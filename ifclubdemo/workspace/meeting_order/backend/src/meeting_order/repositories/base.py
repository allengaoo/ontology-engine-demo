from typing import Protocol, List
from meeting_order.models.room import Room
from meeting_order.models.booking import Booking

class MeetingRepository(Protocol):
    def list_rooms(self) -> List[Room]:
        ...

    def get_room(self, room_id: int) -> Room:
        ...

    def list_bookings(self, room_id: int = None) -> List[Booking]:
        ...

    def create_booking(self, booking: Booking) -> Booking:
        ...