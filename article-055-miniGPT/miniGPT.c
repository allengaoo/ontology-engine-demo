/*
 * ============================================================================
 *  miniGPT.c  —  用纯 C 写一个「迷你大语言模型」
 * ============================================================================
 *
 * 【小结】
 *   大模型是一个巨大的数学函数：输入文字编号，输出「下一个字」的概率。
 *   训练 = 猜错了就按梯度拧参数；推理 = 取概率最高的下一个字。
 *
 * 【快速上手】
 *   gcc miniGPT.c -o miniGPT -lm -O2
 *   ./miniGPT help
 *   ./miniGPT train your.txt
 *   ./miniGPT generate "The "
 *
 * 【训练是否真的在学？】
 *   会。本版实现了交叉熵 → 各层的解析反向传播 → AdamW 更新全部权重。
 *   你应看到 loss 从 ~5.5（随机猜 log(256)）明显下降。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

#define WEIGHTS_PATH "weights.bin"
#define MAX_LAYERS   8

/* ── 配置：略小于「展示用巨型」，方便 CPU 上几分钟内看到 loss 下降 ── */
typedef struct {
    int vocab_size, emb_dim, n_heads, n_layers, ctx_len;
    float lr, beta1, beta2, eps, wd;
    int batch_size, max_iters;
} Config;

static Config CFG = {
    .vocab_size = 256,
    .emb_dim    = 32,
    .n_heads    = 4,     /* 每头 8 维 */
    .n_layers   = 2,
    .ctx_len    = 32,
    .lr         = 1e-3f,
    .beta1      = 0.9f,
    .beta2      = 0.999f,
    .eps        = 1e-8f,
    .wd         = 0.01f,
    .batch_size = 8,
    .max_iters  = 800,
};

/* ══════════════════════════════════════════════════════
 * Tensor：一维 float 缓冲 + 形状元数据；grad 与 data 等长
 * ══════════════════════════════════════════════════════ */
typedef struct {
    float *data, *grad;
    int shape[4], ndim, size;
} Tensor;

static int prod_shape(const int *s, int n) {
    int p = 1; for (int i = 0; i < n; i++) p *= s[i]; return p;
}

static Tensor tnew(const int *shape, int ndim) {
    Tensor t; t.ndim = ndim; t.size = prod_shape(shape, ndim);
    for (int i = 0; i < 4; i++) t.shape[i] = (i < ndim) ? shape[i] : 0;
    t.data = calloc(t.size, sizeof(float));
    t.grad = calloc(t.size, sizeof(float));
    return t;
}

static void tfree(Tensor *t) {
    free(t->data); free(t->grad);
    t->data = t->grad = NULL; t->size = 0;
}

static void tzero_grad(Tensor *t) {
    memset(t->grad, 0, t->size * sizeof(float));
}

static void trandn(Tensor *t, float scale) {
    for (int i = 0; i < t->size; i++) {
        float u1 = (rand() + 1.f) / (RAND_MAX + 1.0);
        float u2 = (rand() + 1.f) / (RAND_MAX + 1.0);
        t->data[i] = scale * sqrtf(-2.f * logf(u1)) * cosf(2.f * 3.14159265f * u2);
    }
}

/* 把可训练张量登记进参数表，方便统一 zero_grad / Adam */
typedef struct { Tensor *t; float *m, *v; } Param;
typedef struct { Param *p; int n, cap; int step; } Optim;

static void optim_add(Optim *o, Tensor *t) {
    if (o->n >= o->cap) {
        o->cap = o->cap ? o->cap * 2 : 64;
        o->p = realloc(o->p, o->cap * sizeof(Param));
    }
    o->p[o->n].t = t;
    o->p[o->n].m = calloc(t->size, sizeof(float));
    o->p[o->n].v = calloc(t->size, sizeof(float));
    o->n++;
}

static void optim_zero(Optim *o) {
    for (int i = 0; i < o->n; i++) tzero_grad(o->p[i].t);
}

static void optim_step(Optim *o, Config *c) {
    o->step++;
    float b1c = 1.f - powf(c->beta1, o->step);
    float b2c = 1.f - powf(c->beta2, o->step);
    for (int i = 0; i < o->n; i++) {
        Param *p = &o->p[i];
        for (int j = 0; j < p->t->size; j++) {
            float g = p->t->grad[j];
            p->m[j] = c->beta1 * p->m[j] + (1.f - c->beta1) * g;
            p->v[j] = c->beta2 * p->v[j] + (1.f - c->beta2) * g * g;
            float mh = p->m[j] / b1c, vh = p->v[j] / b2c;
            p->t->data[j] -= c->lr * (mh / (sqrtf(vh) + c->eps) + c->wd * p->t->data[j]);
        }
    }
}

