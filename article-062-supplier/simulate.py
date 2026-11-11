"""工厂 7 号更换供应商。六条断言都打在真实容器上。"""

import json
import sys
import time
from pathlib import Path

import psycopg
import pymysql
from elasticsearch import Elasticsearch
from kafka import KafkaProducer

import config
from actions import BUYER, SUPERVISOR, Engine
from bootstrap import prepare
from catchup import Catchup
from commit import commit_both
from portal import Portal
from query import on_time_rate, purchase_document

ROOT = Path(__file__).resolve().parent


def check(name, ok, detail):
    if not ok:
        raise SystemExit(f"失败 {name}: {detail}")
    print(f"通过 {name}: {detail}")


def purchase_row(po_id):
    with psycopg.connect(config.PURCHASE_DSN) as conn:
        row = conn.execute(
            "SELECT supplier_id, write_count FROM purchase_order WHERE id = %s",
            (po_id,),
        ).fetchone()
    return row


def contract_row(po_id):
    with psycopg.connect(config.CONTRACT_DSN) as conn:
        row = conn.execute(
            "SELECT supplier_id, write_count FROM contract WHERE po_id = %s",
            (po_id,),
        ).fetchone()
    return row


def change_status(change_id):
    with psycopg.connect(config.PURCHASE_DSN) as conn:
        row = conn.execute(
            "SELECT status FROM change_order WHERE id = %s",
            (change_id,),
        ).fetchone()
    return row[0]


def set_new_supplier(change_id, supplier_id):
    with psycopg.connect(config.PURCHASE_DSN) as conn:
        conn.execute(
            "UPDATE change_order SET new_supplier_id = %s WHERE id = %s",
            (supplier_id, change_id),
        )
        conn.commit()


def seed():
    with psycopg.connect(config.PURCHASE_DSN) as conn:
        conn.execute(
            "INSERT INTO supplier (id, name) VALUES (%s, %s), (%s, %s), (%s, %s)",
            (
                config.SUPPLIER_JIA,
                "甲",
                config.SUPPLIER_YI,
                "乙",
                config.SUPPLIER_BING,
                "丙",
            ),
        )
        conn.execute(
            """
            INSERT INTO purchase_order (id, factory_id, supplier_id, annual_amount)
            VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)
            """,
            (
                config.PO_MAIN,
                config.FACTORY_ID,
                config.SUPPLIER_JIA,
                2_000_000,
                config.PO_RECONCILE,
                config.FACTORY_ID,
                config.SUPPLIER_JIA,
                100_000,
            ),
        )
        conn.execute(
            """
            INSERT INTO change_order (id, po_id, new_supplier_id, annual_amount, status)
            VALUES (%s, %s, %s, %s, '待确认'), (%s, %s, %s, %s, '待确认')
            """,
            (
                config.CHANGE_MAIN,
                config.PO_MAIN,
                config.SUPPLIER_YI,
                2_000_000,
                config.CHANGE_RECONCILE,
                config.PO_RECONCILE,
                config.SUPPLIER_YI,
                100_000,
            ),
        )
        conn.execute("INSERT INTO probe (id, n) VALUES (1, 0)")
        conn.commit()
    with psycopg.connect(config.CONTRACT_DSN) as conn:
        conn.execute(
            "INSERT INTO contract (id, po_id, supplier_id) VALUES (%s, %s, %s), (%s, %s, %s)",
            (
                1,
                config.PO_MAIN,
                config.SUPPLIER_JIA,
                2,
                config.PO_RECONCILE,
                config.SUPPLIER_JIA,
            ),
        )
        conn.execute("INSERT INTO probe (id, n) VALUES (1, 0)")
        conn.commit()
    deliveries = [
        (config.SUPPLIER_JIA, 96, 4),
        (config.SUPPLIER_YI, 82, 18),
        (config.SUPPLIER_BING, 95, 5),
    ]
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
            cur.executemany(
                "INSERT INTO delivery (supplier_id, on_time, late) VALUES (%s, %s, %s)",
                deliveries,
            )
            cur.executemany(
                "INSERT INTO purchase_order (id, supplier_id, status) VALUES (%s, %s, %s)",
                [
                    (config.PO_MAIN, config.SUPPLIER_JIA, "待确认"),
                    (config.PO_RECONCILE, config.SUPPLIER_JIA, "待确认"),
                ],
            )
    finally:
        conn.close()
    es = Elasticsearch(config.ES_URL)
    for po_id in (config.PO_MAIN, config.PO_RECONCILE):
        es.index(
            index=config.INDEX,
            id=str(po_id),
            document={
                "factory_id": config.FACTORY_ID,
                "supplier_id": config.SUPPLIER_JIA,
                "status": "待确认",
            },
            refresh="wait_for",
        )


