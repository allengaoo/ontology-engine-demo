from fastapi import APIRouter, Depends
from meeting_order.models.room import Room
from meeting_order.repositories.factory import get_repository

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("")
def list_rooms(repository=get_repository()) -> list[Room]:
    return repository.list_rooms()