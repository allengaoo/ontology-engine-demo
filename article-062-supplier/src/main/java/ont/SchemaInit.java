package ont;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;

public final class SchemaInit {
    private SchemaInit() {}

    public static void apply() throws Exception {
        String text = Files.readString(Path.of("schema.sql"));
        String[] parts = text.split("-- @db contract", 2);
        reset(Databases.purchase(), parts[0].replace("-- @db purchase", ""));
        reset(Databases.contract(), parts[1]);
    }

    private static void reset(Connection conn, String script) throws Exception {
        try (conn) {
            conn.setAutoCommit(true);
            rollbackPrepared(conn);
            try (Statement statement = conn.createStatement()) {
                statement.execute("DROP SCHEMA IF EXISTS public CASCADE");
                statement.execute("CREATE SCHEMA public");
            }
            for (String sql : script.split(";")) {
                String trimmed = stripComments(sql);
                if (!trimmed.isEmpty()) {
                    try (Statement statement = conn.createStatement()) {
                        statement.execute(trimmed);
                    }
                }
            }
        }
    }

    private static void rollbackPrepared(Connection conn) throws Exception {
        java.util.List<String> names = new java.util.ArrayList<>();
        try (Statement statement = conn.createStatement();
                ResultSet rows = statement.executeQuery("SELECT gid FROM pg_prepared_xacts")) {
            while (rows.next()) {
                names.add(rows.getString(1));
            }
        }
        for (String gid : names) {
            if (gid.matches("[A-Za-z0-9_:-]+")) {
                try (Statement rollback = conn.createStatement()) {
                    rollback.execute("ROLLBACK PREPARED '" + gid + "'");
                }
            }
        }
    }

    private static String stripComments(String sql) {
        StringBuilder kept = new StringBuilder();
        for (String line : sql.split("\n")) {
            if (!line.trim().startsWith("--")) {
                kept.append(line).append('\n');
            }
        }
        return kept.toString().trim();
    }
}
