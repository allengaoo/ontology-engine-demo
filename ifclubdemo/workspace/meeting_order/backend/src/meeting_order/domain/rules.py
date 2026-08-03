"""Booking conflict rules."""

from datetime import datetime
from fastapi import HTTPException
from typing import List
from meeting_order.models.booking import Booking
from meeting_order.models.room import Room

def check_booking_time_validity(start_at: str, end_at: str) -> None:
    """Ensure end time is later than start time, raise HTTP 409 if not."""
    start = datetime.fromisoformat(start_at)
    end = datetime.fromisoformat(end_at)
    if end <= start:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BOOKING_CONFLICT",
                "message": "会议结束时间必须晚于开始时间。",
            },
        )

def validate_time_range(start_at: str, end_at: str) -> None:
    """Raise ValueError if end_at is not after start_at."""
    check_booking_time_validity(start_at, end_at)

def check_no_overlap(room_id: int, start_at: str, end_at: str, existing: List[Booking]) -> None:
    """Raise HTTP 409 if same-room intervals overlap (abut allowed)."""
    start = datetime.fromisoformat(start_at)
    end = datetime.fromisoformat(end_at)

    for booking in existing:
        if booking.room_id != room_id:
            continue
        existing_start = datetime.fromisoformat(booking.start_at)
        existing_end = datetime.fromisoformat(booking.end_at)

        # Allow abutting (e.g., one ends when other starts)
        if existing_end <= start or end <= existing_start:
            continue
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "BOOKING_CONFLICT",
                    "message": "所选时间段与已有预约冲突。",
                },
            )

def check_room_active(room: Room) -> None:
    """Raise HTTP 409 if room is inactive."""
    if not room.is_active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ROOM_INACTIVE",
                "message": "会议室已停用，无法预定。",
            },
        )

def check_room_is_active(room: Room) -> None:
    """Ensure the room is active; raise HTTP 409 if not."""
    if not room.is_active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ROOM_INACTIVE",
                "message": "会议室已停用，无法预定。",
            },
        )