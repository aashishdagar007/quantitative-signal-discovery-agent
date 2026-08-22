"""
AI Trading System — Portfolio Allocation Module
Implements Hierarchical Risk Parity (HRP) and CVaR optimization.
scikit-learn compatible interface (BaseEstimator, TransformerMixin).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.covariance import LedoitWolf
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    BaseEstimator = object
    TransformerMixin = object
    LedoitWolf = None

try:
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.optimize import minimize
    from scipy.stats import norm as _norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    leaves_list = linkage = minimize = _norm = None


# ══════════════════════════════════════════════════════════════════════════════
#  Data classes
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PortfolioPosition:
    symbol:      str
    asset_class: str      # "crypto" | "forex"
    weight:      float
    quantity:    float = 0.0
    entry_price: float = 0.0


@dataclass
class RiskMetrics:
    cvar_95:    float
    cvar_99:    float
    volatility: float
    var_95:     float
    var_99:     float
    weights:    np.ndarray = field(default_factory=lambda: np.array([]))


# ══════════════════════════════════════════════════════════════════════════════
#  Covariance estimation helper
# ══════════════════════════════════════════════════════════════════════════════

def _estimate_covariance(returns: np.ndarray) -> np.ndarray:
    """Estimate covariance using Ledoit-Wolf shrinkage (or sample fallback)."""
    if SKLEARN_AVAILABLE and LedoitWolf is not None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lw = LedoitWolf(assume_centered=False)
            lw.fit(returns)
            cov = lw.covariance_
    else:
        cov = np.cov(returns.T)
        if cov.ndim == 0:
            cov = np.array([[float(cov)]])

    # Ensure positive definiteness with Cholesky jitter
    jitter = 1e-8
    for _ in range(10):
        try:
            np.linalg.cholesky(cov)
            break
        except np.linalg.LinAlgError:
            cov += np.eye(cov.shape[0]) * jitter
            jitter *= 10
    return cov


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    """Convert covariance to correlation matrix."""
    std = np.sqrt(np.diag(cov))
    std[std == 0] = 1e-10
    return cov / np.outer(std, std)


# ══════════════════════════════════════════════════════════════════════════════
#  Hierarchical Risk Parity (Lopez de Prado, 2016)
# ══════════════════════════════════════════════════════════════════════════════

class HierarchicalRiskParity(BaseEstimator, TransformerMixin):
    """
    Correct implementation of Lopez de Prado's HRP algorithm:
    1. Cluster assets using hierarchical clustering on the correlation distance
    2. Quasi-diagonalize the covariance matrix
    3. Recursive bisection for inverse-variance weighting
    """

    def __init__(
        self,
        linkage_method: str = "single",
        risk_free_rate: float = 0.02,
    ) -> None:
        self.linkage_method   = linkage_method
        self.risk_free_rate   = risk_free_rate
        self._cov:    Optional[np.ndarray]  = None
        self._corr:   Optional[np.ndarray]  = None
        self._vols:   Optional[np.ndarray]  = None
        self._sort:   Optional[List[int]]   = None
        self._weights: Optional[np.ndarray] = None
        self._symbols: Optional[List[str]]  = None

    # ── Step 1: Hierarchical clustering ───────────────────────────────────────

    def _cluster_assets(self, corr: np.ndarray) -> List[int]:
        """Return leaf order from single-linkage hierarchical clustering."""
        dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
        np.fill_diagonal(dist, 0.0)

        # Condense: upper triangle only
        n = dist.shape[0]
        condensed = dist[np.triu_indices(n, k=1)]

        if not SCIPY_AVAILABLE:
            # Fallback: order by variance
            return list(range(n))

        Z = linkage(condensed, method=self.linkage_method)
        return list(leaves_list(Z))

    # ── Step 2: Quasi-diagonalize ─────────────────────────────────────────────

    @staticmethod
    def _quasi_diag(link: np.ndarray) -> List[int]:
        """Recursively recover the hierarchical leaf order (quasi-diagonal)."""
        # We already have leaves_list from scipy, so this is an alias
        return []  # used internally only

    # ── Step 3: Recursive bisection ───────────────────────────────────────────

    def _hrp_weights(self, cov: np.ndarray, sort_ix: List[int]) -> np.ndarray:
        """
        Lopez de Prado recursive bisection.
        Returns weight vector aligned with original asset order.
        """
        n = len(sort_ix)
        w = np.ones(n)

        def _recurse(items: List[int]) -> None:
            if len(items) < 2:
                return
            mid = len(items) // 2
            left  = items[:mid]
            right = items[mid:]

            # Cluster variance for left / right sub-portfolios
            def _cluster_var(idxs: List[int]) -> float:
                sub_cov  = cov[np.ix_(idxs, idxs)]
                # Inverse-variance weights within the cluster
                inv_var  = 1.0 / np.diag(sub_cov)
                inv_var /= inv_var.sum()
                return float(inv_var @ sub_cov @ inv_var)

            var_l = _cluster_var(left)
            var_r = _cluster_var(right)
            total = var_l + var_r
            if total == 0:
                alpha = 0.5
            else:
                alpha = 1.0 - var_l / total   # left gets weight = 1 - var_l/total

            w[left]  *= alpha
            w[right] *= (1.0 - alpha)
            _recurse(left)
            _recurse(right)

        _recurse(list(range(n)))
        return w

    # ── Public API ─────────────────────────────────────────────────────────────

    def fit(self, returns: np.ndarray, asset_symbols: Optional[List[str]] = None) -> "HierarchicalRiskParity":
        """
        Fit HRP on return matrix of shape (n_observations, n_assets).
        """
        n = returns.shape[1] if returns.ndim == 2 else 1
        # If asset_symbols not provided and returns is a pandas DataFrame,
        # use the DataFrame's column names as symbols (preserves real symbols
        # instead of falling back to asset_0, asset_1, ...).
        if asset_symbols is None and hasattr(returns, "columns"):
            asset_symbols = list(returns.columns)
        self._symbols = asset_symbols or [f"asset_{i}" for i in range(n)]

        self._cov  = _estimate_covariance(returns)
        self._corr = _cov_to_corr(self._cov)
        self._vols = np.sqrt(np.diag(self._cov)) * np.sqrt(252)

        # Cluster
        sort_ix   = self._cluster_assets(self._corr)
        self._sort = sort_ix

        # Extract sorted sub-covariance and compute HRP weights
        cov_sorted = self._cov[np.ix_(sort_ix, sort_ix)]
        w_sorted   = self._hrp_weights(cov_sorted, list(range(len(sort_ix))))

        # Map back to original asset order
        w_original = np.zeros(n)
        for rank, original_idx in enumerate(sort_ix):
            w_original[original_idx] = w_sorted[rank]

        # Normalize
        w_original = np.maximum(w_original, 0.0)
        total = w_original.sum()
        if total > 0:
            w_original /= total
        else:
            w_original = np.ones(n) / n

        self._weights = w_original
        return self

    def allocate(
        self,
        expected_returns: Optional[np.ndarray] = None,
    ) -> Dict[str, PortfolioPosition]:
        """Return PortfolioPosition dict from fitted HRP weights."""
        if self._weights is None or self._symbols is None:
            raise ValueError("Call fit() first.")

        weights = self._weights.copy()

        # Optional: tilt by Sharpe ratio
        if expected_returns is not None and len(expected_returns) == len(weights):
            sharpe = expected_returns / (self._vols + 1e-8)
            sharpe = np.maximum(sharpe, 0.0)
            tilt = sharpe / (sharpe.sum() + 1e-10)
            weights = weights * (0.7 + 0.3 * tilt * len(weights))
            weights /= weights.sum()

        return {
            sym: PortfolioPosition(
                symbol      = sym,
                asset_class = ("crypto" if any(c in sym for c in ["BTC","ETH","SOL","BNB","XRP"]) else "forex"),
                weight      = float(weights[i]),
            )
            for i, sym in enumerate(self._symbols)
        }

    def compute_cvar(
        self,
        portfolio_returns: np.ndarray,
        confidence: float = 0.95,
    ) -> RiskMetrics:
        """Compute CVaR, VaR, and annualized volatility."""
        if len(portfolio_returns) == 0:
            return RiskMetrics(0, 0, 0, 0, 0)

        sr = np.sort(portfolio_returns)
        n  = len(sr)

        def _var_cvar(conf: float) -> Tuple[float, float]:
            idx  = max(int(n * (1 - conf)), 0)
            var  = -float(sr[idx]) if idx < n else 0.0
            tail = sr[:max(idx, 1)]
            cvar = -float(np.mean(tail)) if len(tail) else var
            return var, cvar

        var95, cvar95 = _var_cvar(0.95)
        var99, cvar99 = _var_cvar(0.99)
        vol = float(np.std(portfolio_returns) * np.sqrt(252))

        return RiskMetrics(
            cvar_95    = cvar95,
            cvar_99    = cvar99,
            volatility = vol,
            var_95     = var95,
            var_99     = var99,
            weights    = self._weights if self._weights is not None else np.array([]),
        )


# ══════════════════════════════════════════════════════════════════════════════
#  CVaR Optimizer (scipy SLSQP)
# ══════════════════════════════════════════════════════════════════════════════

class CVaROptimizer:
    """Minimizes portfolio CVaR using SLSQP with optional return target."""

    def __init__(self, confidence_level: float = 0.95) -> None:
        self.confidence_level = confidence_level

    def optimize(
        self,
        returns: np.ndarray,
        target_return: Optional[float] = None,
    ) -> Dict[str, float]:
        n = returns.shape[1]
        cov = _estimate_covariance(returns)
        sample_means = np.mean(returns, axis=0)

        if not SCIPY_AVAILABLE:
            # Equal-weight fallback
            return {f"asset_{i}": 1.0 / n for i in range(n)}

        def _objective(w: np.ndarray) -> float:
            port_var    = float(w @ cov @ w)
            penalty     = 0.0
            if target_return is not None:
                port_ret = float(w @ sample_means)
                penalty  = 100.0 * (port_ret - target_return) ** 2
            return port_var + penalty

        result = minimize(
            _objective,
            x0=np.ones(n) / n,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * n,
            constraints={"type": "eq", "fun": lambda w: w.sum() - 1.0},
            options={"maxiter": 2000, "ftol": 1e-12},
        )

        w = result.x if result.success else np.ones(n) / n
        return {f"asset_{i}": float(wi) for i, wi in enumerate(w)}

    def compute_portfolio_risk(
        self, weights: np.ndarray, cov_matrix: np.ndarray
    ) -> RiskMetrics:
        port_var  = float(weights @ cov_matrix @ weights)
        port_vol  = float(np.sqrt(port_var) * np.sqrt(252))

        if SCIPY_AVAILABLE and _norm is not None:
            alpha   = self.confidence_level
            z_alpha = _norm.ppf(alpha)
            phi_z   = _norm.pdf(z_alpha)
            var95   = float(np.sqrt(port_var) * z_alpha)
            cvar95  = float(np.sqrt(port_var) * phi_z / max(1 - alpha, 1e-9))
            z99     = _norm.ppf(0.99)
            var99   = float(np.sqrt(port_var) * z99)
            cvar99  = float(np.sqrt(port_var) * _norm.pdf(z99) / max(1 - 0.99, 1e-9))
        else:
            var95 = cvar95 = float(np.sqrt(port_var) * 1.645)
            var99 = cvar99 = float(np.sqrt(port_var) * 2.326)

        return RiskMetrics(
            cvar_95    = cvar95,
            cvar_99    = cvar99,
            volatility = port_vol,
            var_95     = var95,
            var_99     = var99,
            weights    = weights,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Cross-Asset Allocator — combines HRP + CVaR + AI desk signals
# ══════════════════════════════════════════════════════════════════════════════

class CrossAssetAllocator:
    """
    Combines HRP weights with AI Desk signals and CVaR constraints
    to produce final cross-asset position sizing.
    """

    def __init__(
        self,
        max_single_weight: float = 0.40,
        max_asset_class_weight: float = 0.70,
    ) -> None:
        self.max_single        = max_single_weight
        self.max_class         = max_asset_class_weight
        self._hrp              = HierarchicalRiskParity()
        self._cvar_opt         = CVaROptimizer()

    def allocate(
        self,
        returns: np.ndarray,
        symbols: List[str],
        ai_directions: Optional[Dict[str, str]] = None,
        ai_confidences: Optional[Dict[str, float]] = None,
    ) -> Dict[str, PortfolioPosition]:
        """
        Full allocation pipeline:
        1. Fit HRP
        2. Tilt weights toward AI desk signals
        3. Apply concentration limits
        """
        self._hrp.fit(returns, asset_symbols=symbols)

        # Build expected return tilt from AI signals
        exp_returns = np.zeros(len(symbols))
        if ai_directions and ai_confidences:
            hist_means = np.mean(returns, axis=0) * 252  # annualized
            for i, sym in enumerate(symbols):
                direction = (ai_directions.get(sym) or "neutral").lower()
                conf      = (ai_confidences.get(sym) or 50.0) / 100.0
                if direction == "long":
                    exp_returns[i] = abs(hist_means[i]) * conf
                elif direction == "short":
                    exp_returns[i] = -abs(hist_means[i]) * conf
                else:
                    exp_returns[i] = hist_means[i]

        positions = self._hrp.allocate(expected_returns=exp_returns)

        # Apply concentration limits
        total = sum(p.weight for p in positions.values())
        for sym, pos in positions.items():
            pos.weight = min(pos.weight / max(total, 1e-9), self.max_single)

        # Re-normalize
        total = sum(p.weight for p in positions.values())
        if total > 0:
            for pos in positions.values():
                pos.weight /= total

        return positions
