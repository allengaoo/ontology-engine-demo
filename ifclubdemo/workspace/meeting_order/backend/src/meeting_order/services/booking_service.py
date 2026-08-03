from fastapi import HTTPException
from typing import List
from meeting_order.domain.rules import (
    check_booking_time_validity,
    check_no_overlap,
    check_room_active,
)
from meeting_order.models.booking import Booking
from meeting_order.repositories.factory import get_repository
from meeting_order.schemas.booking import CreateBookingRequest


def create_booking(request: CreateBookingRequest) -> Booking:
    repo = get_repository()
    
    try:
        # 1. 校验时间合法性
        check_booking_time_validity(request.start_at, request.end_at)
        
        # 2. 获取房间信息并校验是否激活
        room = repo.get_room(request.room_id)
        check_room_active(room)
        
        # 3. 查询该房间的已有预订
        existing_bookings: List[Booking] = repo.list_bookings(request.room_id)
        
        # 4. 检查时间冲突
        check_no_overlap(request.room_id, request.start_at, request.end_at, existing_bookings)
        
        # 5. 创建新的预订记录
        new_booking = Booking(
            id=None,
            room_id=request.room_id,
            title=request.title,
            booker=request.booker,
            start_at=request.start_at,
            end_at=request.end_at
        )
        
        return repo.create_booking(new_booking)
    
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BOOKING_CONFLICT",
                "message": str(e),
            },
        )