static void optim_free(Optim *o) {
    for (int i = 0; i < o->n; i++) { free(o->p[i].m); free(o->p[i].v); }
    free(o->p); o->p = NULL; o->n = o->cap = 0;
}

/* ══════════════════════════════════════════════════════
 * 基础算子：Softmax / GELU / LayerNorm / 线性层（含反传）
 * ══════════════════════════════════════════════════════ */
static void softmax_row(float *v, int n) {
    float mx = v[0];
    for (int i = 1; i < n; i++) if (v[i] > mx) mx = v[i];
    float s = 0.f;
    for (int i = 0; i < n; i++) { v[i] = expf(v[i] - mx); s += v[i]; }
    for (int i = 0; i < n; i++) v[i] /= s;
}

static float gelu(float x) {
    const float k = sqrtf(2.f / 3.14159265f);
    return 0.5f * x * (1.f + tanhf(k * (x + 0.044715f * x * x * x)));
}
static float gelu_prime(float x) {
    const float k = sqrtf(2.f / 3.14159265f);
    float u = k * (x + 0.044715f * x * x * x);
    float t = tanhf(u);
    float sech2 = 1.f - t * t;
    float up = k * (1.f + 3.f * 0.044715f * x * x);
    return 0.5f * (1.f + t) + 0.5f * x * sech2 * up;
}

/* LN: 对最后一维 D 归一化。缓存 xhat、rstd 供反传 */
typedef struct { Tensor gamma, beta; } LayerNorm;

static LayerNorm ln_new(int D) {
    int s[1] = {D};
    LayerNorm ln; ln.gamma = tnew(s, 1); ln.beta = tnew(s, 1);
    for (int i = 0; i < D; i++) ln.gamma.data[i] = 1.f;
    return ln;
}

static void ln_forward(LayerNorm *ln, const float *x, float *y,
                       float *xhat, float *rstd, int N, int D) {
    const float eps = 1e-5f;
    for (int n = 0; n < N; n++) {
        const float *xin = x + n * D;
        float mean = 0.f;
        for (int d = 0; d < D; d++) mean += xin[d];
        mean /= D;
        float var = 0.f;
        for (int d = 0; d < D; d++) { float v = xin[d] - mean; var += v * v; }
        var /= D;
        float r = 1.f / sqrtf(var + eps);
        rstd[n] = r;
        for (int d = 0; d < D; d++) {
            float xh = (xin[d] - mean) * r;
            xhat[n * D + d] = xh;
            y[n * D + d] = xh * ln->gamma.data[d] + ln->beta.data[d];
        }
    }
}

static void ln_backward(LayerNorm *ln, const float *dy, const float *xhat,
                        const float *rstd, float *dx, int N, int D) {
    for (int d = 0; d < D; d++) {
        float dg = 0.f, db = 0.f;
        for (int n = 0; n < N; n++) {
            dg += dy[n * D + d] * xhat[n * D + d];
            db += dy[n * D + d];
        }
        ln->gamma.grad[d] += dg;
        ln->beta.grad[d]  += db;
    }
    for (int n = 0; n < N; n++) {
        float r = rstd[n];
        float sum_dy_g = 0.f, sum_dy_g_xh = 0.f;
        for (int d = 0; d < D; d++) {
            float dy_g = dy[n * D + d] * ln->gamma.data[d];
            sum_dy_g += dy_g;
            sum_dy_g_xh += dy_g * xhat[n * D + d];
        }
        for (int d = 0; d < D; d++) {
            float dy_g = dy[n * D + d] * ln->gamma.data[d];
            dx[n * D + d] += r * (dy_g - sum_dy_g / D - xhat[n * D + d] * sum_dy_g_xh / D);
        }
    }
}

/* y[N,O] = x[N,I] @ W[I,O] + b[O] */
static void linear_forward(const float *x, const Tensor *W, const Tensor *b,
                           float *y, int N, int I, int O) {
    for (int n = 0; n < N; n++) {
        for (int o = 0; o < O; o++) {
            float s = b ? b->data[o] : 0.f;
            for (int i = 0; i < I; i++) s += x[n * I + i] * W->data[i * O + o];
            y[n * O + o] = s;
        }
    }
}

static void linear_backward(const float *x, Tensor *W, Tensor *b,
                            const float *dy, float *dx, int N, int I, int O) {
    for (int n = 0; n < N; n++) {
        for (int i = 0; i < I; i++) {
            float s = 0.f;
            for (int o = 0; o < O; o++) {
                float g = dy[n * O + o];
                W->grad[i * O + o] += x[n * I + i] * g;
                s += g * W->data[i * O + o];
            }
            if (dx) dx[n * I + i] += s;
        }
        if (b) for (int o = 0; o < O; o++) b->grad[o] += dy[n * O + o];
    }
}

