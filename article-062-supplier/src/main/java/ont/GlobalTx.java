package ont;

import io.seata.core.exception.TransactionException;
import io.seata.rm.RMClient;
import io.seata.tm.TMClient;
import io.seata.tm.api.GlobalTransaction;
import io.seata.tm.api.GlobalTransactionContext;
import java.sql.Connection;
import java.sql.SQLException;
import javax.sql.DataSource;

/** 两个 PostgreSQL 各注册一个 XA 分支。都准备好，TC 才通知提交。 */
public final class GlobalTx {
    private static String lastXid = "";

    private GlobalTx() {}

    public static void init() {
        TMClient.init("supplier-demo", Config.TX_GROUP);
        RMClient.init("supplier-demo", Config.TX_GROUP);
        Log.line("Seata 客户端已注册，事务组 " + Config.TX_GROUP);
    }

    public static void shutdown() {
        io.seata.core.rpc.ShutdownHook.getInstance().destroyAll();
    }

    public static String lastXid() {
        return lastXid;
    }

    public static void run(SqlWork purchase, SqlWork contract) {
        run(purchase, contract, false);
    }

    /** failAfterPrepare 为真时，两个分支都完成 XA prepare，然后在全局提交前失败。 */
    public static void run(SqlWork purchase, SqlWork contract, boolean failAfterPrepare) {
        GlobalTransaction tx = GlobalTransactionContext.getCurrentOrCreate();
        boolean began = false;
        try {
            tx.begin(60_000, "supplier-change");
            began = true;
            lastXid = tx.getXid();
            Log.line("全局事务开始 " + lastXid);
            branch("采购库", Databases.purchaseXa(), purchase);
            branch("合同库", Databases.contractXa(), contract);
            if (failAfterPrepare) {
                Log.line("两个分支都已准备，提交前失败，回滚 " + lastXid);
                throw new IllegalStateException("两边都已准备，提交前失败");
            }
            tx.commit();
            Log.line("全局事务已提交 " + lastXid);
        } catch (RuntimeException ex) {
            rollback(tx, began);
            throw ex;
        } catch (Exception ex) {
            rollback(tx, began);
            throw new IllegalStateException(ex);
        }
    }

    private static void branch(String name, DataSource source, SqlWork work) throws Exception {
        try (Connection conn = source.getConnection()) {
            conn.setAutoCommit(false);
            work.accept(conn);
            conn.commit();
            Log.line(name + " XA prepare 完成");
        }
    }

    private static void rollback(GlobalTransaction tx, boolean began) {
        if (!began) {
            return;
        }
        try {
            tx.rollback();
            Log.line("全局事务已回滚 " + tx.getXid());
        } catch (TransactionException ignored) {
            // 调用方看到的是原先的失败。
        }
    }

    @FunctionalInterface
    public interface SqlWork {
        void accept(Connection conn) throws SQLException;
    }
}
