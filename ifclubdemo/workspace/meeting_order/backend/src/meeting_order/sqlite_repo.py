from typing import List, Optional
from .models.room import Room
from .models.booking import Booking
from .repositories.base import MeetingRepository
from .config import DB_PATH
import sqlite3
import json


class SqliteRepository(MeetingRepository):
    def __init__(self) -> None:
        self.db_path = DB_PATH
        self.init_db()

    def init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                is_active BOOLEAN NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY,
                room_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                booker TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                FOREIGN KEY (room_id) REFERENCES rooms (id)
            )
        """)
        conn.commit()
        conn.close()

    def seed_rooms_if_empty(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM rooms")
        if cursor.fetchone()[0] == 0:
            with open("data/seed_rooms.json") as f:
                rooms_data = json.load(f)
            for room_data in rooms_data:
                cursor.execute(
                    "INSERT INTO rooms (name, capacity, is_active) VALUES (?, ?, ?)",
                    (room_data["name"], room_data["capacity"], room_data["is_active"])
                )
        conn.commit()
        conn.close()

    def list_rooms(self) -> List[Room]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, capacity, is_active FROM rooms")
        rows = cursor.fetchall()
        rooms = [Room(id=row[0], name=row[1], capacity=row[2], is_active=row[3]) for row in rows]
        conn.close()
        return rooms

    def get_room(self, room_id: int) -> Optional[Room]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, capacity, is_active FROM rooms WHERE id=?", (room_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Room(id=row[0], name=row[1], capacity=row[2], is_active=row[3])
        return None

    def list_bookings(self, room_id: int) -> List[Booking]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, room_id, title, booker, start_at, end_at FROM bookings WHERE room_id=?", (room_id,))
        rows = cursor.fetchall()
        bookings = [Booking(id=row[0], room_id=row[1], title=row[2], booker=row[3], start_at=row[4], end_at=row[5]) for row in rows]
        conn.close()
        return bookings

    def create_booking(self, booking: Booking) -> Booking:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO bookings (room_id, title, booker, start_at, end_at) VALUES (?, ?, ?, ?, ?)",
            (booking.room_id, booking.title, booking.booker, booking.start_at, booking.end_at)
        )
        conn.commit()
        booking.id = cursor.lastrowid
        conn.close()
        return booking