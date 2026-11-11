"""本机演示的地址。端口只绑在 127.0.0.1，口令只用于这套容器。"""

PURCHASE_DSN = "host=127.0.0.1 port=5434 dbname=purchase user=ont password=ont"
CONTRACT_DSN = "host=127.0.0.1 port=5433 dbname=contract user=ont password=ont"
ES_URL = "http://127.0.0.1:9200"
KAFKA_BOOTSTRAP = "127.0.0.1:9092"
DORIS_HOST = "127.0.0.1"
DORIS_PORT = 9030
DORIS_BACKEND = "172.30.62.11:9050"
SEATA_HOST = "127.0.0.1"
SEATA_PORT = 8091
TOPIC = "supplier-edits"
INDEX = "purchase-order"
ANNUAL_THRESHOLD = 1_000_000
RATE_CUTOFF = 0.90

SUPPLIER_JIA = 1
SUPPLIER_YI = 2
SUPPLIER_BING = 3
PO_MAIN = 17
PO_RECONCILE = 18
CHANGE_MAIN = 170
CHANGE_RECONCILE = 180
FACTORY_ID = 7
