"""Tests for the demo Flask app."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"


def test_divide(client):
    resp = client.get("/divide/10/4")
    assert resp.status_code == 200
    data = resp.get_json()
    # 10 / 4 = 2.5 — float division expected
    assert data["result"] == 2.5, f"Expected 2.5 but got {data['result']}"


def test_divide_by_zero(client):
    resp = client.get("/divide/5/0")
    assert resp.status_code == 400
