package ont;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

public final class DorisRate {
    private DorisRate() {}

    public static void waitUntilAlive() throws Exception {
        Instant deadline = Instant.now().plus(Duration.ofSeconds(180));
        String last = "还没有连上";
        while (Instant.now().isBefore(deadline)) {
            try (Connection conn = DriverManager.getConnection(Config.DORIS_URL, "root", "")) {
                if (backendAlive(conn)) {
                    System.out.println("就绪 Doris BE");
                    return;
                }
                last = "BE 尚未 Alive";
                addBackend(conn);
            } catch (Exception ex) {
                last = ex.getMessage();
            }
            Thread.sleep(2000);
        }
        throw new IllegalStateException("Doris 没有就绪: " + last);
    }

    public static void resetTables() throws Exception {
        try (Connection conn = DriverManager.getConnection(Config.DORIS_URL, "root", "");
                Statement statement = conn.createStatement()) {
            statement.execute("CREATE DATABASE IF NOT EXISTS ont");
            statement.execute("DROP TABLE IF EXISTS ont.delivery");
            statement.execute("DROP TABLE IF EXISTS ont.purchase_order");
            statement.execute(deliveryDdl());
            statement.execute(orderDdl());
        }
    }

    public record Agg(int supplierId, double rate, int rows) {}

    public static List<Agg> aggregate() {
        String sql = "SELECT supplier_id, SUM(on_time) * 1.0 / (SUM(on_time) + SUM(late)), COUNT(*) "
                + "FROM ont.delivery GROUP BY supplier_id ORDER BY supplier_id";
        List<Agg> aggs = new ArrayList<>();
        try (Connection conn = DriverManager.getConnection(Config.DORIS_URL, "root", "");
                Statement statement = conn.createStatement();
                ResultSet rows = statement.executeQuery(sql)) {
            while (rows.next()) {
                aggs.add(new Agg(rows.getInt(1), rows.getDouble(2), rows.getInt(3)));
            }
            return aggs;
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public static Double of(int supplierId) {
        String sql = "SELECT SUM(on_time) * 1.0 / (SUM(on_time) + SUM(late)) "
                + "FROM ont.delivery WHERE supplier_id = ?";
        try (Connection conn = DriverManager.getConnection(Config.DORIS_URL, "root", "");
                var statement = conn.prepareStatement(sql)) {
            statement.setInt(1, supplierId);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next() || rows.getObject(1) == null) {
                    return null;
                }
                return rows.getDouble(1);
            }
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static boolean backendAlive(Connection conn) throws Exception {
        try (Statement statement = conn.createStatement();
                ResultSet rows = statement.executeQuery("SHOW BACKENDS")) {
            int alive = column(rows, "Alive");
            while (rows.next()) {
                if ("true".equalsIgnoreCase(rows.getString(alive))) {
                    return true;
                }
            }
            return false;
        }
    }

    private static void addBackend(Connection conn) {
        try (Statement statement = conn.createStatement()) {
            statement.execute("ALTER SYSTEM ADD BACKEND \"172.30.62.11:9050\"");
        } catch (Exception ignored) {
            // 已经注册过就继续等 Alive。
        }
    }

    private static int column(ResultSet rows, String name) throws Exception {
        var meta = rows.getMetaData();
        for (int i = 1; i <= meta.getColumnCount(); i++) {
            if (name.equalsIgnoreCase(meta.getColumnLabel(i))) {
                return i;
            }
        }
        throw new IllegalStateException("SHOW BACKENDS 没有 " + name);
    }

    private static String deliveryDdl() {
        return "CREATE TABLE ont.delivery (supplier_id INT, period INT, on_time INT, late INT) "
                + "DUPLICATE KEY(supplier_id, period) DISTRIBUTED BY HASH(supplier_id) BUCKETS 1 "
                + "PROPERTIES (\"replication_num\" = \"1\")";
    }

    private static String orderDdl() {
        return "CREATE TABLE ont.purchase_order (id INT, supplier_id INT, status VARCHAR(32)) "
                + "UNIQUE KEY(id) DISTRIBUTED BY HASH(id) BUCKETS 1 "
                + "PROPERTIES (\"replication_num\" = \"1\")";
    }
}
