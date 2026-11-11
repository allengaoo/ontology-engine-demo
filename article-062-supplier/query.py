"""查找。准时率只问 Doris，采购单文档只问 Elasticsearch。"""

import pymysql
from elasticsearch import Elasticsearch

import config


def on_time_rate(supplier_id):
    conn = pymysql.connect(
        host=config.DORIS_HOST,
        port=config.DORIS_PORT,
        user="root",
        password="",
        database="ont",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(on_time) * 1.0 / (SUM(on_time) + SUM(late))
                FROM delivery
                WHERE supplier_id = %s
                """,
                (supplier_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def purchase_document(po_id):
    es = Elasticsearch(config.ES_URL)
    if not es.exists(index=config.INDEX, id=str(po_id)):
        return None
    return es.get(index=config.INDEX, id=str(po_id))["_source"]
