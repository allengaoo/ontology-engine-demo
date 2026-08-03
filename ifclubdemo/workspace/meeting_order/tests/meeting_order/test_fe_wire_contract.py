"""前端接线契约：不启浏览器，专抓列表/控件/刷新假活。"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
IFCLUB = Path(__file__).resolve().parents[4]
if str(IFCLUB) not in sys.path:
    sys.path.insert(0, str(IFCLUB))
from harness.fe_api_contract import check_fe_api_contract  # noqa: E402

def test_fe_api_wire_contract():
    result = check_fe_api_contract(ROOT)
    assert result.ok, result.summary()

@pytest.mark.parametrize(
    "rel,needle",
    [
        ("frontend/src/components/BookingForm.tsx", 'type="datetime-local"'),
        ("frontend/src/components/BookingForm.tsx", "FormData"),
        ("frontend/src/pages/BookingPage.tsx", "rooms={rooms}"),
        ("frontend/src/pages/BookingPage.tsx", "refreshBookings"),
        ("frontend/src/api/client.ts", "joinApiPath"),
    ],
)
def test_fe_wire_needles(rel: str, needle: str):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert needle in text, f"{rel} 缺少 {needle!r}"

def test_fe_no_double_api_prefix():
    page = (ROOT / "frontend/src/pages/BookingPage.tsx").read_text(encoding="utf-8")
    assert 'apiGet("/api/v1/' not in page
    assert '"/rooms"' in page and '"/bookings"' in page