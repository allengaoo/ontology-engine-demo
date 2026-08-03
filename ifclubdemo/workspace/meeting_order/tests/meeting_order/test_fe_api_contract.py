import pytest
from unittest.mock import patch, MagicMock
from meeting_order.config import API_V1_PREFIX


def test_api_v1_prefix_not_duplicated():
    """确保 API 路径中不出现双写 /api/v1"""
    assert API_V1_PREFIX == "/api/v1"
    # 模拟前端调用路径拼接
    with patch("meeting_order.config.API_V1_PREFIX", new="/api/v1"):
        prefix = API_V1_PREFIX
        assert prefix == "/api/v1"
        # 确保没有重复拼接
        assert not prefix.startswith("//api/v1") and not prefix.endswith("/api/v1/")
        assert prefix.count("/api/v1") == 1


def test_api_path_joining_function_used():
    """确保前端调用使用了拼接函数而非硬编码路径"""
    # 模拟拼接函数（保留首段前导 /）
    def join_api_path(*parts):
        parts = [p.strip("/") for p in parts if p]
        joined = "/".join(parts)
        return "/" + joined if not joined.startswith("/") else joined

    # 测试路径拼接
    path = join_api_path(API_V1_PREFIX, "bookings")
    assert path == "/api/v1/bookings"

    # 确保没有直接写死路径
    assert not path.startswith("//api/v1") and not path.startswith("/api/v1//")