"""唯一的写入口。确认更换不接收调用方传入的供应商编号。"""

import uuid

import psycopg

import config
from commit import commit_both

BUYER = "采购员"
SUPERVISOR = "主管"


class Reject(RuntimeError):
    pass


class Engine:
    def __init__(self, portal, publish, rate_of):
        self.portal = portal
        self.publish = publish
        self.rate_of = rate_of

    def confirm(self, change_id, actor):
        row = self._load(change_id)
        rate = self.rate_of(row["new_supplier_id"])
        if rate is None or rate >= config.RATE_CUTOFF:
            self._audit(change_id, actor, "拒绝", "不在这次结果里")
            return "拒绝"
        if actor not in (BUYER, SUPERVISOR):
            self._audit(change_id, actor, "拒绝", "不能做这个动作")
            return "拒绝"
        if (
            actor == BUYER
            and row["status"] == "待确认"
            and row["annual_amount"] > config.ANNUAL_THRESHOLD
        ):
            self._set_status(change_id, "待主管确认", actor, "提交主管")
            return "需要主管"
        if actor == BUYER and row["status"] != "待确认":
            self._audit(change_id, actor, "拒绝", "状态不允许")
            return "拒绝"
        if actor == SUPERVISOR and row["status"] != "待主管确认":
            self._audit(change_id, actor, "拒绝", "状态不允许")
            return "拒绝"

        new_supplier = row["new_supplier_id"]
        po_id = row["po_id"]

        def purchase_work(conn):
            current = conn.execute(
                "SELECT status FROM change_order WHERE id = %s FOR UPDATE",
                (change_id,),
            ).fetchone()
            if current[0] not in ("待确认", "待主管确认"):
                raise Reject("状态不允许")
            conn.execute(
                """
                UPDATE purchase_order
                SET supplier_id = %s, write_count = write_count + 1
                WHERE id = %s
                """,
                (new_supplier, po_id),
            )
            conn.execute(
                "UPDATE change_order SET status = '待通知' WHERE id = %s",
                (change_id,),
            )
            self._audit_on(conn, change_id, actor, "接受", "两库已换，通知未发")

        def contract_work(conn):
            conn.execute(
                """
                UPDATE contract
                SET supplier_id = %s, write_count = write_count + 1
                WHERE po_id = %s
                """,
                (new_supplier, po_id),
            )

        try:
            commit_both(purchase_work, contract_work)
        except Reject:
            self._audit(change_id, actor, "拒绝", "状态不允许")
            return "拒绝"
        self._publish(po_id, new_supplier, "待通知")
        return "接受"

    def resend(self, change_id, actor):
        row = self._load(change_id)
        if row["status"] != "待通知":
            self._audit(change_id, actor, "拒绝", "没有待发出的通知")
            return "拒绝"
        if not self.portal.notify(change_id):
            self._audit(change_id, actor, "待重发", "通知失败，仍待通知")
            return "待重发"
        self._set_status(change_id, "已更换", actor, "已通知")
        self._publish(row["po_id"], row["new_supplier_id"], "已更换")
        return "接受"

    def reconcile(self, change_id, actor):
        row = self._load(change_id)
        if row["status"] != "待通知":
            self._audit(change_id, actor, "拒绝", "没有待补记的通知")
            return "拒绝"
        if not self.portal.delivered(change_id):
            self._audit(change_id, actor, "拒绝", "门户没有送达记录")
            return "拒绝"
        self._set_status(change_id, "已更换", actor, "按门户补记")
        self._publish(row["po_id"], row["new_supplier_id"], "已更换")
        return "接受"

    def _publish(self, po_id, supplier_id, status):
        self.publish(
            {
                "event_id": uuid.uuid4().hex,
                "po_id": po_id,
                "supplier_id": supplier_id,
                "status": status,
            }
        )

    def _load(self, change_id):
        with psycopg.connect(config.PURCHASE_DSN) as conn:
            row = conn.execute(
                """
                SELECT id, po_id, new_supplier_id, annual_amount, status
                FROM change_order WHERE id = %s
                """,
                (change_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("更换单不存在")
        return {
            "id": row[0],
            "po_id": row[1],
            "new_supplier_id": row[2],
            "annual_amount": row[3],
            "status": row[4],
        }

    def _audit(self, change_id, actor, result, detail):
        with psycopg.connect(config.PURCHASE_DSN) as conn:
            self._audit_on(conn, change_id, actor, result, detail)
            conn.commit()

    def _audit_on(self, conn, change_id, actor, result, detail):
        conn.execute(
            """
            INSERT INTO audit_log (change_id, actor, result, detail)
            VALUES (%s, %s, %s, %s)
            """,
            (change_id, actor, result, detail),
        )

    def _set_status(self, change_id, status, actor, detail):
        with psycopg.connect(config.PURCHASE_DSN) as conn:
            conn.execute(
                "UPDATE change_order SET status = %s WHERE id = %s",
                (status, change_id),
            )
            self._audit_on(conn, change_id, actor, "接受", detail)
            conn.commit()
