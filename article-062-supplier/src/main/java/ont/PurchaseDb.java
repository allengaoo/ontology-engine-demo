package ont;

import java.sql.Connection;
import java.sql.SQLException;

public final class PurchaseDb {
    private PurchaseDb() {}

    public static ChangeRow load(int changeId) {
        String sql = "SELECT id, po_id, new_supplier_id, annual_amount, status "
                + "FROM change_order WHERE id = ?";
        try (Connection conn = Databases.purchase()) {
            try (var statement = conn.prepareStatement(sql)) {
                statement.setInt(1, changeId);
                try (var rows = statement.executeQuery()) {
                    if (!rows.next()) {
                        throw new IllegalStateException("更换单不存在");
                    }
                    return new ChangeRow(
                            rows.getInt(1),
                            rows.getInt(2),
                            rows.getInt(3),
                            rows.getLong(4),
                            rows.getString(5));
                }
            }
        } catch (RuntimeException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public static void audit(int changeId, String actor, String result, String detail) {
        try (Connection conn = Databases.purchase()) {
            conn.setAutoCommit(false);
            insertAudit(conn, changeId, actor, result, detail);
            conn.commit();
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public static void setStatus(int changeId, String status, String actor, String detail) {
        try (Connection conn = Databases.purchase()) {
            conn.setAutoCommit(false);
            Sql.exec(conn, "UPDATE change_order SET status = ? WHERE id = ?", status, changeId);
            insertAudit(conn, changeId, actor, "接受", detail);
            conn.commit();
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public static void insertAudit(
            Connection conn, int changeId, String actor, String result, String detail) throws SQLException {
        Sql.exec(
                conn,
                "INSERT INTO audit_log (change_id, actor, result, detail) VALUES (?, ?, ?, ?)",
                changeId,
                actor,
                result,
                detail);
    }

    public static void setSupplier(Connection conn, int changeId, int poId, int supplierId) throws SQLException {
        String status = Sql.queryString(
                conn, "SELECT status FROM change_order WHERE id = ? FOR UPDATE", changeId);
        if (!"待确认".equals(status) && !"待主管确认".equals(status)) {
            throw new Reject("状态不允许");
        }
        Sql.exec(
                conn,
                "UPDATE purchase_order SET supplier_id = ?, write_count = write_count + 1 WHERE id = ?",
                supplierId,
                poId);
        Sql.exec(conn, "UPDATE change_order SET status = '待通知' WHERE id = ?", changeId);
    }

    public static int[] supplierAndWrites(int poId) {
        try (Connection conn = Databases.purchase()) {
            try (var statement = conn.prepareStatement(
                    "SELECT supplier_id, write_count FROM purchase_order WHERE id = ?")) {
                statement.setInt(1, poId);
                try (var rows = statement.executeQuery()) {
                    rows.next();
                    return new int[] {rows.getInt(1), rows.getInt(2)};
                }
            }
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }
}