/* ══════════════════════════════════════════════════════
 * 一层 Transformer：MHA + FFN + 残差（前向缓存供反传）
 * ══════════════════════════════════════════════════════ */
typedef struct {
    Tensor Wq, Wk, Wv, Wo;
    Tensor W1, b1, W2, b2;
    LayerNorm ln1, ln2;
} Block;

/* 单层前向缓存 */
typedef struct {
    float *x;          /* 层输入 [B*T*D] */
    float *ln1_y, *ln1_xhat, *ln1_rstd;
    float *q, *k, *v;  /* [B*T*D] */
    float *attn;       /* [B*H*T*T] softmax 后 */
    float *ctx;        /* 注意力聚合 [B*T*D] */
    float *attn_out;   /* 经 Wo [B*T*D] */
    float *res1;       /* x + attn_out */
    float *ln2_y, *ln2_xhat, *ln2_rstd;
    float *ffn_h;      /* GELU 前 [B*T*4D] */
    float *ffn_a;      /* GELU 后 */
    float *ffn_out;    /* [B*T*D] */
    float *out;        /* res1 + ffn_out */
} BlockCache;

typedef struct {
    Tensor tok_emb, pos_emb, out_head;
    Block blocks[MAX_LAYERS];
    LayerNorm final_ln;
    Optim opt;
} GPT;

static Block block_new(int D, int H) {
    (void)H;
    int sDD[2] = {D, D}, sD4[2] = {D, 4 * D}, s4D[2] = {4 * D, D};
    int s4[1] = {4 * D}, s1[1] = {D};
    Block b;
    b.Wq = tnew(sDD, 2); trandn(&b.Wq, 0.02f);
    b.Wk = tnew(sDD, 2); trandn(&b.Wk, 0.02f);
    b.Wv = tnew(sDD, 2); trandn(&b.Wv, 0.02f);
    b.Wo = tnew(sDD, 2); trandn(&b.Wo, 0.02f);
    b.W1 = tnew(sD4, 2); trandn(&b.W1, 0.02f);
    b.b1 = tnew(s4, 1);
    b.W2 = tnew(s4D, 2); trandn(&b.W2, 0.02f);
    b.b2 = tnew(s1, 1);
    b.ln1 = ln_new(D); b.ln2 = ln_new(D);
    return b;
}

static void block_register(Optim *o, Block *b) {
    optim_add(o, &b->Wq); optim_add(o, &b->Wk); optim_add(o, &b->Wv); optim_add(o, &b->Wo);
    optim_add(o, &b->W1); optim_add(o, &b->b1); optim_add(o, &b->W2); optim_add(o, &b->b2);
    optim_add(o, &b->ln1.gamma); optim_add(o, &b->ln1.beta);
    optim_add(o, &b->ln2.gamma); optim_add(o, &b->ln2.beta);
}

static BlockCache *bcache_new(int B, int T, int D, int H) {
    BlockCache *c = calloc(1, sizeof(BlockCache));
    int N = B * T, TT = T * T;
    c->x = calloc(N * D, sizeof(float));
    c->ln1_y = calloc(N * D, sizeof(float));
    c->ln1_xhat = calloc(N * D, sizeof(float));
    c->ln1_rstd = calloc(N, sizeof(float));
    c->q = calloc(N * D, sizeof(float));
    c->k = calloc(N * D, sizeof(float));
    c->v = calloc(N * D, sizeof(float));
    c->attn = calloc(B * H * TT, sizeof(float));
    c->ctx = calloc(N * D, sizeof(float));
    c->attn_out = calloc(N * D, sizeof(float));
    c->res1 = calloc(N * D, sizeof(float));
    c->ln2_y = calloc(N * D, sizeof(float));
    c->ln2_xhat = calloc(N * D, sizeof(float));
    c->ln2_rstd = calloc(N, sizeof(float));
    c->ffn_h = calloc(N * 4 * D, sizeof(float));
    c->ffn_a = calloc(N * 4 * D, sizeof(float));
    c->ffn_out = calloc(N * D, sizeof(float));
    c->out = calloc(N * D, sizeof(float));
    return c;
}

static void bcache_free(BlockCache *c) {
    if (!c) return;
    free(c->x); free(c->ln1_y); free(c->ln1_xhat); free(c->ln1_rstd);
    free(c->q); free(c->k); free(c->v); free(c->attn); free(c->ctx);
    free(c->attn_out); free(c->res1);
    free(c->ln2_y); free(c->ln2_xhat); free(c->ln2_rstd);
    free(c->ffn_h); free(c->ffn_a); free(c->ffn_out); free(c->out);
    free(c);
}

