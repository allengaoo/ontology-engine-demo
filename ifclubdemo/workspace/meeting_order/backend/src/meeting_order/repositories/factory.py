import json
import os
from typing import List
from meeting_order.config import DB_PATH, API_V1_PREFIX
from meeting_order.repositories.sqlite_repo import SqliteRepository
from meeting_order.models.room import Room

def init_db() -> None:
    repo = SqliteRepository()
    repo.init_db()

def seed_rooms_if_empty() -> None:
    repo = SqliteRepository()
    rooms = repo.list_rooms()
    if not rooms:
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "data", "seed_rooms.json")) as f:
            seed_data = json.load(f)
        for item in seed_data:
            room = Room(id=None, name=item["name"], capacity=item["capacity"], is_active=item["is_active"])
            repo.create_room(room)

def get_repository() -> SqliteRepository:
    return SqliteRepository()