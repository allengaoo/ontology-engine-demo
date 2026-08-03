from dataclasses import dataclass
from typing import Optional

@dataclass
class Booking:
    id: Optional[int]
    room_id: int
    title: str
    booker: str
    start_at: str
    end_at: str