/* 多头因果注意力前向，写入 cache */
static void mha_forward(Block *b, BlockCache *c, int B, int T, int D, int H) {
    int N = B * T, dh = D / H;
    float scale = 1.f / sqrtf((float)dh);
    linear_forward(c->ln1_y, &b->Wq, NULL, c->q, N, D, D);
    linear_forward(c->ln1_y, &b->Wk, NULL, c->k, N, D, D);
    linear_forward(c->ln1_y, &b->Wv, NULL, c->v, N, D, D);
    memset(c->ctx, 0, N * D * sizeof(float));

    for (int bb = 0; bb < B; bb++) {
        for (int h = 0; h < H; h++) {
            float *attn = c->attn + ((bb * H + h) * T * T);
            for (int i = 0; i < T; i++) {
                for (int j = 0; j < T; j++) {
                    if (j > i) { attn[i * T + j] = 0.f; continue; }
                    float dot = 0.f;
                    for (int d = 0; d < dh; d++) {
                        float qi = c->q[(bb * T + i) * D + h * dh + d];
                        float kj = c->k[(bb * T + j) * D + h * dh + d];
                        dot += qi * kj;
                    }
                    attn[i * T + j] = dot * scale;
                }
                /* 只对 j<=i 的有效分数做 softmax：先写 -inf 再统一 softmax */
                for (int j = 0; j < T; j++)
                    if (j > i) attn[i * T + j] = -1e9f;
                softmax_row(attn + i * T, T);
            }
            for (int i = 0; i < T; i++) {
                for (int d = 0; d < dh; d++) {
                    float s = 0.f;
                    for (int j = 0; j < T; j++) {
                        float vv = c->v[(bb * T + j) * D + h * dh + d];
                        s += attn[i * T + j] * vv;
                    }
                    c->ctx[(bb * T + i) * D + h * dh + d] = s;
                }
            }
        }
    }
    linear_forward(c->ctx, &b->Wo, NULL, c->attn_out, N, D, D);
}

static void mha_backward(Block *b, BlockCache *c, float *d_ln1_y,
                         const float *d_attn_out, int B, int T, int D, int H) {
    int N = B * T, dh = D / H;
    float scale = 1.f / sqrtf((float)dh);
    float *d_ctx = calloc(N * D, sizeof(float));
    float *d_q = calloc(N * D, sizeof(float));
    float *d_k = calloc(N * D, sizeof(float));
    float *d_v = calloc(N * D, sizeof(float));

    linear_backward(c->ctx, &b->Wo, NULL, d_attn_out, d_ctx, N, D, D);

    for (int bb = 0; bb < B; bb++) {
        for (int h = 0; h < H; h++) {
            float *attn = c->attn + ((bb * H + h) * T * T);
            float *d_attn = calloc(T * T, sizeof(float));

            /* ctx = attn @ V  →  d_attn, d_v */
            for (int i = 0; i < T; i++) {
                for (int d = 0; d < dh; d++) {
                    float g = d_ctx[(bb * T + i) * D + h * dh + d];
                    for (int j = 0; j < T; j++) {
                        d_attn[i * T + j] += g * c->v[(bb * T + j) * D + h * dh + d];
                        d_v[(bb * T + j) * D + h * dh + d] += g * attn[i * T + j];
                    }
                }
            }
            /* softmax 反传（对每一行） */
            for (int i = 0; i < T; i++) {
                float *p = attn + i * T;
                float *dp = d_attn + i * T;
                float sum = 0.f;
                for (int j = 0; j < T; j++) sum += dp[j] * p[j];
                for (int j = 0; j < T; j++) {
                    float ds = p[j] * (dp[j] - sum); /* d(score) */
                    if (j > i) continue;
                    for (int d = 0; d < dh; d++) {
                        float qi = c->q[(bb * T + i) * D + h * dh + d];
                        float kj = c->k[(bb * T + j) * D + h * dh + d];
                        d_q[(bb * T + i) * D + h * dh + d] += ds * scale * kj;
                        d_k[(bb * T + j) * D + h * dh + d] += ds * scale * qi;
                    }
                }
            }
            free(d_attn);
        }
    }

    linear_backward(c->ln1_y, &b->Wq, NULL, d_q, d_ln1_y, N, D, D);
    linear_backward(c->ln1_y, &b->Wk, NULL, d_k, d_ln1_y, N, D, D);
    linear_backward(c->ln1_y, &b->Wv, NULL, d_v, d_ln1_y, N, D, D);

    free(d_ctx); free(d_q); free(d_k); free(d_v);
}

