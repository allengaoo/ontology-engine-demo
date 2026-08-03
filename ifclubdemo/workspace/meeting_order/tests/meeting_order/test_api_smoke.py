from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
from meeting_order.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
