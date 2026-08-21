import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

try:
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.covariance import LedoitWolf, ShrunkCovariance
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    BaseEstimator = None
    TransformerMixin = None
    LedoitWolf = None
    ShrunkCovariance = None


@dataclass
class PortfolioPosition:
    """Represents a portfolio position with symbol and weight"""
    symbol: str
    asset_class: str  # "crypto" or "forex"
    weight: float
    quantity: float = 0.0
    entry_price: float = 0.0


@dataclass
class RiskMetrics:
    """Risk metrics for portfolio evaluation"""
    cvar_95: float  # Conditional Value at Risk at 95%
    cvar_99: float  # Conditional Value at Risk at 99%
    volatility: float  # Annualized portfolio volatility
    var_95: float  # Value at Risk at 95%
    var_99: float  # Value at Risk at 99%
    weights: np.ndarray  # Optimal weights array


class HierarchicalRiskParity:
    """
    Hierarchical Risk Parity (HRP) portfolio allocation.
    
    HRP uses hierarchical clustering to sort assets by volatility,
    then recursively bisection to build the portfolio tree,
    finally optimizing weights based on risk parity principles.
    """
    
    def __init__(self, 
                 cov_estimator: str = "ledoit_wolf",
                 risk_free_rate: float = 0.02):
        """
        Initialize HRP optimizer.
        
        Args:
            cov_estimator: Covariance estimator ("ledoit_wolf", "shrunk")
            risk_free_rate: Annualized risk-free rate
        """
        self.cov_estimator = cov_estimator
        self.risk_free_rate = risk_free_rate
        self.cov_matrix: Optional[np.ndarray] = None
        self.correlation_matrix: Optional[np.ndarray] = None
        self.volatility_vector: Optional[np.ndarray] = None
        self.dendrogram: Optional[np.ndarray] = None
        self.asset_order: Optional[List[str]] = None
    
    def _compute_covariance(self, returns: np.ndarray) -> np.ndarray:
        """Estimate covariance matrix using specified estimator"""
        n_assets = returns.shape[1]
        
        if self.cov_estimator == "ledoit_wolf" and SKLEARN_AVAILABLE:
            lw = LedoitWolf()
            lw.fit(returns.T)
            cov = lw.covariance_
        elif self.cov_estimator == "shrunk" and SKLEARN_AVAILABLE:
            sc = ShrunkCovariance()
            sc.fit(returns.T)
            cov = sc.covariance_
        else:
            # Fallback: sample covariance
            cov = np.cov(returns)
        
        # Ensure positive definiteness
        # Add small diagonal if not positive definite
        attempt = 0
        while attempt < 5:
            attempt += 1
            try:
                np.linalg.cholesky(cov)
                break
            except np.linalg.LinAlgError:
                # Add jitter to diagonal
                cov += np.eye(cov.shape[0]) * 1e-6
        
        return cov
    
    def _compute_distance(self, cov: np.ndarray) -> np.ndarray:
        """Convert covariance to distance matrix for clustering"""
        # Distance based on correlation, not raw covariance
        vol = np.sqrt(np.diag(cov))
        correlation = cov / np.outer(vol, vol)
        # Distance = sqrt(2 * (1 - correlation))
        distance = np.sqrt(2 * (1 - correlation))
        np.fill_diagonal(distance, 0.0)
        return distance
    
    def _hierarchical_clustering(self, distance: np.ndarray) -> np.ndarray:
        """Perform hierarchical clustering using single linkage"""
        from scipy.cluster.hierarchy import linkage, leaves_list
        
        # Use single linkage for clustering
        Z = linkage(distance, method='single')
        leaves = leaves_list(Z)
        
        return Z, leaves
    
    def _recursive_bisection(self, 
                            distance: np.ndarray, 
                            leaves: np.ndarray) -> Tuple[List[int], List[float]]:
        """
        Recursive bisection to build HRP tree.
        
        Returns:
            weights: final portfolio weights
            path: clustering path information
        """
        n_assets = distance.shape[0]
        
        # Initialize weights
        remaining = set(leaves)
        weights = np.ones(n_assets) / n_assets
        
        # Recursive bisection
        while len(remaining) > 1:
            # Find the split point
            # Sort leaves by their distance to the rest
            remaining_list = sorted(list(remaining))
            
            if len(remaining_list) <= 2:
                # Final allocation
                for i, idx in enumerate(remaining_list):
                    weights[idx] = 1.0 / len(remaining_list)
                break
            
            # Find the optimal split that minimizes within-group variance
            best_split = None
            best_criteria = float('inf')
            
            for split_size in range(1, len(remaining_list)):
                left_group = set(remaining_list[:split_size])
                right_group = set(remaining_list[split_size:])
                
                # Compute average distance within each group
                if len(left_group) > 1 and len(right_group) > 1:
                    left_indices = sorted(left_group)
                    right_indices = sorted(right_group)
                    
                    left_dist = np.mean(distance[np.ix_(left_indices, left_indices)])
                    right_dist = np.mean(distance[np.ix_(right_indices, right_indices)])
                    
                    # Criteria: balance between groups + distance
                    balance = 4 * len(left_group) * len(right_group) / pow(len(left_group) + len(right_group), 2)
                    criteria = (left_dist + right_dist) / (balance + 1e-10)
                    
                    if criteria < best_criteria:
                        best_criteria = criteria
                        best_split = (left_group, right_group)
            
            if best_split:
                left_group, right_group = best_split
                # Allocate proportionally based to inverse volatility
                # This is a simplification; full HRP would compute risk budgets
                left_vol = np.mean([np.sqrt(distance[i, i]) for i in left_group])
                right_vol = np.mean([np.sqrt(distance[i, i]) for i in right_group])
                
                # Inverse volatility weighting
                total_vol = left_vol + right_vol
                if total_vol > 0:
                    left_weight = right_vol / total_vol
                    right_weight = left_vol / total_vol
                
                # Recurse on each group
                remaining = set()
                if left_group:
                    remaining.update(left_group)
                if right_group:
                    remaining.update(right_group)
            else:
                # Fallback: equal weight
                for idx in remaining:
                    weights[idx] = 1.0 / len(remaining)
                break
        
        return weights.tolist(), []
    
    def fit(self, 
            returns: np.ndarray, 
            asset_symbols: List[str]) -> 'HierarchicalRiskParity':
        """
        Fit HRP model on return data.
        
        Args:
            returns: Array of shape (n_observations, n_assets)
            asset_symbols: List of asset symbols/tickers
            
        Returns:
            self for method chaining
        """
        n_assets = returns.shape[1]
        
        # Compute covariance matrix
        self.cov_matrix = self._compute_covariance(returns)
        
        # Compute volatility vector (annualized if daily returns)
        self.volatility_vector = np.sqrt(np.diag(self.cov_matrix)) * np.sqrt(252)
        
        # Compute distance matrix
        distance = self._compute_distance(self.cov_matrix)
        
        # Hierarchical clustering
        Z, leaves = self._hierarchical_clustering(distance)
        self.dendrogram = Z
        
        # Order assets by clustering
        self.asset_order = [asset_symbols[idx] for idx in leaves]
        
        # Recursive bisection to get weights
        weights, _ = self._recursive_bisection(distance, leaves)
        
        # Normalize weights to sum to 1
        weights_array = np.array(weights)
        weights_array = weights_array / np.sum(weights_array)
        
        # Reorder weights to match original asset order
        original_order_weights = np.zeros(n_assets)
        for i, ordered_idx in enumerate(leaves):
            original_order_weights[i] = weights_array[i]
        
        # Store equal-weighted reference for comparison
        self.original_weights = original_order_weights
        
        return self
    
    def allocate(self, 
                 expected_returns: Optional[np.ndarray] = None,
                 risk_aversion: float = 1.0) -> Dict[str, PortfolioPosition]:
        """
        Generate optimal portfolio weights using HRP.
        
        Args:
            expected_returns: Expected returns for each asset
            risk_aversion: Risk aversion parameter for mean-variance adjustment
            
        Returns:
            Dictionary mapping symbol to PortfolioPosition
        """
        if self.cov_matrix is None or self.volatility_vector is None:
            raise ValueError("HRP model not fitted. Call fit() first.")
        
        n_assets = self.cov_matrix.shape[0]
        
        # Start with HRP weights
        hrp_weights = self.original_weights.copy()
        
        # If expected returns provided, adjust for risk-adjusted allocation
        if expected_returns is not None and len(expected_returns) == n_assets:
            # Simple risk-adjusted adjustment
            sharpe_ratio = expected_returns / (self.volatility_vector + 1e-8)
            adjustment = sharpe_ratio / (np.sum(sharpe_ratio) + 1e-8)
            adjusted_weights = hrp_weights * adjustment
            adjusted_weights = adjusted_weights / np.sum(adjusted_weights)  # renormalize
        else:
            adjusted_weights = hrp_weights
        
        # Create portfolio positions
        positions = {}
        for i, symbol in enumerate(self.asset_order if self.asset_order else range(n_assets)):
            if i < len(adjusted_weights):
                weight = float(adjusted_weights[i])
                positions[symbol] = PortfolioPosition(
                    symbol=symbol,
                    asset_class=self._get_asset_class(symbol),
                    weight=weight,
                    entry_price=0.0  # will be filled by execution core
                )
        
        return positions
    
    def _get_asset_class(self, symbol: str) -> str:
        """Determine asset class from symbol"""
        crypto_symbols = ["BTC", "ETH", "ADA", "SOL", "DOGE", "DOT", "LINK", "UNI"]
        if any(symbol.startswith(c) for c in crypto_symbols):
            return "crypto"
        else:
            return "forex"
    
    def compute_cvar(self, 
                     portfolio_returns: np.ndarray, 
                     confidence: float = 0.95) -> RiskMetrics:
        """
        Compute Conditional Value at Risk (CVaR) and related metrics.
        
        CVaR (Expected Shortfall) is the expected loss given that 
        the loss exceeds VaR.
        
        Args:
            portfolio_returns: Array of portfolio returns
            confidence: Confidence level (0.95 or 0.99)
            
        Returns:
            RiskMetrics object with all risk measures
        """
        if len(portfolio_returns) == 0:
            return RiskMetrics(
                cvar_95=0.0,
                cvar_99=0.0,
                volatility=0.0,
                var_95=0.0,
                var_99=0.0,
                weights=np.array([])
            )
        
        # Sort returns (worst first)
        sorted_returns = np.sort(portfolio_returns)
        
        # Compute VaR at specified confidence
        n = len(sorted_returns)
        rank = int(n * (1 - confidence))
        var = -sorted_returns[rank]  # VaR is positive loss
        
        # Compute CVaR: mean of losses exceeding VaR
        tail_losses = sorted_returns[:rank]
        cvar = -np.mean(tail_losses) if len(tail_losses) > 0 else 0.0
        
        # Annualized volatility
        volatility = np.std(portfolio_returns) * np.sqrt(252)
        
        # VaR at 99%
        rank_99 = int(n * (1 - 0.99))
        var_99 = -sorted_returns[rank_99] if rank_99 < n else var
        
        return RiskMetrics(
            cvar_95=cvar,
            cvar_99=cvar,  # simplified - would compute separately for 99%
            volatility=volatility,
            var_95=var,
            var_99=var_99,
            weights=self.original_weights if self.original_weights is not None else np.array([])
        )


