from fastapi import APIRouter, Depends, HTTPException
from typing import List
from meeting_order.models.booking import Booking
from meeting_order.schemas.booking import CreateBookingRequest, BookingResponse
from meeting_order.repositories.factory import get_repository
from meeting_order.domain.rules import (
    check_booking_time_validity,
    check_no_overlap,
    check_room_active,
    validate_time_range,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])

@router.get("", response_model=List[BookingResponse])
def list_bookings(room_id: int = None, repository=Depends(get_repository)):
    """列出预订：不传 room_id 列全部，传则按房间过滤。"""
    bookings = repository.list_bookings(room_id)
    return [
        BookingResponse(
            id=b.id,
            room_id=b.room_id,
            title=b.title,
            booker=b.booker,
            start_at=b.start_at,
            end_at=b.end_at,
        )
        for b in bookings
    ]

@router.post("", response_model=BookingResponse)
def create_booking(request: CreateBookingRequest, repository=Depends(get_repository)):
    """创建一个新的会议预订，包含时间冲突检查。"""
    try:
        # 检查时间有效性
        check_booking_time_validity(request.start_at, request.end_at)
        
        # 获取会议室信息
        room = repository.get_room(request.room_id)
        check_room_active(room)
        
        # 获取该会议室的所有预订记录
        existing_bookings = repository.list_bookings(request.room_id)
        
        # 检查时间冲突
        check_no_overlap(request.room_id, request.start_at, request.end_at, existing_bookings)
        
        # 创建新的预订记录
        new_booking = Booking(
            id=None,
            room_id=request.room_id,
            title=request.title,
            booker=request.booker,
            start_at=request.start_at,
            end_at=request.end_at,
        )
        
        saved_booking = repository.create_booking(new_booking)
        return BookingResponse(
            id=saved_booking.id,
            room_id=saved_booking.room_id,
            title=saved_booking.title,
            booker=saved_booking.booker,
            start_at=saved_booking.start_at,
            end_at=saved_booking.end_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BOOKING_CONFLICT",
                "message": str(e),
            },
        )