package ont;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;

public final class Portal {
    private final Connection conn;
    private final java.util.Map<Integer, Integer> calls = new java.util.HashMap<>();
    private boolean failNext;

    public Portal(Path path) throws Exception {
        Files.createDirectories(path.getParent());
        conn = DriverManager.getConnection("jdbc:sqlite:" + path);
        try (Statement statement = conn.createStatement()) {
            statement.execute(
                    "CREATE TABLE IF NOT EXISTS notice (change_id integer PRIMARY KEY, delivered integer NOT NULL)");
            statement.execute("DELETE FROM notice");
        }
    }

    public void failNext() {
        failNext = true;
    }

    public boolean notify(int changeId) {
        calls.merge(changeId, 1, Integer::sum);
        if (failNext) {
            failNext = false;
            Log.line("门户 更换单 " + changeId + "：调用超时，不写送达记录，累计调用 " + calls.get(changeId));
            return false;
        }
        markDelivered(changeId);
        Log.line("门户 更换单 " + changeId + "：送达已记下，累计调用 " + calls.get(changeId));
        return true;
    }

    public void markDeliveredWithoutCall(int changeId) {
        markDelivered(changeId);
        Log.line("门户 更换单 " + changeId + "：已有送达记录，这次不调用门户");
    }

    public boolean delivered(int changeId) {
        try (PreparedStatement statement =
                conn.prepareStatement("SELECT delivered FROM notice WHERE change_id = ?")) {
            statement.setInt(1, changeId);
            try (ResultSet rows = statement.executeQuery()) {
                return rows.next() && rows.getInt(1) == 1;
            }
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public int callCount(int changeId) {
        return calls.getOrDefault(changeId, 0);
    }

    private void markDelivered(int changeId) {
        String sql = "INSERT INTO notice (change_id, delivered) VALUES (?, 1) "
                + "ON CONFLICT(change_id) DO UPDATE SET delivered = 1";
        try (PreparedStatement statement = conn.prepareStatement(sql)) {
            statement.setInt(1, changeId);
            statement.execute();
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }
}
