"""
AI Trading System — Database Models & Session Management
SQLAlchemy ORM with PostgreSQL backend, loaded from environment.
"""

import os
from datetime import datetime
from typing import Generator, Optional

from dotenv import load_dotenv

# Load environment variables FIRST so DATABASE_URL is resolved from .env
for env_path in [".env", "infrastructure/.env", "../infrastructure/.env"]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

# ── Database connection ────────────────────────────────────────────────────────

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://trading_user:trading_pass@localhost:5432/trading_db"
)

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite: use StaticPool (single connection) — safe for dev/testing
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    # PostgreSQL / other RDBMS: production pool settings
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── ORM Base ───────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass

# ── Password hashing ──────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    """RBAC user model — admin / quant / trader / viewer"""
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(64), unique=True, index=True, nullable=False)
    email           = Column(String(128), unique=True, index=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    role            = Column(String(16), nullable=False, default="viewer")
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login      = Column(DateTime, nullable=True)

    positions  = relationship("Position", back_populates="owner")
    orders     = relationship("Order", back_populates="user")


class Position(Base):
    """Open / closed trading position"""
    __tablename__ = "positions"

    id            = Column(Integer, primary_key=True, index=True)
    symbol        = Column(String(32), nullable=False, index=True)
    asset_class   = Column(String(16), nullable=False)   # crypto | forex
    side          = Column(String(8), nullable=False)     # long | short
    quantity      = Column(Numeric(20, 8), nullable=False)
    entry_price   = Column(Numeric(20, 8), nullable=False)
    current_price = Column(Numeric(20, 8), nullable=True)
    status        = Column(String(16), nullable=False, default="open")
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=True)
    opened_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at     = Column(DateTime, nullable=True)

    owner  = relationship("User", back_populates="positions")
    orders = relationship("Order", back_populates="position")


class Order(Base):
    """Individual order record linked to a position"""
    __tablename__ = "orders"

    id           = Column(Integer, primary_key=True, index=True)
    order_id     = Column(String(64), unique=True, nullable=True)
    symbol       = Column(String(32), nullable=False)
    asset_class  = Column(String(16), nullable=False)
    side         = Column(String(8), nullable=False)
    order_type   = Column(String(16), nullable=False, default="market")
    quantity     = Column(Numeric(20, 8), nullable=False)
    price        = Column(Numeric(20, 8), nullable=True)
    filled_price = Column(Numeric(20, 8), nullable=True)
    status       = Column(String(16), nullable=False, default="pending")
    exchange     = Column(String(32), nullable=False, default="binance")
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=True)
    position_id  = Column(Integer, ForeignKey("positions.id"), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    filled_at    = Column(DateTime, nullable=True)

    user     = relationship("User", back_populates="orders")
    position = relationship("Position", back_populates="orders")


class Signal(Base):
    """AI-generated directional trading signal with cryptographic signature"""
    __tablename__ = "signals"

    id         = Column(Integer, primary_key=True, index=True)
    symbol     = Column(String(32), nullable=False, index=True)
    direction  = Column(String(8), nullable=False)         # long | short | neutral
    confidence = Column(Float, nullable=False, default=0.0)
    risk_score = Column(Float, nullable=True)
    consensus  = Column(Text, nullable=True)
    signature  = Column(Text, nullable=True)
    source     = Column(String(32), nullable=False, default="ai_desk")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AuditLog(Base):
    """Mirror of the blockchain ledger for fast SQL querying"""
    __tablename__ = "audit_log"

    id          = Column(Integer, primary_key=True, index=True)
    tx_id       = Column(String(128), unique=True, nullable=False)
    block_index = Column(Integer, nullable=False, index=True)
    event_type  = Column(String(32), nullable=False)       # trade | consensus | state_change
    payload     = Column(Text, nullable=False)              # JSON string
    block_hash  = Column(String(256), nullable=False)
    merkle_root = Column(String(256), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ── DB lifecycle helpers ──────────────────────────────────────────────────────

def create_db_and_tables() -> None:
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ── Seed: 4-person RBAC team ──────────────────────────────────────────────────

TEAM_MEMBERS = [
    {
        "username": os.environ.get("ADMIN_USERNAME", "Lalit"),
        "email": "lalit@trading.local",
        "password": os.environ.get("ADMIN_PASSWORD", "AdminPass#2026!"),
        "role": "admin",
    },
    {
        "username": "quant_dev",
        "email": "quant@trading.local",
        "password": "QuantPass#2026!",
        "role": "quant",
    },
    {
        "username": "trader_lead",
        "email": "trader@trading.local",
        "password": "TraderPass#2026!",
        "role": "trader",
    },
    {
        "username": "risk_viewer",
        "email": "viewer@trading.local",
        "password": "ViewerPass#2026!",
        "role": "viewer",
    },
]


def seed_default_admin(
    username: str = "Lalit",
    password: str = "AdminPass#2026!",
    role: str = "admin",
) -> None:
    """Seed the default admin user if not present."""
    db = SessionLocal()
    try:
        existing = get_user_by_username(db, username)
        if not existing:
            user = User(
                username=username,
                email=f"{username.lower()}@trading.local",
                hashed_password=hash_password(password),
                role=role,
                is_active=True,
            )
            db.add(user)
            db.commit()
            print(f"[DB] Admin user '{username}' seeded successfully.")
        else:
            print(f"[DB] Admin user '{username}' already exists.")
    finally:
        db.close()


def seed_team_members() -> None:
    """Seed the full 4-person development team if not present."""
    db = SessionLocal()
    try:
        for member in TEAM_MEMBERS:
            existing = get_user_by_username(db, member["username"])
            if not existing:
                user = User(
                    username=member["username"],
                    email=member["email"],
                    hashed_password=hash_password(member["password"]),
                    role=member["role"],
                    is_active=True,
                )
                db.add(user)
                print(f"[DB] Team member '{member['username']}' ({member['role']}) seeded.")
        db.commit()
    finally:
        db.close()
