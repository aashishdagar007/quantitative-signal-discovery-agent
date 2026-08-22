"""
tests_new/conftest.py
Shared test database setup and FastAPI dependency override for tests_new/.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trading.db")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import app
from backend.database import Base, User, get_db, hash_password, seed_team_members

TEST_DB_URL = "sqlite://"

test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    """Create all tables, apply dependency override, and seed all test users."""
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()
    # Seed standard users
    test_users = [
        ("testadmin", "testadmin@test.local", "TestPass#2026!", "admin"),
        ("admin_user", "admin@test.local", "AdminSecret#1", "admin"),
        ("viewer_user", "viewer@test.local", "ViewerSecret#1", "viewer"),
    ]
    for username, email, pwd, role in test_users:
        if not db.query(User).filter(User.username == username).first():
            db.add(User(
                username=username,
                email=email,
                hashed_password=hash_password(pwd),
                role=role,
                is_active=True,
            ))
    db.commit()
    db.close()
    yield
    app.dependency_overrides.pop(get_db, None)
