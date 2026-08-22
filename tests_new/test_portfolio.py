"""
tests_new/test_portfolio.py
Coverage for core_engine/portfolio_allocation.py:
  - HierarchicalRiskParity.fit(df).allocate() → weights keyed by column names, sum=1
  - HierarchicalRiskParity.compute_cvar() → sane RiskMetrics
"""

from __future__ import annotations

import numpy as np
import pytest

# pandas may not be on path in CI — skip gracefully
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from core_engine.portfolio_allocation import (
    HierarchicalRiskParity,
    PortfolioPosition,
    RiskMetrics,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def synthetic_returns_array() -> np.ndarray:
    """250 daily returns for 4 synthetic assets, shape (250, 4)."""
    rng = np.random.default_rng(42)
    return rng.normal(0.0005, 0.02, size=(250, 4))


@pytest.fixture()
def asset_symbols() -> list[str]:
    return ["BTCUSDT", "ETHUSDT", "EURUSD", "GBPUSD"]


@pytest.fixture()
def synthetic_returns_df(synthetic_returns_array, asset_symbols):
    if not PANDAS_AVAILABLE:
        pytest.skip("pandas not available")
    return pd.DataFrame(synthetic_returns_array, columns=asset_symbols)


# ── HRP with numpy array ──────────────────────────────────────────────────────

class TestHRPWithArray:
    def test_weights_sum_to_one(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        positions = hrp.allocate()
        weights = [p.weight for p in positions.values()]
        assert abs(sum(weights) - 1.0) < 1e-6, f"Weights sum to {sum(weights)}, expected 1.0"

    def test_keys_match_provided_symbols(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        positions = hrp.allocate()
        assert set(positions.keys()) == set(asset_symbols)

    def test_all_weights_non_negative(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        positions = hrp.allocate()
        for sym, pos in positions.items():
            assert pos.weight >= 0.0, f"Negative weight for {sym}: {pos.weight}"

    def test_returns_portfolio_positions(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        positions = hrp.allocate()
        for sym, pos in positions.items():
            assert isinstance(pos, PortfolioPosition)
            assert pos.symbol == sym

    def test_fit_returns_self(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        result = hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        assert result is hrp, "fit() should return self for chaining"


# ── HRP with pandas DataFrame ─────────────────────────────────────────────────

class TestHRPWithDataFrame:
    def test_keys_match_column_names(self, synthetic_returns_df, asset_symbols) -> None:
        """When a DataFrame is passed, allocate() must use column names as keys."""
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_df)   # no asset_symbols kwarg — inferred from columns
        positions = hrp.allocate()
        assert set(positions.keys()) == set(asset_symbols)

    def test_weights_sum_to_one_df(self, synthetic_returns_df) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_df)
        positions = hrp.allocate()
        weights = [p.weight for p in positions.values()]
        assert abs(sum(weights) - 1.0) < 1e-6

    def test_two_asset_minimum(self) -> None:
        """2-asset portfolio: weights must sum to 1 (minimum scipy-safe case)."""
        if not PANDAS_AVAILABLE:
            pytest.skip("pandas not available")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            rng.normal(0, 0.01, (100, 2)),
            columns=["BTCUSDT", "ETHUSDT"],
        )
        hrp = HierarchicalRiskParity()
        hrp.fit(df)
        positions = hrp.allocate()
        weights = [p.weight for p in positions.values()]
        assert abs(sum(weights) - 1.0) < 1e-6
        assert set(positions.keys()) == {"BTCUSDT", "ETHUSDT"}


# ── CVaR metrics ──────────────────────────────────────────────────────────────

class TestCVaR:
    def test_compute_cvar_returns_risk_metrics(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        # portfolio_returns = weighted sum of per-asset returns
        weights = np.array([p.weight for p in hrp.allocate().values()])
        port_returns = synthetic_returns_array @ weights
        metrics = hrp.compute_cvar(port_returns)
        assert isinstance(metrics, RiskMetrics)

    def test_cvar_values_are_finite(self, synthetic_returns_array, asset_symbols) -> None:
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        weights = np.array([p.weight for p in hrp.allocate().values()])
        port_returns = synthetic_returns_array @ weights
        metrics = hrp.compute_cvar(port_returns)
        assert np.isfinite(metrics.cvar_95),    f"cvar_95 not finite: {metrics.cvar_95}"
        assert np.isfinite(metrics.cvar_99),    f"cvar_99 not finite: {metrics.cvar_99}"
        assert np.isfinite(metrics.volatility), f"volatility not finite: {metrics.volatility}"
        assert np.isfinite(metrics.var_95),     f"var_95 not finite: {metrics.var_95}"
        assert np.isfinite(metrics.var_99),     f"var_99 not finite: {metrics.var_99}"

    def test_cvar_ordering(self, synthetic_returns_array, asset_symbols) -> None:
        """CVaR(99%) should be >= CVaR(95%) (deeper tail = larger loss)."""
        hrp = HierarchicalRiskParity()
        hrp.fit(synthetic_returns_array, asset_symbols=asset_symbols)
        weights = np.array([p.weight for p in hrp.allocate().values()])
        port_returns = synthetic_returns_array @ weights
        metrics = hrp.compute_cvar(port_returns)
        assert metrics.cvar_99 >= metrics.cvar_95 - 1e-9, (
            f"Expected cvar_99 ({metrics.cvar_99:.6f}) >= cvar_95 ({metrics.cvar_95:.6f})"
        )

    def test_empty_returns_does_not_crash(self) -> None:
        hrp = HierarchicalRiskParity()
        metrics = hrp.compute_cvar(np.array([]))
        assert isinstance(metrics, RiskMetrics)
        assert metrics.cvar_95 == 0
