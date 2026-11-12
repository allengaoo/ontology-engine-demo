package ont;

import java.util.List;

public final class Checks {
    private Checks() {}

    public static void lookup(List<Integer> orders, List<DorisRate.Agg> aggs) {
        require(
                "0 索引返回工厂 7 号的两张采购单",
                orders.size() == 2 && orders.get(0) == Config.PO_MAIN && orders.get(1) == Config.PO_RECONCILE,
                "采购单 " + orders);
        int low = 0;
        StringBuilder detail = new StringBuilder();
        for (DorisRate.Agg agg : aggs) {
            detail.append(Log.supplier(agg.supplierId())).append(" ")
                    .append(Log.rate(agg.rate())).append("/").append(agg.rows()).append(" ");
            if (agg.rows() != 12) {
                fail("0 交货记录行数", detail.toString());
            }
            if (agg.rate() < Config.RATE_CUTOFF) {
                low++;
                if (agg.supplierId() != Config.SUPPLIER_YI || !"0.82".equals(Log.rate(agg.rate()))) {
                    fail("0 低于 90% 的供应商", detail.toString());
                }
            }
        }
        require("0 汇总后低于 90% 的只有乙", low == 1 && aggs.size() == 3, detail.toString());
    }

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
