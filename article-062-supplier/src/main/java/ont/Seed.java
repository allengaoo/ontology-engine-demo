package ont;

import java.sql.Connection;
import java.sql.DriverManager;

public final class Seed {
    private Seed() {}

    public static void run() throws Exception {
        seedPurchase();
        seedContract();
        seedDoris();
        OrderIndex.put(Config.PO_MAIN, Config.SUPPLIER_JIA, "待确认");
        OrderIndex.put(Config.PO_RECONCILE, Config.SUPPLIER_JIA, "待确认");
    }

    private static void seedPurchase() throws Exception {
        try (Connection conn = Databases.purchase()) {
            conn.setAutoCommit(false);
            Sql.exec(conn, "INSERT INTO supplier (id, name) VALUES (1, '甲'), (2, '乙'), (3, '丙')");
            Sql.exec(
                    conn,
                    "INSERT INTO purchase_order (id, factory_id, supplier_id, annual_amount) VALUES (?, ?, ?, ?), (?, ?, ?, ?)",
                    Config.PO_MAIN, Config.FACTORY_ID, Config.SUPPLIER_JIA, 2_000_000,
                    Config.PO_RECONCILE, Config.FACTORY_ID, Config.SUPPLIER_JIA, 100_000);
            Sql.exec(
                    conn,
                    "INSERT INTO change_order (id, po_id, new_supplier_id, annual_amount, status) "
                            + "VALUES (?, ?, ?, ?, '待确认'), (?, ?, ?, ?, '待确认')",
                    Config.CHANGE_MAIN, Config.PO_MAIN, Config.SUPPLIER_YI, 2_000_000,
                    Config.CHANGE_RECONCILE, Config.PO_RECONCILE, Config.SUPPLIER_YI, 100_000);
            Sql.exec(conn, "INSERT INTO probe (id, n) VALUES (1, 0)");
            conn.commit();
        }
    }

    private static void seedContract() throws Exception {
        try (Connection conn = Databases.contract()) {
            conn.setAutoCommit(false);
            Sql.exec(
                    conn,
                    "INSERT INTO contract (id, po_id, supplier_id) VALUES (?, ?, ?), (?, ?, ?)",
                    1, Config.PO_MAIN, Config.SUPPLIER_JIA,
                    2, Config.PO_RECONCILE, Config.SUPPLIER_JIA);
            Sql.exec(conn, "INSERT INTO probe (id, n) VALUES (1, 0)");
            conn.commit();
        }
    }

    private static void seedDoris() throws Exception {
        try (Connection conn = DriverManager.getConnection(Config.DORIS_URL, "root", "");
                var statement = conn.createStatement()) {
            insertYear(statement, Config.SUPPLIER_JIA, 96, 4);
            insertYear(statement, Config.SUPPLIER_YI, 82, 18);
            insertYear(statement, Config.SUPPLIER_BING, 95, 5);
            statement.execute(
                    "INSERT INTO ont.purchase_order VALUES (" + Config.PO_MAIN + ", 1, '待确认'), ("
                            + Config.PO_RECONCILE + ", 1, '待确认')");
        }
    }

    private static void insertYear(java.sql.Statement statement, int supplier, int onTime, int late)
            throws Exception {
        int base = onTime / 12;
        int remainder = onTime % 12;
        StringBuilder sql = new StringBuilder("INSERT INTO ont.delivery VALUES ");
        for (int period = 1; period <= 12; period++) {
            if (period > 1) {
                sql.append(", ");
            }
            int on = base + (period <= remainder ? 1 : 0);
            int missed = period <= late % 12 ? late / 12 + 1 : late / 12;
            sql.append("(").append(supplier).append(", ").append(period).append(", ")
                    .append(on).append(", ").append(missed).append(")");
        }
        statement.execute(sql.toString());
    }

    public static void setNewSupplier(int changeId, int supplierId) throws Exception {
        try (Connection conn = Databases.purchase()) {
            conn.setAutoCommit(false);
            Sql.exec(conn, "UPDATE change_order SET new_supplier_id = ? WHERE id = ?", supplierId, changeId);
            conn.commit();
        }
    }
}