static void block_forward(Block *b, BlockCache *c, const float *x,
                          int B, int T, int D, int H) {
    int N = B * T;
    memcpy(c->x, x, N * D * sizeof(float));
    ln_forward(&b->ln1, c->x, c->ln1_y, c->ln1_xhat, c->ln1_rstd, N, D);
    mha_forward(b, c, B, T, D, H);
    for (int i = 0; i < N * D; i++) c->res1[i] = c->x[i] + c->attn_out[i];

    ln_forward(&b->ln2, c->res1, c->ln2_y, c->ln2_xhat, c->ln2_rstd, N, D);
    linear_forward(c->ln2_y, &b->W1, &b->b1, c->ffn_h, N, D, 4 * D);
    for (int i = 0; i < N * 4 * D; i++) c->ffn_a[i] = gelu(c->ffn_h[i]);
    linear_forward(c->ffn_a, &b->W2, &b->b2, c->ffn_out, N, 4 * D, D);
    for (int i = 0; i < N * D; i++) c->out[i] = c->res1[i] + c->ffn_out[i];
}

static void block_backward(Block *b, BlockCache *c, float *dx,
                           const float *dout, int B, int T, int D, int H) {
    int N = B * T;
    float *d_res1 = calloc(N * D, sizeof(float));
    float *d_ffn_out = calloc(N * D, sizeof(float));
    float *d_ln2_y = calloc(N * D, sizeof(float));
    float *d_ffn_a = calloc(N * 4 * D, sizeof(float));
    float *d_ffn_h = calloc(N * 4 * D, sizeof(float));
    float *d_attn_out = calloc(N * D, sizeof(float));
    float *d_ln1_y = calloc(N * D, sizeof(float));

    /* 残差：dout 同时流向 ffn_out 与 res1 */
    for (int i = 0; i < N * D; i++) {
        d_ffn_out[i] += dout[i];
        d_res1[i] += dout[i];
    }
    linear_backward(c->ffn_a, &b->W2, &b->b2, d_ffn_out, d_ffn_a, N, 4 * D, D);
    for (int i = 0; i < N * 4 * D; i++)
        d_ffn_h[i] += d_ffn_a[i] * gelu_prime(c->ffn_h[i]);
    linear_backward(c->ln2_y, &b->W1, &b->b1, d_ffn_h, d_ln2_y, N, D, 4 * D);
    ln_backward(&b->ln2, d_ln2_y, c->ln2_xhat, c->ln2_rstd, d_res1, N, D);

    /* 残差：d_res1 流向 x 与 attn_out */
    for (int i = 0; i < N * D; i++) {
        dx[i] += d_res1[i];
        d_attn_out[i] += d_res1[i];
    }
    mha_backward(b, c, d_ln1_y, d_attn_out, B, T, D, H);
    ln_backward(&b->ln1, d_ln1_y, c->ln1_xhat, c->ln1_rstd, dx, N, D);

    free(d_res1); free(d_ffn_out); free(d_ln2_y); free(d_ffn_a);
    free(d_ffn_h); free(d_attn_out); free(d_ln1_y);
}

/* ══════════════════════════════════════════════════════
 * GPT 整体
 * ══════════════════════════════════════════════════════ */
typedef struct {
    int *ids;                 /* [B*T] */
    float *emb;               /* [B*T*D] */
    BlockCache *bc[MAX_LAYERS];
    float *x_layers[MAX_LAYERS + 1]; /* 每层输入；[0]=emb */
    float *fln_y, *fln_xhat, *fln_rstd;
    float *logits;            /* [B*T*V] */
    int B, T, D, V, H, L;
} RunCache;

static GPT gpt_create(Config *c) {
    GPT g; memset(&g, 0, sizeof(g));
    int s_tok[2] = {c->vocab_size, c->emb_dim};
    int s_pos[2] = {c->ctx_len, c->emb_dim};
    int s_out[2] = {c->emb_dim, c->vocab_size};
    g.tok_emb = tnew(s_tok, 2); trandn(&g.tok_emb, 0.02f);
    g.pos_emb = tnew(s_pos, 2); trandn(&g.pos_emb, 0.02f);
    g.out_head = tnew(s_out, 2); trandn(&g.out_head, 0.02f);
    g.final_ln = ln_new(c->emb_dim);
    for (int i = 0; i < c->n_layers; i++) g.blocks[i] = block_new(c->emb_dim, c->n_heads);

    memset(&g.opt, 0, sizeof(g.opt));
    optim_add(&g.opt, &g.tok_emb);
    optim_add(&g.opt, &g.pos_emb);
    for (int i = 0; i < c->n_layers; i++) block_register(&g.opt, &g.blocks[i]);
    optim_add(&g.opt, &g.final_ln.gamma);
    optim_add(&g.opt, &g.final_ln.beta);
    optim_add(&g.opt, &g.out_head);
    return g;
}

