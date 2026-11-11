"""提交成功之后追平副本。同一条编辑处理两次，结果相同。"""

import json
import threading

import psycopg
import pymysql
from elasticsearch import Elasticsearch
from kafka import KafkaConsumer

import config


class Catchup(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="catchup")
        self.gate = threading.Event()
        self.gate.set()
        self.ready = threading.Event()

    def pause(self):
        self.gate.clear()

    def resume(self):
        self.gate.set()

    def run(self):
        consumer = KafkaConsumer(
            config.TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP,
            group_id="catchup",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )
        self.ready.set()
        for message in consumer:
            self.gate.wait()
            self.apply(message.value)

    def apply(self, event):
        if self._seen(event["event_id"]):
            return False
        Elasticsearch(config.ES_URL).index(
            index=config.INDEX,
            id=str(event["po_id"]),
            document={
                "factory_id": config.FACTORY_ID,
                "supplier_id": event["supplier_id"],
                "status": event["status"],
            },
            refresh="wait_for",
        )
        self._write_doris(event)
        self._mark(event["event_id"])
        return True

    def _seen(self, event_id):
        with psycopg.connect(config.PURCHASE_DSN) as conn:
            row = conn.execute(
                "SELECT 1 FROM consumed_event WHERE event_id = %s",
                (event_id,),
            ).fetchone()
        return row is not None

    def _mark(self, event_id):
        with psycopg.connect(config.PURCHASE_DSN) as conn:
            conn.execute(
                "INSERT INTO consumed_event (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (event_id,),
            )
            conn.commit()

    def _write_doris(self, event):
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
                    "INSERT INTO purchase_order (id, supplier_id, status) VALUES (%s, %s, %s)",
                    (event["po_id"], event["supplier_id"], event["status"]),
                )
        finally:
            conn.close()
