"""FE↔API 集成流：GET rooms → POST bookings → GET bookings 刷新。"""
from __future__ import annotations
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import meeting_order.config as config
    from meeting_order.main import app
    from meeting_order.repositories.factory import init_db
    db = tmp_path / "fe_flow.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    init_db()
    with TestClient(app) as c:
        yield c

def test_fe_backend_rooms_then_book_then_refresh(client: TestClient):
    rooms_res = client.get("/api/v1/rooms")
    assert rooms_res.status_code == 200
    rooms = rooms_res.json()
    assert isinstance(rooms, list) and len(rooms) >= 2
    for key in ("id", "name", "capacity", "is_active"):
        assert key in rooms[0]
    active = [r for r in rooms if r.get("is_active")]
    assert active
    assert client.get("/api/v1/bookings").status_code == 200
    room_id = active[0]["id"]
    create = client.post(
        "/api/v1/bookings",
        json={
            "room_id": room_id,
            "title": "前端联调会",
            "booker": "集成测试",
            "start_at": "2026-10-01T09:00:00",
            "end_at": "2026-10-01T10:00:00",
        },
    )
    assert create.status_code in (200, 201), create.text
    bookings = client.get("/api/v1/bookings").json()
    assert any(b.get("title") == "前端联调会" for b in bookings)
    conflict = client.post(
        "/api/v1/bookings",
        json={
            "room_id": room_id,
            "title": "撞车会",
            "booker": "乙",
            "start_at": "2026-10-01T09:30:00",
            "end_at": "2026-10-01T10:30:00",
        },
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "BOOKING_CONFLICT"
    assert detail.get("message")

def test_fe_source_mentions_refresh_after_post():
    page = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "BookingPage.tsx"
    text = page.read_text(encoding="utf-8")
    assert "setBookings" in text
    assert "refreshBookings" in text or text.count("/bookings") >= 2