static RunCache *rcache_new(Config *c, int B) {
    RunCache *r = calloc(1, sizeof(RunCache));
    r->B = B; r->T = c->ctx_len; r->D = c->emb_dim; r->V = c->vocab_size;
    r->H = c->n_heads; r->L = c->n_layers;
    int N = B * r->T;
    r->ids = calloc(N, sizeof(int));
    r->emb = calloc(N * r->D, sizeof(float));
    for (int l = 0; l <= r->L; l++)
        r->x_layers[l] = calloc(N * r->D, sizeof(float));
    for (int l = 0; l < r->L; l++)
        r->bc[l] = bcache_new(B, r->T, r->D, r->H);
    r->fln_y = calloc(N * r->D, sizeof(float));
    r->fln_xhat = calloc(N * r->D, sizeof(float));
    r->fln_rstd = calloc(N, sizeof(float));
    r->logits = calloc(N * r->V, sizeof(float));
    return r;
}

static void rcache_free(RunCache *r) {
    if (!r) return;
    free(r->ids); free(r->emb);
    for (int l = 0; l <= r->L; l++) free(r->x_layers[l]);
    for (int l = 0; l < r->L; l++) bcache_free(r->bc[l]);
    free(r->fln_y); free(r->fln_xhat); free(r->fln_rstd); free(r->logits);
    free(r);
}

static void embed_forward(GPT *g, RunCache *r) {
    int B = r->B, T = r->T, D = r->D;
    for (int b = 0; b < B; b++)
        for (int t = 0; t < T; t++) {
            int id = r->ids[b * T + t];
            for (int d = 0; d < D; d++)
                r->emb[(b * T + t) * D + d] =
                    g->tok_emb.data[id * D + d] + g->pos_emb.data[t * D + d];
        }
    memcpy(r->x_layers[0], r->emb, B * T * D * sizeof(float));
}

static void embed_backward(GPT *g, RunCache *r, const float *demb) {
    int B = r->B, T = r->T, D = r->D;
    for (int b = 0; b < B; b++)
        for (int t = 0; t < T; t++) {
            int id = r->ids[b * T + t];
            for (int d = 0; d < D; d++) {
                float gval = demb[(b * T + t) * D + d];
                g->tok_emb.grad[id * D + d] += gval;
                g->pos_emb.grad[t * D + d] += gval;
            }
        }
}

/* 前向：返回平均交叉熵；targets[B*T]；若 want_grad 则填 logits 供反传 */
static float gpt_forward(GPT *g, RunCache *r, const int *targets) {
    int B = r->B, T = r->T, D = r->D, V = r->V, N = B * T;
    embed_forward(g, r);
    for (int l = 0; l < r->L; l++) {
        block_forward(&g->blocks[l], r->bc[l], r->x_layers[l], B, T, D, r->H);
        memcpy(r->x_layers[l + 1], r->bc[l]->out, N * D * sizeof(float));
    }
    ln_forward(&g->final_ln, r->x_layers[r->L], r->fln_y, r->fln_xhat, r->fln_rstd, N, D);
    linear_forward(r->fln_y, &g->out_head, NULL, r->logits, N, D, V);

    float loss = 0.f;
    for (int n = 0; n < N; n++) {
        float *row = r->logits + n * V;
        float mx = row[0];
        for (int v = 1; v < V; v++) if (row[v] > mx) mx = row[v];
        float sum = 0.f;
        for (int v = 0; v < V; v++) sum += expf(row[v] - mx);
        int y = targets[n];
        loss += -(row[y] - mx) + logf(sum);
    }
    return loss / N;
}

/*
 * 反传核心：
 *   dL/dlogit = (softmax(logit) - onehot(y)) / N
 *   再逐层回传，最后更新 embedding。
 */
static void gpt_backward(GPT *g, RunCache *r, const int *targets) {
    int B = r->B, T = r->T, D = r->D, V = r->V, N = B * T;
    float *dlogits = calloc(N * V, sizeof(float));
    float *d_fln_y = calloc(N * D, sizeof(float));
    float *d_x = calloc(N * D, sizeof(float));

    for (int n = 0; n < N; n++) {
        float *row = r->logits + n * V;
        float tmp[256];
        memcpy(tmp, row, V * sizeof(float));
        softmax_row(tmp, V);
        for (int v = 0; v < V; v++)
            dlogits[n * V + v] = tmp[v] / N;
        dlogits[n * V + targets[n]] -= 1.f / N;
    }

    linear_backward(r->fln_y, &g->out_head, NULL, dlogits, d_fln_y, N, D, V);
    memset(d_x, 0, N * D * sizeof(float));
    ln_backward(&g->final_ln, d_fln_y, r->fln_xhat, r->fln_rstd, d_x, N, D);

    for (int l = r->L - 1; l >= 0; l--) {
        float *dx_in = calloc(N * D, sizeof(float));
        block_backward(&g->blocks[l], r->bc[l], dx_in, d_x, B, T, D, r->H);
        memcpy(d_x, dx_in, N * D * sizeof(float));
        free(dx_in);
    }
    embed_backward(g, r, d_x);

    free(dlogits); free(d_fln_y); free(d_x);
}

