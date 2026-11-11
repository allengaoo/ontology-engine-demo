package ont;

public final class Checks {
    private Checks() {}

    public static void bothRollBack() {
        try {
            GlobalTx.run(
                    conn -> Sql.exec(conn, "UPDATE probe SET n = 1 WHERE id = 1"),
                    conn -> Sql.exec(conn, "UPDATE probe SET n = 1 WHERE id = 1"),
                    true);
            fail("两库退回", "准备之后提交前失败，两边竟然都提交了");
        } catch (Exception ignored) {
            // 预期失败。下面核对两边都没有留下 1。
        }
        int purchase = readProbe(true);
        int contract = readProbe(false);
        require("两库退回", purchase == 0 && contract == 0, "采购库 " + purchase + "，合同库 " + contract);
    }

    public static void require(String name, boolean ok, String detail) {
        if (!ok) {
            fail(name, detail);
        }
        System.out.println("通过 " + name + ": " + detail);
    }

    public static void fail(String name, String detail) {
        throw new IllegalStateException("失败 " + name + ": " + detail);
    }

    private static int readProbe(boolean purchase) {
        try (var conn = purchase ? Databases.purchase() : Databases.contract()) {
            return Sql.queryInt(conn, "SELECT n FROM probe WHERE id = 1");
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }
}
