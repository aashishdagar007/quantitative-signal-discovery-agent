"""
tests_new/test_kronos_ai_desk.py
Coverage for Task 5:
  - Kronos probabilistic forecasting fed into AI Desk consensus
  - ForecastAgent node in LangGraph / Fallback pipeline
  - ED25519-signed consensus includes forecast data and influence
"""

from __future__ import annotations

import asyncio

import pytest

from core_engine.ai_desk import ForecastAgent, KeyManager, create_ai_desk, run_ai_desk


class TestKronosForecastAgent:
    def test_forecast_agent_direct_invocation(self) -> None:
        km = KeyManager()
        agent = ForecastAgent(km)
        state = {
            "messages": [],
            "market_data": {
                "symbol": "BTCUSDT",
                "prices": [64000.0, 64200.0, 64500.0, 64800.0, 65000.0],
            },
            "consensus": None,
            "signature": None,
            "risk_score": 0.0,
            "direction": None,
            "confidence": 0.0,
            "position_size_pct": 0.0,
            "kronos_forecast": None,
        }
        updated = agent.forecast(state)
        assert updated["kronos_forecast"] is not None
        assert "predicted_price" in updated["kronos_forecast"]
        assert len(updated["messages"]) == 1
        assert updated["messages"][0]["agent"] == "kronos_forecast"
        assert updated["messages"][0]["direction"] in ("long", "short", "neutral")


class TestAIDeskWithKronosConsensus:
    def test_pipeline_contains_forecast_data(self) -> None:
        async def _run():
            result = await run_ai_desk(
                symbol="EUR/USD",
                prices=[1.0800, 1.0815, 1.0805, 1.0825, 1.0810, 1.0835, 1.0828, 1.0842],
            )
            # 1. Forecast data reaches the consensus payload
            assert result["kronos_forecast"] is not None
            assert result["forecast_predicted_price"] is not None
            assert isinstance(result["forecast_predicted_price"], (int, float))

            # 2. Consensus text is generated and signed
            assert result["consensus"] is not None
            assert result["signature"] is not None
            assert result["signature_valid"] is True

            # 3. Consensus text mentions forecast
            assert "Kronos Forecast" in result["consensus"]

            # 4. Message log includes kronos_forecast agent
            agents_in_log = [m.get("agent") for m in result["messages"]]
            assert "kronos_forecast" in agents_in_log
        asyncio.run(_run())

    def test_crypto_forecast_influences_consensus(self) -> None:
        async def _run():
            result = await run_ai_desk(
                symbol="BTCUSDT",
                prices=[60000.0, 61000.0, 62000.0, 63000.0, 64000.0, 65000.0],
            )
            assert result["kronos_forecast"] is not None
            assert result["direction"] in ("long", "short", "neutral")
            assert result["signature_valid"] is True
        asyncio.run(_run())