/* 推理用轻量前向（不建完整 RunCache 的 generate 路径） */
static void gpt_logits_one(GPT *g, Config *c, const int *ids, float *logits_last) {
    RunCache *r = rcache_new(c, 1);
    memcpy(r->ids, ids, c->ctx_len * sizeof(int));
    int zeros[256]; /* dummy targets unused for loss value path */
    for (int i = 0; i < c->ctx_len; i++) zeros[i] = 0;
    (void)gpt_forward(g, r, zeros);
    int T = c->ctx_len, V = c->vocab_size, D = c->emb_dim;
    (void)D;
    memcpy(logits_last, r->logits + (T - 1) * V, V * sizeof(float));
    rcache_free(r);
}

/* ── 存盘 / 读盘 ── */
static void tw(FILE *fp, Tensor *t) { fwrite(t->data, sizeof(float), t->size, fp); }
static void tr(FILE *fp, Tensor *t) {
    if (fread(t->data, sizeof(float), t->size, fp) != (size_t)t->size) {
        fprintf(stderr, "读取权重失败\n"); exit(1);
    }
}

static void save_weights(GPT *g, Config *c, const char *path) {
    FILE *fp = fopen(path, "wb");
    if (!fp) { perror(path); exit(1); }
    fwrite(c, sizeof(Config), 1, fp);
    tw(fp, &g->tok_emb); tw(fp, &g->pos_emb);
    for (int i = 0; i < c->n_layers; i++) {
        Block *b = &g->blocks[i];
        tw(fp, &b->Wq); tw(fp, &b->Wk); tw(fp, &b->Wv); tw(fp, &b->Wo);
        tw(fp, &b->W1); tw(fp, &b->b1); tw(fp, &b->W2); tw(fp, &b->b2);
        tw(fp, &b->ln1.gamma); tw(fp, &b->ln1.beta);
        tw(fp, &b->ln2.gamma); tw(fp, &b->ln2.beta);
    }
    tw(fp, &g->final_ln.gamma); tw(fp, &g->final_ln.beta); tw(fp, &g->out_head);
    fclose(fp);
    printf("已保存权重 → %s\n", path);
}

static void load_weights(GPT *g, Config *c, const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        fprintf(stderr, "找不到 %s，请先 ./miniGPT train <文本>\n", path);
        exit(1);
    }
    Config s;
    fread(&s, sizeof(Config), 1, fp);
    if (s.vocab_size != c->vocab_size || s.emb_dim != c->emb_dim ||
        s.n_heads != c->n_heads || s.n_layers != c->n_layers || s.ctx_len != c->ctx_len) {
        fprintf(stderr, "weights.bin 与当前 Config 不一致，请用同一份源码重新训练。\n");
        exit(1);
    }
    tr(fp, &g->tok_emb); tr(fp, &g->pos_emb);
    for (int i = 0; i < c->n_layers; i++) {
        Block *b = &g->blocks[i];
        tr(fp, &b->Wq); tr(fp, &b->Wk); tr(fp, &b->Wv); tr(fp, &b->Wo);
        tr(fp, &b->W1); tr(fp, &b->b1); tr(fp, &b->W2); tr(fp, &b->b2);
        tr(fp, &b->ln1.gamma); tr(fp, &b->ln1.beta);
        tr(fp, &b->ln2.gamma); tr(fp, &b->ln2.beta);
    }
    tr(fp, &g->final_ln.gamma); tr(fp, &g->final_ln.beta); tr(fp, &g->out_head);
    fclose(fp);
    printf("已加载权重 ← %s\n", path);
}

/* ══════════════════════════════════════════════════════
 * 生成：
 * ══════════════════════════════════════════════════════ */
static void generate(GPT *g, Config *c, const char *prompt, int n_tokens) {
    int T = c->ctx_len, V = c->vocab_size;
    int *ids = calloc(T, sizeof(int));
    int plen = (int)strlen(prompt);
    int cur = 0;
    for (int i = 0; i < T; i++)
        ids[i] = (i < plen) ? (unsigned char)prompt[i] : (int)' ';
    cur = plen < T ? plen : T;

    printf("提示词: %s\n生成: ", prompt);
    float *logits = malloc(V * sizeof(float));
    for (int step = 0; step < n_tokens; step++) {
        gpt_logits_one(g, c, ids, logits);
        softmax_row(logits, V);
        /* 在可打印 ASCII 中取最大，避免控制字符/非法 UTF-8 */
        int best = 32;
        float bestp = -1.f;
        for (int v = 32; v < 127; v++)
            if (logits[v] > bestp) { bestp = logits[v]; best = v; }
        putchar(best);
        fflush(stdout);
        if (cur < T) ids[cur++] = best;
        else { memmove(ids, ids + 1, (T - 1) * sizeof(int)); ids[T - 1] = best; }
    }
    printf("\n");
    free(ids); free(logits);
}

