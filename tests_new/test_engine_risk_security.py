"""
tests_new/test_engine_risk_security.py
Coverage for Task 3 & Task 4:
  - Explicit PAPER/LIVE state machine & DB persistence
  - POST /engine/mode RBAC-restricted toggle + blockchain ledger entry
  - Risk guards in execution_engine.py (max notional cap & daily loss circuit breaker)
  - Security profiler integration in execution path & GET /security/status
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_trading.db")

from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_trading_mode, set_trading_mode
from blockchain_audit.ledger import ImmutableLedger
from core_engine.execution_engine import DualMarketEngine, RiskLimitExceeded
from security.python_security_profiler import profiler as security_profiler
from tests_new.conftest import TestingSessionLocal

client = TestClient(app, raise_server_exceptions=True)


def _get_token(username: str, password: str) -> str:
    resp = client.post(
        "/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, f"Auth failed for {username}: {resp.text}"
    return resp.json()["access_token"]


# ══════════════════════════════════════════════════════════════════════════════
#  Task 3: Trading State & Risk Guards Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTradingStateMachine:
    def test_default_mode_is_paper(self) -> None:
        db = TestingSessionLocal()
        mode = get_trading_mode(db)
        db.close()
        assert mode == "PAPER"

    def test_set_and_get_trading_mode(self) -> None:
        db = TestingSessionLocal()
        set_trading_mode(db, "LIVE", set_by="test_runner")
        assert get_trading_mode(db) == "LIVE"
        set_trading_mode(db, "PAPER", set_by="test_runner")
        assert get_trading_mode(db) == "PAPER"
        db.close()

    def test_invalid_mode_raises(self) -> None:
        db = TestingSessionLocal()
        with pytest.raises(ValueError):
            set_trading_mode(db, "INVALID_MODE")
        db.close()

    def test_get_engine_mode_endpoint(self) -> None:
        token = _get_token("viewer_user", "ViewerSecret#1")
        resp = client.get("/engine/mode", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert "mode" in resp.json()

    def test_non_admin_cannot_toggle_mode(self) -> None:
        token = _get_token("viewer_user", "ViewerSecret#1")
        resp = client.post(
            "/engine/mode",
            json={"mode": "LIVE"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403  # forbidden for viewer

    def test_admin_can_toggle_mode_and_creates_ledger_entry(self, tmp_path) -> None:
        token = _get_token("admin_user", "AdminSecret#1")
        resp = client.post(
            "/engine/mode",
            json={"mode": "LIVE"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "LIVE"
        assert data["changed"] is True
        assert data["tx_id"] != ""

        # Toggle back to PAPER
        resp2 = client.post(
            "/engine/mode",
            json={"mode": "PAPER"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["mode"] == "PAPER"


class TestExecutionEngineRiskGuards:
    def test_paper_mode_order_not_sent_to_live_venue(self) -> None:
        async def _run():
            engine = DualMarketEngine()
            engine.mode = "PAPER"
            order = await engine.execute_order("BTCUSDT", "buy", 100.0)  # very large notional
            assert order["status"] == "PAPER"
            assert order["mode"] == "PAPER"
        asyncio.run(_run())

    def test_live_mode_exceeding_notional_cap_is_rejected(self) -> None:
        async def _run():
            engine = DualMarketEngine()
            engine.mode = "LIVE"
            engine.max_order_notional = 1000.0  # $1,000 cap
            # BTC price default ~65,000 → 1 BTC = $65,000 > $1,000
            with pytest.raises(RiskLimitExceeded) as exc_info:
                await engine.execute_order("BTCUSDT", "buy", 1.0, price=65000.0)
            assert "exceeds maximum allowed cap" in str(exc_info.value)
        asyncio.run(_run())

    def test_live_mode_daily_loss_circuit_breaker(self) -> None:
        async def _run():
            engine = DualMarketEngine()
            engine.mode = "LIVE"
            engine.max_order_notional = 100000.0
            engine.max_daily_loss = 2000.0
            engine.daily_loss = 2500.0  # breached
            with pytest.raises(RiskLimitExceeded) as exc_info:
                await engine.execute_order("BTCUSDT", "buy", 0.01, price=65000.0)
            assert "circuit breaker" in str(exc_info.value)
        asyncio.run(_run())


# ══════════════════════════════════════════════════════════════════════════════
#  Task 4: Security Profiler Integration Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityProfilerIntegration:
    def test_order_execution_registers_with_profiler(self) -> None:
        async def _run():
            engine = DualMarketEngine()
            engine.mode = "PAPER"
            # Profiler execution monitoring should be called during order
            order = await engine.execute_order("EURUSD", "buy", 0.01, price=1.0850)
            assert order["id"] in [r.get("order_id") for r in engine.profiler._impl._exec_records]
            assert engine.profiler.get_current_state() is not None
        asyncio.run(_run())

    def test_security_status_endpoint(self) -> None:
        token = _get_token("admin_user", "AdminSecret#1")
        resp = client.get("/security/status", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "summary" in data
        assert "anomalies" in data
        assert "using_cpp" in data
