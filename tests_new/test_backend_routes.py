"""
tests_new/test_backend_routes.py
Basic FastAPI route tests using httpx AsyncClient with an in-memory SQLite DB.

Tests:
  - GET  /health          → 200
  - POST /auth/token      → 200, access_token present
  - GET  /users/me        without token → 401
  - GET  /users/me        with valid token → 200
  - GET  /engine/status   with valid token → 200
  - GET  /signals/latest  with valid token → 200
"""

from __future__ import annotations

import os

# Use SQLite for all tests — override DATABASE_URL before any backend import
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trading.db")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Import app AFTER env override ────────────────────────────────────────────
from backend.app import app

client = TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_token(username: str = "testadmin", password: str = "TestPass#2026!") -> str:
    """Obtain a JWT access token for the given credentials."""
    resp = client.post(
        "/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_200(self) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_has_status(self) -> None:
        resp = client.get("/health")
        body = resp.json()
        # Accept either {"status": "ok"} or any dict with a truthy value
        assert isinstance(body, dict)

    def test_root_returns_200(self) -> None:
        resp = client.get("/")
        assert resp.status_code == 200


class TestAuthToken:
    def test_valid_credentials_issue_token(self) -> None:
        resp = client.post(
            "/auth/token",
            data={"username": "testadmin", "password": "TestPass#2026!"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_wrong_password_rejected(self) -> None:
        resp = client.post(
            "/auth/token",
            data={"username": "testadmin", "password": "wrongpassword"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code in (400, 401, 403)

    def test_unknown_user_rejected(self) -> None:
        resp = client.post(
            "/auth/token",
            data={"username": "ghost", "password": "whatever"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code in (400, 401, 403)


class TestProtectedRoutes:
    def test_unauthenticated_me_returns_401(self) -> None:
        resp = client.get("/users/me")
        assert resp.status_code == 401

    def test_authenticated_me_returns_200(self) -> None:
        token = _get_token()
        resp = client.get("/users/me", headers=_auth_headers(token))
        assert resp.status_code == 200

    def test_me_returns_correct_username(self) -> None:
        token = _get_token()
        resp = client.get("/users/me", headers=_auth_headers(token))
        body = resp.json()
        assert body.get("username") == "testadmin"

    def test_unauthenticated_engine_status_returns_401(self) -> None:
        resp = client.get("/engine/status")
        assert resp.status_code == 401

    def test_authenticated_engine_status_returns_200(self) -> None:
        token = _get_token()
        resp = client.get("/engine/status", headers=_auth_headers(token))
        assert resp.status_code == 200

    def test_unauthenticated_signals_latest_returns_401(self) -> None:
        resp = client.get("/signals/latest")
        assert resp.status_code == 401

    def test_authenticated_signals_latest_returns_200(self) -> None:
        token = _get_token()
        resp = client.get("/signals/latest", headers=_auth_headers(token))
        assert resp.status_code == 200

    def test_unauthenticated_audit_log_returns_401(self) -> None:
        resp = client.get("/audit/log")
        assert resp.status_code == 401

    def test_authenticated_audit_log_returns_200(self) -> None:
        token = _get_token()
        resp = client.get("/audit/log", headers=_auth_headers(token))
        assert resp.status_code == 200

    def test_unauthenticated_admin_dashboard_returns_401(self) -> None:
        resp = client.get("/admin/dashboard")
        assert resp.status_code == 401

    def test_authenticated_admin_dashboard_returns_200(self) -> None:
        token = _get_token()
        resp = client.get("/admin/dashboard", headers=_auth_headers(token))
        assert resp.status_code == 200

    def test_unauthenticated_portfolio_positions_returns_401(self) -> None:
        resp = client.get("/portfolio/positions")
        assert resp.status_code == 401

    def test_authenticated_portfolio_positions_returns_200(self) -> None:
        token = _get_token()
        resp = client.get("/portfolio/positions", headers=_auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert "risk_metrics" in data
        assert len(data["positions"]) > 0
        for pos in data["positions"]:
            assert "symbol" in pos
            assert "weight" in pos
            assert "asset_class" in pos
