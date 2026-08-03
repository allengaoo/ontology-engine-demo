"""API 集成测试：rooms / bookings / 409。保留此 fixture，只补断言。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个测试独立 tmp DB，禁止 session 级共享、禁止用生产库。"""
    import meeting_order.config as config
    from meeting_order.main import app
    from meeting_order.repositories.factory import init_db
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    init_db()
    with TestClient(app) as c:
        yield c


def test_rooms_endpoint(client):
    res = client.get("/api/v1/rooms")
    assert res.status_code == 200
    rooms = res.json()
    assert isinstance(rooms, list) and len(rooms) >= 2


def test_create_booking_success(client):
    # 获取房间列表以获取有效 room_id
    res = client.get("/api/v1/rooms")
    assert res.status_code == 200
    rooms = res.json()
    assert len(rooms) > 0
    room_id = rooms[0]["id"]

    # 创建合法预订请求
    booking_data = {
        "room_id": room_id,
        "title": "团队会议",
        "booker": "张三",
        "start_at": "2025-04-05T10:00:00",
        "end_at": "2025-04-05T11:00:00"
    }

    res = client.post("/api/v1/bookings", json=booking_data)
    assert res.status_code == 200
    booking = res.json()
    assert booking["room_id"] == room_id
    assert booking["title"] == "团队会议"
    assert booking["booker"] == "张三"


def test_create_booking_conflict(client):
    # 获取房间列表以获取有效 room_id
    res = client.get("/api/v1/rooms")
    assert res.status_code == 200
    rooms = res.json()
    assert len(rooms) > 0
    room_id = rooms[0]["id"]

    # 第一次创建预订
    booking_data = {
        "room_id": room_id,
        "title": "团队会议",
        "booker": "张三",
        "start_at": "2025-04-05T10:00:00",
        "end_at": "2025-04-05T11:00:00"
    }

    res = client.post("/api/v1/bookings", json=booking_data)
    assert res.status_code == 200

    # 尝试创建冲突的预订
    conflicting_booking_data = {
        "room_id": room_id,
        "title": "另一个会议",
        "booker": "李四",
        "start_at": "2025-04-05T10:30:00",
        "end_at": "2025-04-05T11:30:00"
    }

    res = client.post("/api/v1/bookings", json=conflicting_booking_data)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "BOOKING_CONFLICT"
    assert "冲突" in res.json()["detail"]["message"]