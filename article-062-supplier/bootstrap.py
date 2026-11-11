"""等容器就绪，并建好两个业务库、索引和 Doris 表。"""

import socket
import time
from pathlib import Path

import psycopg
import pymysql
from elasticsearch import Elasticsearch

import config
from commit import rollback_prepared

ROOT = Path(__file__).resolve().parent


def wait_port(host, port, seconds, label):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"就绪 {label} {host}:{port}")
                return
        except OSError:
            time.sleep(1)
    raise SystemExit(f"{label} {host}:{port} 在 {seconds} 秒内没有就绪")


def _reset_postgres(dsn):
    rollback_prepared(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def _apply_sql(dsn, script):
    statements = []
    for part in script.split(";"):
        lines = [
            line
            for line in part.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        text = "\n".join(lines).strip()
        if text:
            statements.append(text)
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


def _doris_cursor():
    return pymysql.connect(
        host=config.DORIS_HOST,
        port=config.DORIS_PORT,
        user="root",
        password="",
        autocommit=True,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=30,
    )


def _wait_doris(seconds):
    deadline = time.time() + seconds
    last_error = "还没有连上"
    while time.time() < deadline:
        try:
            conn = _doris_cursor()
        except pymysql.Error as exc:
            last_error = str(exc)
            time.sleep(2)
            continue
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW BACKENDS")
                rows = cur.fetchall()
                columns = [item[0] for item in cur.description]
                alive_at = columns.index("Alive") if rows else None
                if rows and any(str(row[alive_at]).lower() == "true" for row in rows):
                    print("就绪 Doris BE")
                    return
                joined = " ".join(str(row) for row in rows)
                if config.DORIS_BACKEND not in joined:
                    try:
                        cur.execute(
                            f'ALTER SYSTEM ADD BACKEND "{config.DORIS_BACKEND}"'
                        )
                    except pymysql.Error as exc:
                        last_error = str(exc)
                else:
                    last_error = f"BE 尚未 Alive: {rows}"
        finally:
            conn.close()
        time.sleep(2)
    raise SystemExit(f"Doris 在 {seconds} 秒内没有就绪: {last_error}")


def _init_doris():
    conn = _doris_cursor()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE DATABASE IF NOT EXISTS ont")
            cur.execute("DROP TABLE IF EXISTS ont.delivery")
            cur.execute("DROP TABLE IF EXISTS ont.purchase_order")
            cur.execute(
                """
                CREATE TABLE ont.delivery (
                    supplier_id INT,
                    on_time INT,
                    late INT
                )
                DUPLICATE KEY(supplier_id)
                DISTRIBUTED BY HASH(supplier_id) BUCKETS 1
                PROPERTIES ("replication_num" = "1")
                """
            )
            cur.execute(
                """
                CREATE TABLE ont.purchase_order (
                    id INT,
                    supplier_id INT,
                    status VARCHAR(32)
                )
                UNIQUE KEY(id)
                DISTRIBUTED BY HASH(id) BUCKETS 1
                PROPERTIES ("replication_num" = "1")
                """
            )
    finally:
        conn.close()


def _init_es():
    es = Elasticsearch(config.ES_URL)
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if es.ping():
                break
        except Exception:
            time.sleep(2)
    else:
        raise SystemExit("Elasticsearch 没有通过 ping")
    if es.indices.exists(index=config.INDEX):
        es.indices.delete(index=config.INDEX)
    es.indices.create(index=config.INDEX)
    print("就绪 Elasticsearch 索引")


def prepare():
    wait_port("127.0.0.1", 5434, 60, "采购库")
    wait_port("127.0.0.1", 5433, 60, "合同库")
    wait_port("127.0.0.1", 9200, 120, "Elasticsearch")
    wait_port("127.0.0.1", 9092, 90, "Kafka")
    wait_port("127.0.0.1", config.SEATA_PORT, 90, "Seata")
    wait_port(config.DORIS_HOST, config.DORIS_PORT, 180, "Doris 查询端口")
    _wait_doris(180)
    text = (ROOT / "schema.sql").read_text()
    purchase_sql, contract_sql = text.split("-- @db contract", 1)
    purchase_sql = purchase_sql.replace("-- @db purchase", "")
    _reset_postgres(config.PURCHASE_DSN)
    _reset_postgres(config.CONTRACT_DSN)
    _apply_sql(config.PURCHASE_DSN, purchase_sql)
    _apply_sql(config.CONTRACT_DSN, contract_sql)
    _init_es()
    _init_doris()
    print("表和索引已建好")
