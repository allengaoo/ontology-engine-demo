"""供应商门户。不在两个业务库的提交里。"""

import sqlite3
from pathlib import Path


class Portal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS notice (change_id integer PRIMARY KEY, delivered integer NOT NULL)"
        )
        self.conn.execute("DELETE FROM notice")
        self.conn.commit()
        self.fail_next = False
        self.calls = {}

    def notify(self, change_id):
        self.calls[change_id] = self.calls.get(change_id, 0) + 1
        if self.fail_next:
            self.fail_next = False
            return False
        self.conn.execute(
            "INSERT INTO notice (change_id, delivered) VALUES (?, 1) "
            "ON CONFLICT(change_id) DO UPDATE SET delivered = 1",
            (change_id,),
        )
        self.conn.commit()
        return True

    def mark_delivered_without_call(self, change_id):
        self.conn.execute(
            "INSERT INTO notice (change_id, delivered) VALUES (?, 1) "
            "ON CONFLICT(change_id) DO UPDATE SET delivered = 1",
            (change_id,),
        )
        self.conn.commit()

    def delivered(self, change_id):
        row = self.conn.execute(
            "SELECT delivered FROM notice WHERE change_id = ?",
            (change_id,),
        ).fetchone()
        return row is not None and row[0] == 1

    def call_count(self, change_id):
        return self.calls.get(change_id, 0)
