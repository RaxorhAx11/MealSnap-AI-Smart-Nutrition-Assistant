from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


def _login_and_get_token(client: TestClient, username_or_email: str, password: str) -> str:
    r = client.post("/auth/login", json={"username_or_email": username_or_email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    return data["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_and_root(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


def test_login_seed_users(client: TestClient) -> None:
    t1 = _login_and_get_token(client, "test_alex", "TestPassword!123")
    t2 = _login_and_get_token(client, "priya.qa@example.com", "TestPassword!123")
    assert t1 and t2


def test_profile_get_update_and_target(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")

    # profile exists (seeded)
    r = client.get("/profile", headers=_auth_headers(token))
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["user_id"] > 0

    # update profile (change target weight slightly)
    r2 = client.post(
        "/profile/update",
        headers=_auth_headers(token),
        json={"target_weight_kg": float(prof.get("target_weight_kg") or 78.0) - 0.5},
    )
    assert r2.status_code == 200, r2.text

    # nutrition target should compute
    r3 = client.get("/nutrition/target", headers=_auth_headers(token))
    assert r3.status_code == 200, r3.text
    tgt = r3.json()
    assert tgt["daily_calorie_target"] > 0
    assert tgt["recommended_protein"] > 0
    assert tgt["recommended_carbs"] >= 0
    assert tgt["recommended_fats"] > 0


def test_dashboard_and_insights(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")

    r = client.get("/dashboard?days=30", headers=_auth_headers(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert "nutrition_history" in data
    assert "weight_history" in data

    # latest summary exists (seeded)
    r2 = client.get("/dashboard-nutrition", headers=_auth_headers(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["calories"] >= 0

    # suggestions should be stable even if no gaps
    r3 = client.get("/next-purchase-suggestions", headers=_auth_headers(token))
    assert r3.status_code == 200, r3.text
    assert "suggestions" in r3.json()

    r4 = client.get("/nutrition-gaps", headers=_auth_headers(token))
    assert r4.status_code == 200, r4.text
    assert "gaps" in r4.json()


def test_weight_log_history_analysis_recommendations(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")

    # history should exist due to seeding
    r1 = client.get("/weight/history?days=14", headers=_auth_headers(token))
    assert r1.status_code == 200, r1.text
    assert len(r1.json()) >= 7

    # analysis should work (seeded 14 days)
    r2 = client.get("/weight/analysis", headers=_auth_headers(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["trend"] in ("decreasing", "increasing", "stable")

    # recommendations should return a list
    r3 = client.get("/weight/recommendations", headers=_auth_headers(token))
    assert r3.status_code == 200, r3.text
    assert isinstance(r3.json().get("recommendations"), list)

    # adding today's weight should conflict because seeding adds one per day including today
    r4 = client.post("/weight/add", headers=_auth_headers(token), json={"weight_kg": 81.0, "note": "duplicate"})
    assert r4.status_code == 409, r4.text


def test_receipt_history_seeded(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")
    r = client.get("/receipts/history", headers=_auth_headers(token))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert "receipt_date" in rows[0]
    assert "items_count" in rows[0]


def test_generate_meal_plan_uses_db_confirmed_items(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")
    r = client.post("/generate-meal-plan", headers=_auth_headers(token), json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert "plan" in data and "days" in data["plan"]


def test_analyze_nutrition_validation_and_response_shape(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")

    # invalid payload should 422
    bad = client.post("/analyze-nutrition", headers=_auth_headers(token), json={"items": []})
    assert bad.status_code in (400, 422), bad.text

    # minimal valid payload
    payload = {
        "items": [
            {"name": "oats", "quantity": 80, "unit": "g"},
            {"name": "milk", "quantity": 250, "unit": "ml"},
        ]
    }
    r = client.post("/analyze-nutrition", headers=_auth_headers(token), json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert "summary" in data and "items" in data


def test_weights_legacy_endpoints(client: TestClient) -> None:
    token = _login_and_get_token(client, "test_alex", "TestPassword!123")
    today = date.today()
    yesterday = today - timedelta(days=1)

    # fetching should work
    r = client.get("/weights", headers=_auth_headers(token))
    assert r.status_code == 200, r.text

    # saving should update-or-create without error
    r2 = client.post("/weights", headers=_auth_headers(token), json={"date": str(yesterday), "weight": 81.5})
    assert r2.status_code == 200, r2.text

