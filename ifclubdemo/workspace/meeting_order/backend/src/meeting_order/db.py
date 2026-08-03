"""兼容入口：请使用 meeting_order.repositories.factory。"""
from meeting_order.repositories.factory import init_db, get_repository

__all__ = ["init_db", "get_repository"]
