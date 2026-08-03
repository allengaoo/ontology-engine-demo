"""API URL 规范化契约。"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
IFCLUB = Path(__file__).resolve().parents[4]
if str(IFCLUB) not in sys.path:
    sys.path.insert(0, str(IFCLUB))
from harness.api_url_contract import check_api_url_contract  # noqa: E402

def test_api_url_contract():
    result = check_api_url_contract(ROOT)
    assert result.ok, result.summary()