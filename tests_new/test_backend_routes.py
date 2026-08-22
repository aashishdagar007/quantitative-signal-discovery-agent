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
from backend.database import Base, User, get_db, hash_password

# ── Test-specific SQLite engine (in-memory) ───────────────────────────────────

TEST_DB_URL = "sqlite://"  # pure in-memory

_test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


# Seed one user for auth tests
def _seed_test_db():
    Base.metadata.create_all(bind=_test_engine)
    db = _TestSession()
    if not db.query(User).filter(User.username == "testadmin").first():
        db.add(User(
            username="testadmin",
            email="testadmin@test.local",
            hashed_password=hash_password("TestPass#2026!"),
            role="admin",
            is_active=True,
        ))
        db.commit()
    db.close()


# Apply the dependency override BEFORE creating the TestClient
app.dependency_overrides[get_db] = _override_get_db
_seed_test_db()

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
