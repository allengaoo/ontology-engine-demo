package ont;

import java.sql.Connection;
import java.sql.SQLException;

public final class ContractDb {
    private ContractDb() {}

    public static void setCounterparty(Connection conn, int poId, int supplierId) throws SQLException {
        Sql.exec(
                conn,
                "UPDATE contract SET supplier_id = ?, write_count = write_count + 1 WHERE po_id = ?",
                supplierId,
                poId);
    }

    public static int[] supplierAndWrites(int poId) {
        try (Connection conn = Databases.contract()) {
            try (var statement = conn.prepareStatement(
                    "SELECT supplier_id, write_count FROM contract WHERE po_id = ?")) {
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
