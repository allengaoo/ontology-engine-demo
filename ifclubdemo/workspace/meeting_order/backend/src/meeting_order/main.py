"""FastAPI entry."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from meeting_order.api import bookings, rooms
from meeting_order.config import API_V1_PREFIX
from meeting_order.repositories.factory import init_db, seed_rooms_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_rooms_if_empty()
    yield


app = FastAPI(title="Meeting Order", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# 前缀只挂载一次；router 自身只有 /rooms、/bookings
app.include_router(rooms.router, prefix=API_V1_PREFIX)
app.include_router(bookings.router, prefix=API_V1_PREFIX)


@app.get("/health")
def health():
    return {"ok": True}