from pydantic import BaseModel, Field
from typing import Optional

class CreateBookingRequest(BaseModel):
    room_id: int
    title: str = Field(min_length=1)
    booker: str = Field(min_length=1)
    start_at: str = Field(min_length=1)
    end_at: str = Field(min_length=1)

class BookingResponse(BaseModel):
    id: int
    room_id: int
    title: str
    booker: str
    start_at: str
    end_at: str