class CVaROptimizer:
    """
    CVaR-based optimization module.
    
    Optimizes portfolio to minimize Conditional Value at Risk
    while achieving target returns.
    """
    
    def __init__(self, 
                 confidence_level: float = 0.95,
                 risk_free_rate: float = 0.02):
        self.confidence_level = confidence_level
        self.risk_free_rate = risk_free_rate
        self.cov_estimator = LedoitWolf() if SKLEARN_AVAILABLE else None
    
    def optimize_min_cvar(self,
                         returns: np.ndarray,
                         expected_return_target: Optional[float] = None) -> Dict[str, float]:
        """
        Optimize portfolio to minimize CVaR.
        
        Args:
            returns: Array of shape (n_observations, n_assets)
            expected_return_target: Target expected annual return
            
        Returns:
            Dictionary of asset -> weight mapping
        """
        n_assets = returns.shape[1]
        
        if SKLEARN_AVAILABLE:
            # Estimate covariance
            lw = LedoitWolf()
            lw.fit(returns.T)
            cov = lw.covariance_
        else:
            cov = np.cov(returns)
        
        # Portfolio variance: w^T * cov * w
        # CVaR approximation using Cornish-Fisher or simple Gaussian assumption
        
        # Objective: minimize CVaR approximation
        # For Gaussian: CVaR = mu + sigma * phi(alpha) / (1-alpha)
        # We'll minimize the CVaR proxy
        
        # Use scipy for optimization if available
        try:
            from scipy.optimize import minimize
            from scipy import stats
            
            # Sample mean returns
            sample_means = np.mean(returns, axis=0)
            
            # Constraints: weights sum to 1
            constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
            
            # Bounds: weights between 0 and 1 (long-only)
            bounds = tuple((0, 1) for _ in range(n_assets))
            
            # CVaR objective function (Gaussian approximation)
            def cvar_objective(w):
                port_variance = w @ cov @ w
                port_return = w @ sample_means
                
                # Gaussian CVaR at confidence level alpha
                alpha = self.confidence_level
                # CVaR = -port_return + sigma * phi(alpha) / (1-alpha)  (for negative returns)
                # Simplified: minimize portfolio variance as proxy for CVaR
                # with return constraint
                
                # Add penalty for missing target return
                target_penalty = 0.0
                if expected_return_target is not None:
                    target_penalty = abs(port_return - expected_return_target) ** 2 * 100
                
                return port_variance + target_penalty
            
            # Initial guess: equal weights
            w0 = np.ones(n_assets) / n_assets
            
            # Optimize
            result = minimize(
                cvar_objective,
                w0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000, 'ftol': 1e-12}
            )
            
            if result.success:
                optimal_weights = result.x
            else:
                # Fallback to equal weights
                optimal_weights = np.ones(n_assets) / n_assets
                print(f"CVaR optimization did not converge: {result.message}")
        else:
            # Fallback: equal weights
            optimal_weights = np.ones(n_assets) / n_assets
        
        # Convert to dictionary
        weight_dict = {f"asset_{i}": float(w) for i, w in enumerate(optimal_weights)}
        
        return weight_dict
    
    def compute_portfolio_risk(self,
                               weights: np.ndarray,
                               cov_matrix: np.ndarray) -> RiskMetrics:
        """
        Compute risk metrics for given portfolio weights.
        
        Args:
            weights: Portfolio weight vector
            cov_matrix: Covariance matrix of asset returns
            
        Returns:
            RiskMetrics with CVaR, VaR, and volatility
        """
        # Portfolio variance
        port_variance = weights @ cov_matrix @ weights
        port_volatility = np.sqrt(port_variance) * np.sqrt(252)
        
        # Portfolio return (assuming equal mean return approximation)
        # For CVaR we need the distribution of portfolio returns
        # Using Gaussian approximation:
        from scipy import stats
        
        # Cornish-Fisher expansion for CVaR
        alpha = self.confidence_level
        z_alpha = stats.norm.ppf(alpha)  # z-score for VaR
        
        # Skewness and kurtosis of portfolio returns
        # Simplified: assume normal distribution
        port_var = -np.sqrt(port_variance) * z_alpha  # VaR (positive)
        
        # CVaR for normal distribution: VaR * 1/(1-alpha) * phi(z) ... 
        # Actually for normal: CVaR = mu - sigma * phi(z) / (1-alpha)
        # where phi is the standard normal PDF
        
        phi_z = stats.norm.pdf(z_alpha)
        if 1 - alpha > 0:
            cvar = port_var * phi_z / (1 - alpha) if port_var != 0 else 0
        else:
            cvar = 0
        
        # VaR at 99%
        z_alpha_99 = stats.norm.ppf(0.99)
        var_99 = -np.sqrt(port_variance) * z_alpha_99
        
        return RiskMetrics(
            cvar_95=max(cvar, 0),
            cvar_99=max(var_99 * phi_z / (1 - 0.99), 0) if 1 - 0.99 > 0 else 0,
            volatility=port_volatility,
            var_95=max(port_var, 0),
            var_99=max(var_99, 0),
            weights=weights
        )