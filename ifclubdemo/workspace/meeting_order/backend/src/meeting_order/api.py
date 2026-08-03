from fastapi import APIRouter, HTTPException
from typing import List
from meeting_order.schemas.booking import CreateBookingRequest, BookingResponse
from meeting_order.services.booking_service import create_booking
from meeting_order.repositories.factory import get_repository
from meeting_order.domain.rules import check_booking_time_validity, validate_time_range, check_no_overlap, check_room_active
from meeting_order.models.room import Room
from meeting_order.models.booking import Booking

router = APIRouter()

@router.post("/bookings", response_model=BookingResponse)
async def create_booking_endpoint(request: CreateBookingRequest):
    try:
        # Validate time range first
        validate_time_range(request.start_at, request.end_at)
        
        # Get repository instance
        repo = get_repository()
        
        # Fetch room details
        room = repo.get_room(request.room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Check if room is active
        check_room_active(room)
        
        # Check booking time validity
        check_booking_time_validity(request.start_at, request.end_at)
        
        # Get all bookings for the room
        existing_bookings = repo.list_bookings(request.room_id)
        
        # Check for overlaps
        check_no_overlap(request.room_id, request.start_at, request.end_at, existing_bookings)
        
        # Create the booking
        booking = create_booking(
            room_id=request.room_id,
            title=request.title,
            booker=request.booker,
            start_at=request.start_at,
            end_at=request.end_at
        )
        
        # Save to repository
        saved_booking = repo.create_booking(booking)
        
        return BookingResponse.from_orm(saved_booking)
    
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BOOKING_CONFLICT",
                "message": str(e)
            }
        )