package ont;

/** 本机演示地址。口令只用于这套容器。 */
public final class Config {
    public static final String PURCHASE_URL = "jdbc:postgresql://127.0.0.1:5434/purchase";
    public static final String CONTRACT_URL = "jdbc:postgresql://127.0.0.1:5433/contract";
    public static final String DB_USER = "ont";
    public static final String DB_PASSWORD = "ont";
    public static final String ES = "http://127.0.0.1:9200";
    public static final String KAFKA = "127.0.0.1:9092";
    public static final String DORIS_URL =
            "jdbc:mysql://127.0.0.1:9030/?useSSL=false&allowPublicKeyRetrieval=true";
    public static final String TOPIC = "supplier-edits";
    public static final String INDEX = "purchase-order";
    public static final int ANNUAL_THRESHOLD = 1_000_000;
    public static final double RATE_CUTOFF = 0.90;
    public static final int SUPPLIER_JIA = 1;
    public static final int SUPPLIER_YI = 2;
    public static final int SUPPLIER_BING = 3;
    public static final int PO_MAIN = 17;
    public static final int PO_RECONCILE = 18;
    public static final int CHANGE_MAIN = 170;
    public static final int CHANGE_RECONCILE = 180;
    public static final int FACTORY_ID = 7;
    public static final String BUYER = "采购员";
    public static final String SUPERVISOR = "主管";
    public static final String TX_GROUP = "default_tx_group";

    private Config() {}
}