/* ══════════════════════════════════════════════════════
 * 训练：前向 → 反传 → AdamW，loss 应明显下降
 * ══════════════════════════════════════════════════════ */
static void train(const char *filename) {
    FILE *f = fopen(filename, "r");
    if (!f) { perror(filename); exit(1); }
    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    rewind(f);
    if (fsize < CFG.ctx_len + 2) {
        fprintf(stderr, "文本至少需要 %d 字节\n", CFG.ctx_len + 2);
        exit(1);
    }
    char *text = malloc(fsize + 1);
    fread(text, 1, fsize, f);
    text[fsize] = '\0';
    fclose(f);

    srand(42);
    GPT g = gpt_create(&CFG);
    int B = CFG.batch_size, T = CFG.ctx_len;
    RunCache *rc = rcache_new(&CFG, B);
    int *targets = malloc(B * T * sizeof(int));

    printf("======== 开始训练（含解析反传 + AdamW）========\n");
    printf("语料: %s (%ld 字节)\n", filename, fsize);
    printf("配置: layers=%d dim=%d heads=%d ctx=%d batch=%d iters=%d lr=%g\n",
           CFG.n_layers, CFG.emb_dim, CFG.n_heads, CFG.ctx_len,
           CFG.batch_size, CFG.max_iters, CFG.lr);
    printf("随机猜 loss 约 log(256)=%.3f；若反传正确，曲线应持续下降。\n\n", logf(256.f));

    float loss0 = -1.f;
    for (int iter = 0; iter < CFG.max_iters; iter++) {
        for (int b = 0; b < B; b++) {
            int start = rand() % (fsize - T - 1);
            for (int t = 0; t < T; t++) {
                rc->ids[b * T + t] = (unsigned char)text[start + t];
                targets[b * T + t] = (unsigned char)text[start + t + 1];
            }
        }
        optim_zero(&g.opt);
        float loss = gpt_forward(&g, rc, targets);
        gpt_backward(&g, rc, targets);
        optim_step(&g.opt, &CFG);

        if (iter == 0) loss0 = loss;
        if (iter % 50 == 0 || iter == CFG.max_iters - 1) {
            printf("[训练] iter %4d/%d  loss=%.4f  (相对初始 %+.2f%%)\n",
                   iter, CFG.max_iters, loss, 100.f * (loss - loss0) / loss0);
        }
        if (iter > 0 && iter % 200 == 0) {
            printf("---- 中途试推理 ----\n");
            generate(&g, &CFG, "The ", 80);
        }
    }

    save_weights(&g, &CFG, WEIGHTS_PATH);
    printf("\n最终 loss= 见上；初始 loss≈%.4f。若明显下降，说明反传生效。\n", loss0);
    printf("推理: ./miniGPT generate \"The \"\n");

    free(text); free(targets); rcache_free(rc); optim_free(&g.opt);
}

static void print_help(const char *prog) {
    printf(
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
"  miniGPT — 纯 C 迷你 GPT（解析反传，可真正降 loss）\n"
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
"\n"
"编译:\n"
"  gcc miniGPT.c -o miniGPT -lm -O2\n"
"\n"
"训练:\n"
"  %s train your.txt\n"
"  · 练习「猜下一个字节」；每步：前向算 loss → 反传梯度 → AdamW 更新\n"
"  · 结束写入 weights.bin\n"
"\n"
"推理:\n"
"  %s generate \"The \"\n"
"  · 需先训练；只输出可打印 ASCII，避免终端乱码观感\n"
"\n"
"帮助: %s help\n"
"\n"
"说明: 默认 2 层×32 维，便于 CPU 快速验证。骨架与大模型相同，差在规模。\n"
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        prog, prog, prog);
}

int main(int argc, char **argv) {
    if (argc < 2 || !strcmp(argv[1], "help") || !strcmp(argv[1], "-h") || !strcmp(argv[1], "--help")) {
        print_help(argc ? argv[0] : "./miniGPT");
        return argc < 2 ? 1 : 0;
    }
    if (!strcmp(argv[1], "train")) {
        if (argc < 3) { print_help(argv[0]); return 1; }
        train(argv[2]);
        return 0;
    }
    if (!strcmp(argv[1], "generate")) {
        if (argc < 3) { print_help(argv[0]); return 1; }
        srand(42);
        GPT g = gpt_create(&CFG);
        load_weights(&g, &CFG, WEIGHTS_PATH);
        generate(&g, &CFG, argv[2], 200);
        optim_free(&g.opt);
        return 0;
    }
    fprintf(stderr, "未知命令: %s\n", argv[1]);
    print_help(argv[0]);
    return 1;
}
