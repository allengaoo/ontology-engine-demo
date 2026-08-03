import sqlite3
import json
from pathlib import Path
from typing import List
from meeting_order.models.room import Room
from meeting_order.models.booking import Booking
from meeting_order.repositories.base import MeetingRepository
from meeting_order import config

class SqliteRepository(MeetingRepository):
    def __init__(self):
        self.db_path = config.DB_PATH
        self.init_db()
        self.seed_rooms_if_empty()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    capacity INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    booker TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL
                )
            """)

    def seed_rooms_if_empty(self):
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
            if count == 0:
                seed_file = Path("data/seed_rooms.json")
                with seed_file.open() as f:
                    rooms_data = json.load(f)
                for room_data in rooms_data:
                    conn.execute(
                        "INSERT INTO rooms (name, capacity, is_active) VALUES (?, ?, ?)",
                        (room_data["name"], room_data["capacity"], room_data["is_active"])
                    )

    def list_rooms(self) -> List[Room]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT id, name, capacity, is_active FROM rooms").fetchall()
            return [Room(id=row[0], name=row[1], capacity=row[2], is_active=bool(row[3])) for row in rows]

    def get_room(self, room_id: int) -> Room:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id, name, capacity, is_active FROM rooms WHERE id=?", (room_id,)).fetchone()
            if not row:
                raise ValueError(f"Room with id {room_id} not found")
            return Room(id=row[0], name=row[1], capacity=row[2], is_active=bool(row[3]))

    def list_bookings(self, room_id: int = None) -> List[Booking]:
        with sqlite3.connect(self.db_path) as conn:
            if room_id is None:
                rows = conn.execute(
                    "SELECT id, room_id, title, booker, start_at, end_at FROM bookings"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, room_id, title, booker, start_at, end_at FROM bookings WHERE room_id=?",
                    (room_id,)
                ).fetchall()
            return [
                Booking(id=row[0], room_id=row[1], title=row[2], booker=row[3], start_at=row[4], end_at=row[5])
                for row in rows
            ]

    def create_booking(self, booking: Booking) -> Booking:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO bookings (room_id, title, booker, start_at, end_at) VALUES (?, ?, ?, ?, ?)",
                (booking.room_id, booking.title, booking.booker, booking.start_at, booking.end_at)
            )
            booking.id = cursor.lastrowid
            return booking