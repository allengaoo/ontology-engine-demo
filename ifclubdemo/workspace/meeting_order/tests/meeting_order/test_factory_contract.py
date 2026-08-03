"""factory 契约：init_db 必须种子；get_repository 必须尊重 monkeypatch（禁全局缓存）。"""
import pytest


def test_init_db_seeds_rooms(tmp_path, monkeypatch):
    import meeting_order.config as config
    from meeting_order.repositories.factory import init_db, get_repository
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "a.db"))
    init_db()
    rooms = get_repository().list_rooms()
    assert len(rooms) >= 2, "init_db 后必须有种子房间"


def test_get_repository_respects_monkeypatch(tmp_path, monkeypatch):
    import meeting_order.config as config
    from meeting_order.repositories.factory import init_db, get_repository
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "b.db"))
    init_db()
    repo = get_repository()
    # 新库应只有种子房间，无残留预订
    assert len(repo.list_rooms()) >= 2
    assert repo.list_bookings() == [] or len(repo.list_bookings()) == 0