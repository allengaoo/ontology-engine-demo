"""两个业务库一起提交，或一起退回。

PostgreSQL 的 PREPARE TRANSACTION 把采购库和合同库变成同一个决定。
决定先记在 global_tx 里：记成 committing 之后，两边都提交；没记成则两边退回。
生产里这个协调器的位置是 Seata。Python 侧没有能驱动 Seata AT 的客户端，
所以提交走数据库自己的预提交，不假装已经向 TC 注册了分支。
"""

import re
import uuid

import psycopg

import config

_NAME = re.compile(r"^[a-z0-9]+$")


def _prepared_name(prefix, gid):
    name = prefix + gid
    if _NAME.fullmatch(name) is None or len(name) > 40:
        raise ValueError("非法的预提交名称")
    return name


def _journal(sql, params):
    with psycopg.connect(config.PURCHASE_DSN, autocommit=True) as conn:
        conn.execute(sql, params)


def rollback_prepared(dsn):
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute("SELECT gid FROM pg_prepared_xacts").fetchall()
        for (gid,) in rows:
            if re.fullmatch(r"[A-Za-z0-9_]+", gid) is None:
                continue
            conn.execute(f"ROLLBACK PREPARED '{gid}'")


def _finish(dsn, name, verb):
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            conn.execute(f"{verb} PREPARED '{name}'")
        except psycopg.Error as exc:
            if "does not exist" not in str(exc):
                raise


def _prepare(dsn, name, work):
    conn = psycopg.connect(dsn, autocommit=False)
    prepared = False
    try:
        work(conn)
        conn.execute(f"PREPARE TRANSACTION '{name}'")
        prepared = True
    except Exception:
        if not prepared:
            conn.rollback()
        raise
    finally:
        conn.close()
    return prepared


class CommitError(RuntimeError):
    pass


def commit_both(purchase_work, contract_work, fail_contract=False):
    """purchase_work、contract_work 各自收到一个尚未提交的连接。"""
    gid = uuid.uuid4().hex
    purchase_name = _prepared_name("p", gid)
    contract_name = _prepared_name("c", gid)
    prepared = {"purchase": False, "contract": False}
    phase = "preparing"
    _journal(
        "INSERT INTO global_tx (id, status) VALUES (%s, 'preparing')",
        (gid,),
    )

    def abort():
        if prepared["purchase"]:
            _finish(config.PURCHASE_DSN, purchase_name, "ROLLBACK")
            prepared["purchase"] = False
        if prepared["contract"]:
            _finish(config.CONTRACT_DSN, contract_name, "ROLLBACK")
            prepared["contract"] = False
        _journal("UPDATE global_tx SET status = 'aborted' WHERE id = %s", (gid,))

    def commit_remaining():
        if prepared["purchase"]:
            _finish(config.PURCHASE_DSN, purchase_name, "COMMIT")
            prepared["purchase"] = False
        if prepared["contract"]:
            _finish(config.CONTRACT_DSN, contract_name, "COMMIT")
            prepared["contract"] = False
        _journal(
            "UPDATE global_tx SET status = 'committed' WHERE id = %s",
            (gid,),
        )

    try:
        _prepare(config.PURCHASE_DSN, purchase_name, purchase_work)
        prepared["purchase"] = True
        if fail_contract:

            def fail(conn):
                conn.execute("SELECT 1/0")

            _prepare(config.CONTRACT_DSN, contract_name, fail)
        else:
            _prepare(config.CONTRACT_DSN, contract_name, contract_work)
        prepared["contract"] = True
        _journal(
            "UPDATE global_tx SET status = 'committing' WHERE id = %s",
            (gid,),
        )
        phase = "committing"
        commit_remaining()
    except Exception:
        if phase == "preparing":
            abort()
            raise
        commit_remaining()
    return gid
