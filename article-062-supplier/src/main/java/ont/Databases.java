package ont;

import java.sql.Connection;
import java.sql.SQLException;
import javax.sql.DataSource;
import org.postgresql.ds.PGSimpleDataSource;
import org.postgresql.xa.PGXADataSource;
import io.seata.rm.datasource.xa.DataSourceProxyXANative;

public final class Databases {
    private static DataSource purchasePlain;
    private static DataSource contractPlain;
    private static DataSource purchaseXa;
    private static DataSource contractXa;

    private Databases() {}

    public static void openPlain() {
        purchasePlain = plain(Config.PURCHASE_URL);
        contractPlain = plain(Config.CONTRACT_URL);
    }

    public static void openXa() {
        purchaseXa = xa(Config.PURCHASE_URL);
        contractXa = xa(Config.CONTRACT_URL);
    }

    public static DataSource purchasePlain() {
        return purchasePlain;
    }

    public static DataSource contractPlain() {
        return contractPlain;
    }

    public static DataSource purchaseXa() {
        return purchaseXa;
    }

    public static DataSource contractXa() {
        return contractXa;
    }

    public static Connection purchase() throws SQLException {
        return purchasePlain.getConnection();
    }

    public static Connection contract() throws SQLException {
        return contractPlain.getConnection();
    }

    private static DataSource xa(String url) {
        PGXADataSource source = new PGXADataSource();
        source.setURL(url);
        source.setUser(Config.DB_USER);
        source.setPassword(Config.DB_PASSWORD);
        return new DataSourceProxyXANative(source, url);
    }

    private static DataSource plain(String url) {
        PGSimpleDataSource source = new PGSimpleDataSource();
        source.setURL(url);
        source.setUser(Config.DB_USER);
        source.setPassword(Config.DB_PASSWORD);
        return source;
    }
}