def publish(event):
    producer = publish.producer
    producer.send(config.TOPIC, value=event).get(timeout=10)


def assert_both_roll_back():
    def bump(conn):
        conn.execute("UPDATE probe SET n = 1 WHERE id = 1")

    try:
        commit_both(bump, bump, fail_contract=True)
    except Exception:
        pass
    else:
        raise SystemExit("失败 两库退回: 合同库故障时提交竟然成功了")
    with psycopg.connect(config.PURCHASE_DSN) as conn:
        left = conn.execute("SELECT n FROM probe WHERE id = 1").fetchone()[0]
    with psycopg.connect(config.CONTRACT_DSN) as conn:
        right = conn.execute("SELECT n FROM probe WHERE id = 1").fetchone()[0]
    check("两库退回", left == 0 and right == 0, f"采购库 {left}，合同库 {right}")


def wait_document(po_id, supplier_id, status, seconds):
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        last = purchase_document(po_id)
        if (
            last
            and last.get("supplier_id") == supplier_id
            and last.get("status") == status
        ):
            return last
        time.sleep(0.5)
    raise SystemExit(f"副本没有追上采购单 {po_id}: {last}")


def main():
    sys.path.insert(0, str(ROOT))
    prepare()
    seed()
    portal = Portal(ROOT / "var" / "portal.sqlite")
    producer = KafkaProducer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP,
        value_serializer=lambda item: json.dumps(item).encode("utf-8"),
    )
    publish.producer = producer
    catchup = Catchup()
    catchup.start()
    if not catchup.ready.wait(30):
        raise SystemExit("追平线程没有开始消费")
    engine = Engine(portal, publish, on_time_rate)

    assert_both_roll_back()

    set_new_supplier(config.CHANGE_MAIN, config.SUPPLIER_BING)
    result = engine.confirm(config.CHANGE_MAIN, BUYER)
    supplier, writes = purchase_row(config.PO_MAIN)
    check(
        "1 准时率不低于 90% 被拒绝",
        result == "拒绝" and supplier == config.SUPPLIER_JIA and writes == 0,
        f"结果 {result}，供应商 {supplier}，写入 {writes}",
    )
    set_new_supplier(config.CHANGE_MAIN, config.SUPPLIER_YI)

    result = engine.confirm(config.CHANGE_MAIN, BUYER)
    supplier, writes = purchase_row(config.PO_MAIN)
    contract_supplier, contract_writes = contract_row(config.PO_MAIN)
    check(
        "2 超额时采购员只提交主管",
        result == "需要主管"
        and change_status(config.CHANGE_MAIN) == "待主管确认"
        and supplier == config.SUPPLIER_JIA
        and contract_supplier == config.SUPPLIER_JIA
        and writes == 0
        and contract_writes == 0,
        f"结果 {result}，状态 {change_status(config.CHANGE_MAIN)}",
    )

    catchup.pause()
    result = engine.confirm(config.CHANGE_MAIN, SUPERVISOR)
    supplier, writes = purchase_row(config.PO_MAIN)
    contract_supplier, contract_writes = contract_row(config.PO_MAIN)
    check(
        "3 主管确认，两个库一起写成乙",
        result == "接受"
        and change_status(config.CHANGE_MAIN) == "待通知"
        and supplier == config.SUPPLIER_YI
        and contract_supplier == config.SUPPLIER_YI
        and writes == 1
        and contract_writes == 1,
        f"采购 {supplier}/{writes}，合同 {contract_supplier}/{contract_writes}",
    )
    time.sleep(1.5)
    stale = purchase_document(config.PO_MAIN)
    check(
        "3 附 副本仍是旧供应商",
        stale["supplier_id"] == config.SUPPLIER_JIA,
        f"文档供应商 {stale['supplier_id']}",
    )

    again = engine.confirm(config.CHANGE_MAIN, BUYER)
    supplier, writes = purchase_row(config.PO_MAIN)
    check(
        "4 再次确认被拒绝",
        again == "拒绝" and writes == 1 and supplier == config.SUPPLIER_YI,
        f"结果 {again}，写入仍是 {writes}",
    )

    portal.fail_next = True
    failed = engine.resend(config.CHANGE_MAIN, BUYER)
    supplier, writes = purchase_row(config.PO_MAIN)
    check(
        "5 通知失败停在待通知",
        failed == "待重发"
        and change_status(config.CHANGE_MAIN) == "待通知"
        and writes == 1
        and supplier == config.SUPPLIER_YI,
        f"结果 {failed}，状态 {change_status(config.CHANGE_MAIN)}，写入 {writes}",
    )
    resent = engine.resend(config.CHANGE_MAIN, BUYER)
    supplier, writes = purchase_row(config.PO_MAIN)
    _, contract_writes = contract_row(config.PO_MAIN)
    check(
        "5 重发成功才变成已更换",
        resent == "接受"
        and change_status(config.CHANGE_MAIN) == "已更换"
        and writes == 1
        and contract_writes == 1
        and portal.call_count(config.CHANGE_MAIN) == 2,
        f"结果 {resent}，采购写入 {writes}，合同写入 {contract_writes}",
    )

    catchup.resume()
    followed = wait_document(config.PO_MAIN, config.SUPPLIER_YI, "已更换", 30)
    check(
        "5 附 副本追上乙",
        followed["supplier_id"] == config.SUPPLIER_YI and followed["status"] == "已更换",
        f"文档 {followed}",
    )
    replayed_event = {
        "event_id": "replay-fixed",
        "po_id": config.PO_MAIN,
        "supplier_id": config.SUPPLIER_YI,
        "status": "已更换",
    }
    first = catchup.apply(replayed_event)
    second = catchup.apply(replayed_event)
    again_doc = purchase_document(config.PO_MAIN)
    check(
        "追平同一条编辑两次",
        first is True and second is False and again_doc == followed,
        f"第一次 {first}，第二次 {second}",
    )

    under = engine.confirm(config.CHANGE_RECONCILE, BUYER)
    supplier, writes = purchase_row(config.PO_RECONCILE)
    calls_before = portal.call_count(config.CHANGE_RECONCILE)
    portal.mark_delivered_without_call(config.CHANGE_RECONCILE)
    patched = engine.reconcile(config.CHANGE_RECONCILE, BUYER)
    supplier_after, writes_after = purchase_row(config.PO_RECONCILE)
    _, contract_writes = contract_row(config.PO_RECONCILE)
    check(
        "6 门户已送达则只补记",
        under == "接受"
        and patched == "接受"
        and change_status(config.CHANGE_RECONCILE) == "已更换"
        and writes_after == 1
        and contract_writes == 1
        and portal.call_count(config.CHANGE_RECONCILE) == calls_before
        and supplier_after == config.SUPPLIER_YI,
        f"确认 {under}，补记 {patched}，通知次数 {portal.call_count(config.CHANGE_RECONCILE)}，写入 {writes_after}",
    )
    print("全部断言通过")


if __name__ == "__main__":
    main()
