"""
AI Trading System — Main FastAPI Application
Wires together: RBAC, WebSockets, all routers, AI desk, execution engine.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Load environment
for env_path in ["infrastructure/.env", ".env", "../infrastructure/.env"]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

from backend.database import (
    AuditLog,
    Signal,
    User,
    authenticate_user,
    create_db_and_tables,
    get_db,
    get_user_by_username,
    hash_password,
    seed_team_members,
)

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY                 = os.environ.get("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION")
ALGORITHM                  = os.environ.get("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
CORS_ORIGINS               = os.environ.get(
    "API_CORS_ORIGINS", "http://localhost:3000,http://localhost:8080,http://127.0.0.1:5500"
).split(",")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    """Manages WebSocket connections per channel."""

    def __init__(self) -> None:
        self._connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, channel: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(channel, []).append(ws)

    def disconnect(self, channel: str, ws: WebSocket) -> None:
        conns = self._connections.get(channel, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, channel: str, data: Any) -> None:
        message = json.dumps(data) if not isinstance(data, str) else data
        dead: List[WebSocket] = []
        for ws in self._connections.get(channel, []):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)


manager = ConnectionManager()

# Shared in-memory state (for demo; production would use Redis pub/sub)
_market_state: Dict[str, Any] = {
    "BTCUSDT": {"price": 65000.0, "change_pct": 0.0},
    "ETHUSDT": {"price": 3500.0,  "change_pct": 0.0},
    "EURUSD":  {"price": 1.0845,  "change_pct": 0.0},
}
_agent_debates: List[Dict] = []
_engine_running: bool = False


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Startup] Creating database tables…")
    create_db_and_tables()
    print("[Startup] Seeding RBAC team…")
    seed_team_members()
    print("[Startup] AI Trading System ready.")
    yield
    # Shutdown
    print("[Shutdown] Cleaning up…")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Trading System API",
    description=(
        "Production-grade multi-asset AI Trading System. "
        "Crypto (Binance) + Forex (MT5/FIX) with LangGraph agents, "
        "Kronos forecasting, HRP/CVaR portfolio allocation, "
        "and a blockchain audit trail."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── JWT helpers ───────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None


def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=payload.get("role"))
    except JWTError:
        raise credentials_exception

    user = get_user_by_username(db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def require_role(*roles: str):
    """Dependency factory for role-based access control."""
    def _check(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted. Required: {list(roles)}",
            )
        return current_user
    return _check


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class SignalResponse(BaseModel):
    symbol: str
    direction: str
    confidence: float
    risk_score: Optional[float]
    signature: Optional[str]
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/token", response_model=Token, tags=["Auth"])
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    return {"access_token": access_token, "token_type": "bearer"}


# ── User / RBAC routes ────────────────────────────────────────────────────────

@app.get("/users/me", response_model=UserResponse, tags=["Users"])
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user


@app.get("/users/team", response_model=List[UserResponse], tags=["Users"])
async def list_team(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "quant")),
):
    return db.query(User).all()


@app.post("/users/create", response_model=UserResponse, tags=["Users"])
async def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    existing = get_user_by_username(db, payload.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Engine control routes ─────────────────────────────────────────────────────

@app.post("/engine/start", tags=["Engine"])
async def start_engine(_: User = Depends(require_role("admin", "quant"))):
    global _engine_running
    _engine_running = True
    await manager.broadcast("system", {"event": "engine_start", "timestamp": datetime.utcnow().isoformat()})
    return {"status": "Engine started", "running": True}


@app.post("/engine/stop", tags=["Engine"])
async def stop_engine(_: User = Depends(require_role("admin"))):
    global _engine_running
    _engine_running = False
    await manager.broadcast("system", {"event": "engine_stop", "timestamp": datetime.utcnow().isoformat()})
    return {"status": "Engine stopped", "running": False}


@app.get("/engine/status", tags=["Engine"])
async def engine_status(current_user: User = Depends(get_current_active_user)):
    return {
        "running": _engine_running,
        "markets": list(_market_state.keys()),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Signals routes ─────────────────────────────────────────────────────────────

@app.get("/signals/latest", tags=["Signals"])
async def latest_signals(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    signals = db.query(Signal).order_by(Signal.created_at.desc()).limit(20).all()
    return [
        {
            "symbol": s.symbol,
            "direction": s.direction,
            "confidence": s.confidence,
            "risk_score": s.risk_score,
            "source": s.source,
            "created_at": s.created_at.isoformat(),
        }
        for s in signals
    ]


@app.post("/signals/run_ai_desk", tags=["Signals"])
async def trigger_ai_desk(
    symbol: str = "EURUSD",
    _: User = Depends(require_role("admin", "quant", "trader")),
):
    """Trigger an asynchronous AI desk analysis via Celery."""
    try:
        from backend.celery_app import celery_app
        task = celery_app.send_task(
            "backend.tasks.ai_desk_tasks.run_ai_desk",
            args=[symbol],
            queue="ai_desk",
        )
        return {"task_id": task.id, "symbol": symbol, "status": "queued"}
    except Exception as e:
        # Fallback: return placeholder if Celery not running
        return {"task_id": "offline", "symbol": symbol, "status": "celery_offline", "error": str(e)}


# ── Audit routes ──────────────────────────────────────────────────────────────

@app.get("/audit/log", tags=["Audit"])
async def get_audit_log(
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    import json as _json
    offset = (page - 1) * limit
    entries = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "tx_id": e.tx_id,
            "block_index": e.block_index,
            "event_type": e.event_type,
            "block_hash": e.block_hash,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.get("/admin/dashboard", tags=["Admin"])
async def admin_dashboard(current_user: User = Depends(require_role("admin"))):
    return {
        "message": "Admin dashboard",
        "user": current_user.username,
        "role": current_user.role,
        "system": "AI Trading System v1.0",
    }


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/", tags=["System"])
async def root():
    return {"message": "AI Trading System API — visit /docs for interactive API documentation"}


# ── WebSocket: Live market data stream ────────────────────────────────────────

@app.websocket("/ws/market")
async def ws_market(websocket: WebSocket):
    """Streams live simulated/real market tick data to connected clients."""
    await manager.connect("market", websocket)
    try:
        import random, math
        tick = 0
        while True:
            await asyncio.sleep(1.0)
            tick += 1
            # Simulate realistic market microstructure
            btc_delta = random.gauss(0, 150) + math.sin(tick * 0.05) * 20
            eth_delta = random.gauss(0, 40)  + math.sin(tick * 0.07) * 8
            eur_delta = random.gauss(0, 0.0003) + math.sin(tick * 0.03) * 0.0001

            _market_state["BTCUSDT"]["change_pct"] = btc_delta / _market_state["BTCUSDT"]["price"] * 100
            _market_state["ETHUSDT"]["change_pct"] = eth_delta / _market_state["ETHUSDT"]["price"] * 100
            _market_state["EURUSD"]["change_pct"]  = eur_delta / _market_state["EURUSD"]["price"]  * 100

            _market_state["BTCUSDT"]["price"] = max(1000, _market_state["BTCUSDT"]["price"] + btc_delta)
            _market_state["ETHUSDT"]["price"] = max(100,  _market_state["ETHUSDT"]["price"] + eth_delta)
            _market_state["EURUSD"]["price"]  = max(0.5,  _market_state["EURUSD"]["price"]  + eur_delta)

            payload = {
                "type": "market_tick",
                "tick": tick,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {k: {**v, "price": round(v["price"], 5)} for k, v in _market_state.items()},
            }
            await manager.broadcast("market", payload)
    except WebSocketDisconnect:
        manager.disconnect("market", websocket)


# ── WebSocket: AI agent debate stream ─────────────────────────────────────────

@app.websocket("/ws/agents")
async def ws_agents(websocket: WebSocket):
    """Streams LangGraph agent debate messages to connected clients."""
    await manager.connect("agents", websocket)
    try:
        agents = ["fundamentals", "sentiment", "technical", "debaters_bull", "debaters_bear", "risk_manager"]
        sample_messages = [
            "Analyzing EUR/USD macroeconomic backdrop: ECB rate decision pending…",
            "On-chain BTC whale accumulation detected: 12,450 BTC moved to cold storage…",
            "Technical: BTC testing 200-day EMA at $64,820. RSI: 52. Neutral zone.",
            "Bull case: Fed pivot signals weaken USD, EUR momentum building…",
            "Bear case: Geopolitical risk elevated, safe-haven flows to USD…",
            "Risk Manager: CVaR(95%) = 2.14%. HRP weight: BTC=18.2%, ETH=11.4%, EUR/USD=8.7%",
            "Consensus reached: LONG EUR/USD (confidence: 73.2%). Signing with ED25519…",
            "Signal dispatched to execution core. PulseHyperHybrid activated.",
        ]
        idx = 0
        while True:
            await asyncio.sleep(3.5)
            agent = agents[idx % len(agents)]
            message = sample_messages[idx % len(sample_messages)]
            payload = {
                "type": "agent_message",
                "agent": agent,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            _agent_debates.append(payload)
            if len(_agent_debates) > 200:
                _agent_debates.pop(0)
            await manager.broadcast("agents", payload)
            idx += 1
    except WebSocketDisconnect:
        manager.disconnect("agents", websocket)