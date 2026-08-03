import json
import os
from typing import List

import meeting_order.config as config
from meeting_order.models.room import Room
from meeting_order.repositories.sqlite_repo import SqliteRepository


def init_db():
    repo = SqliteRepository()
    repo.init_db()


def seed_rooms_if_empty():
    repo = SqliteRepository()
    rooms = repo.list_rooms()
    if not rooms:
        with open(os.path.join(config.ROOT, "data", "seed_rooms.json"), "r") as f:
            room_data_list = json.load(f)
        for room_data in room_data_list:
            room = Room(
                id=None,
                name=room_data["name"],
                capacity=room_data["capacity"],
                is_active=room_data["is_active"],
            )
            repo.create_room(room)


def get_repository() -> SqliteRepository:
    return SqliteRepository()