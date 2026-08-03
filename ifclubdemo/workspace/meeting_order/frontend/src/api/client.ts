export const apiBase = "/api/v1";

/** path 只写 /rooms、/bookings；已带 /api/v1 则不再重复拼接。 */
export function joinApiPath(path: string): string {
  const p = (path || '').trim();
  if (!p) return apiBase;
  const normalized = p.startsWith('/') ? p : `/${p}`;
  if (normalized === apiBase || normalized.startsWith(`${apiBase}/`)) return normalized;
  if (normalized.startsWith('/api/')) return normalized;
  return `${apiBase}${normalized}`;
}

async function raiseForResponse(res: Response): Promise<never> {
  const text = await res.text();
  try {
    const data = JSON.parse(text);
    const detail = data?.detail;
    if (typeof detail === 'string') throw new Error(detail);
    if (detail?.message) throw new Error(String(detail.message));
  } catch (e) {
    if (e instanceof Error && e.message && !e.message.startsWith('{')) throw e;
  }
  throw new Error(text || `HTTP ${res.status}`);
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(joinApiPath(path));
  if (!res.ok) await raiseForResponse(res);
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(joinApiPath(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await raiseForResponse(res);
  return res.json();
}