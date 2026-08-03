from typing import Optional
from fastapi import HTTPException
from meeting_order.models.booking import Booking
from meeting_order.models.room import Room
from meeting_order.schemas.booking import CreateBookingRequest
from meeting_order.domain.rules import (
    check_booking_time_validity,
    validate_time_range,
    check_no_overlap,
    check_room_active,
    check_room_is_active,
)
from meeting_order.repositories.factory import get_repository


def create_booking(request: CreateBookingRequest) -> Booking:
    try:
        # Validate time range
        validate_time_range(request.start_at, request.end_at)
        
        # Check if end time is later than start time
        check_booking_time_validity(request.start_at, request.end_at)
        
        # Get repository
        repo = get_repository()
        
        # Fetch room
        room: Optional[Room] = repo.get_room(request.room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Check if room is active
        check_room_active(room)
        check_room_is_active(room)
        
        # List existing bookings for the room
        existing_bookings = repo.list_bookings(request.room_id)
        
        # Check for overlaps
        check_no_overlap(request.room_id, request.start_at, request.end_at, existing_bookings)
        
        # Create and return booking
        return repo.create_booking(
            room_id=request.room_id,
            title=request.title,
            booker=request.booker,
            start_at=request.start_at,
            end_at=request.end_at
        )
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BOOKING_CONFLICT",
                "message": str(e)
            }
        )