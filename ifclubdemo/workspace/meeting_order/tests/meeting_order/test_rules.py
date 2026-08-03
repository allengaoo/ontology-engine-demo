import pytest
from datetime import datetime
from fastapi import HTTPException
from meeting_order.domain.rules import (
    check_booking_time_validity,
    check_no_overlap,
    check_room_active,
)
from meeting_order.models.booking import Booking
from meeting_order.models.room import Room


def test_check_booking_time_validity_valid():
    """测试有效的时间范围"""
    check_booking_time_validity("2023-10-01T09:00:00", "2023-10-01T10:00:00")


def test_check_booking_time_validity_invalid():
    """测试无效的时间范围：结束时间早于开始时间"""
    with pytest.raises(HTTPException) as exc_info:
        check_booking_time_validity("2023-10-01T10:00:00", "2023-10-01T09:00:00")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BOOKING_CONFLICT"


def test_check_booking_time_validity_equal():
    """测试无效的时间范围：开始时间和结束时间相等"""
    with pytest.raises(HTTPException) as exc_info:
        check_booking_time_validity("2023-10-01T09:00:00", "2023-10-01T09:00:00")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BOOKING_CONFLICT"


def test_check_no_overlap_non_conflicting():
    """测试非冲突的预约时间"""
    existing = [
        Booking(
            id=1,
            room_id=1,
            title="会议A",
            booker="张三",
            start_at="2023-10-01T09:00:00",
            end_at="2023-10-01T10:00:00",
        )
    ]
    check_no_overlap(1, "2023-10-01T11:00:00", "2023-10-01T12:00:00", existing)


def test_check_no_overlap_conflicting():
    """测试冲突的预约时间"""
    existing = [
        Booking(
            id=1,
            room_id=1,
            title="会议A",
            booker="张三",
            start_at="2023-10-01T09:00:00",
            end_at="2023-10-01T10:00:00",
        )
    ]
    with pytest.raises(HTTPException) as exc_info:
        check_no_overlap(1, "2023-10-01T09:30:00", "2023-10-01T10:30:00", existing)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "BOOKING_CONFLICT"


def test_check_no_overlap_abutting_allowed():
    """测试首尾相接的情况应被允许"""
    existing = [
        Booking(
            id=1,
            room_id=1,
            title="会议A",
            booker="张三",
            start_at="2023-10-01T09:00:00",
            end_at="2023-10-01T10:00:00",
        )
    ]
    # 新预约正好在已有预约之后开始
    check_no_overlap(1, "2023-10-01T10:00:00", "2023-10-01T11:00:00", existing)


def test_check_room_active_inactive():
    """测试停用房间拒绝预订"""
    room = Room(id=1, name="测试房间", capacity=10, is_active=False)
    with pytest.raises(HTTPException) as exc_info:
        check_room_active(room)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ROOM_INACTIVE"


def test_check_room_active_active():
    """测试启用房间允许预订"""
    room = Room(id=1, name="测试房间", capacity=10, is_active=True)
    check_room_active(room)


def test_check_no_overlap_different_rooms():
    """测试不同会议室之间互不影响"""
    existing = [
        Booking(
            id=1,
            room_id=1,
            title="会议A",
            booker="张三",
            start_at="2023-10-01T09:00:00",
            end_at="2023-10-01T10:00:00",
        )
    ]
    # 在另一个房间预订相同时间应不冲突
    check_no_overlap(2, "2023-10-01T09:30:00", "2023-10-01T10:30:00", existing)