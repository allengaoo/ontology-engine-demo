package ont;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

public final class Sql {
    private Sql() {}

    public static void exec(Connection conn, String sql, Object... args) throws SQLException {
        try (PreparedStatement statement = conn.prepareStatement(sql)) {
            bind(statement, args);
            statement.execute();
        }
    }

    public static int queryInt(Connection conn, String sql, Object... args) throws SQLException {
        try (PreparedStatement statement = conn.prepareStatement(sql)) {
            bind(statement, args);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    throw new SQLException("查询没有结果");
                }
                return rows.getInt(1);
            }
        }
    }

    public static String queryString(Connection conn, String sql, Object... args) throws SQLException {
        try (PreparedStatement statement = conn.prepareStatement(sql)) {
            bind(statement, args);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    return null;
                }
                return rows.getString(1);
            }
        }
    }

    private static void bind(PreparedStatement statement, Object[] args) throws SQLException {
        for (int i = 0; i < args.length; i++) {
            statement.setObject(i + 1, args[i]);
        }
    }
}
