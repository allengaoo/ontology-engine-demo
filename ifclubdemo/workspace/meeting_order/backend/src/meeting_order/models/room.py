from dataclasses import dataclass
from typing import Optional

@dataclass
class Room:
    id: Optional[int]
    name: str
    capacity: int
    is_active: bool = True
