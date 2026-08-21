"""
AI Trading System — Kronos Probabilistic Forecasting Module
Decoder-only causal transformer (encoder with causal mask) for price distributions.
Outputs a Mixture of Gaussians probability distribution over future prices.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = nn = F = None   # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
#  Tokenizer — price quantization
# ══════════════════════════════════════════════════════════════════════════════

SPECIAL_TOKENS = ["<PAD>", "<START>", "<END>", "<MASK>", "<CRYPTO>", "<FOREX>"]
N_SPECIAL = len(SPECIAL_TOKENS)


class Tokenizer:
    """Quantizes price series into discrete token IDs for transformer input."""

    def __init__(self, vocab_size: int = 4096) -> None:
        self.vocab_size  = vocab_size
        self.price_min   = 0.0
        self.price_max   = 1.0
        self._fitted     = False
        self._tok2id: Dict[str, int] = {t: i for i, t in enumerate(SPECIAL_TOKENS)}
        self._id2tok: Dict[int, str] = {i: t for t, i in self._tok2id.items()}
        self._n_price_bins = vocab_size - N_SPECIAL  # bins for prices

    def fit(self, prices: List[float]) -> "Tokenizer":
        if not prices:
            return self
        arr = np.array(prices, dtype=np.float64)
        self.price_min = float(arr.min())
        self.price_max = float(arr.max())
        if self.price_max == self.price_min:
            self.price_max = self.price_min + 1.0
        self._fitted = True
        return self

    def _price_to_bin(self, price: float) -> int:
        """Map price to a bin index in [0, n_price_bins)."""
        norm  = (price - self.price_min) / (self.price_max - self.price_min)
        norm  = max(0.0, min(norm, 1.0 - 1e-9))
        return int(norm * self._n_price_bins) + N_SPECIAL

    def _bin_to_price(self, bin_id: int) -> float:
        idx  = bin_id - N_SPECIAL
        norm = (idx + 0.5) / self._n_price_bins
        return self.price_min + norm * (self.price_max - self.price_min)

    def encode(self, prices: List[float], market_token: str = "<CRYPTO>") -> List[int]:
        if not self._fitted:
            self.fit(prices)
        ids = [self._tok2id["<START>"], self._tok2id.get(market_token, self._tok2id["<CRYPTO>"])]
        for p in prices:
            ids.append(self._price_to_bin(p))
        ids.append(self._tok2id["<END>"])
        return ids

    def decode(self, ids: List[int]) -> List[float]:
        prices: List[float] = []
        recording = False
        for tok in ids:
            if tok == self._tok2id["<START>"]:
                recording = True
                continue
            if tok == self._tok2id["<END>"]:
                break
            if recording and tok >= N_SPECIAL:
                prices.append(self._bin_to_price(tok))
        return prices

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({"price_min": self.price_min, "price_max": self.price_max,
                       "vocab_size": self.vocab_size, "fitted": self._fitted}, f)

    def load(self, path: str) -> "Tokenizer":
        with open(path) as f:
            d = json.load(f)
        self.price_min = d["price_min"]
        self.price_max = d["price_max"]
        self._fitted   = d.get("fitted", True)
        return self


# ══════════════════════════════════════════════════════════════════════════════
#  Probabilistic Output Head — Mixture of Gaussians
# ══════════════════════════════════════════════════════════════════════════════

if TORCH_AVAILABLE:
    class ProbabilisticHead(nn.Module):
        """
        Outputs parameters of a K-component Mixture of Gaussians
        (means μ, standard deviations σ, mixing weights π).
        """

        def __init__(self, d_model: int, n_components: int = 64) -> None:
            super().__init__()
            self.n = n_components
            self.mu    = nn.Linear(d_model, n_components)
            self.log_sigma = nn.Linear(d_model, n_components)
            self.pi    = nn.Linear(d_model, n_components)

        def forward(self, x: "torch.Tensor") -> Dict[str, "torch.Tensor"]:
            # x: [batch, seq, d_model] → use last token
            h = x[:, -1, :]                             # [batch, d_model]
            mu    = self.mu(h)                           # [batch, n]
            sigma = F.softplus(self.log_sigma(h)) + 1e-4 # [batch, n]
            pi    = F.softmax(self.pi(h), dim=-1)        # [batch, n]
            return {"mu": mu, "sigma": sigma, "pi": pi}

    # ── Causal (decoder-only) Transformer ─────────────────────────────────────

    class KronosTransformer(nn.Module):
        """
        Decoder-only transformer for autoregressive price forecasting.
        Implemented via TransformerEncoder + causal attention mask.
        """

        def __init__(
            self,
            vocab_size:   int = 4096,
            d_model:      int = 512,
            n_head:       int = 8,
            n_layer:      int = 6,
            seq_len:      int = 96,
            n_components: int = 64,
            dropout:      float = 0.1,
        ) -> None:
            super().__init__()
            self.d_model = d_model
            self.seq_len = seq_len

            self.tok_embed = nn.Embedding(vocab_size, d_model)
            self.pos_embed = nn.Embedding(seq_len + 4, d_model)   # +4 for special tokens

            enc_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=n_head,
                dim_feedforward=d_model * 4,
                dropout=dropout, batch_first=True, norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_layer,
                                                  norm=nn.LayerNorm(d_model))
            self.head = ProbabilisticHead(d_model, n_components)
            self.drop = nn.Dropout(dropout)

        def _causal_mask(self, seq_len: int, device: "torch.device") -> "torch.Tensor":
            """Upper-triangular mask to enforce autoregressive decoding."""
            mask = torch.triu(torch.ones(seq_len, seq_len, device=device), diagonal=1).bool()
            return mask

        def forward(self, x: "torch.Tensor") -> Dict[str, "torch.Tensor"]:
            """
            x: [batch, seq] token IDs
            Returns MoG parameters dict.
            """
            B, S = x.shape
            S = min(S, self.seq_len + 4)
            x = x[:, :S]

            pos = torch.arange(S, device=x.device).unsqueeze(0).expand(B, -1)
            emb = self.drop(
                self.tok_embed(x) * (self.d_model ** 0.5) + self.pos_embed(pos)
            )

            mask = self._causal_mask(S, x.device)
            out  = self.encoder(emb, mask=mask)            # [B, S, d_model]
            return self.head(out)


# ══════════════════════════════════════════════════════════════════════════════
#  Kronos Probabilistic Model (high-level interface)
# ══════════════════════════════════════════════════════════════════════════════

class KronosProbabilisticModel:
    """
    High-level Kronos wrapper. Handles tokenization, forward pass,
    confidence interval computation, and checkpoint save/load.
    """

    def __init__(
        self,
        vocab_size:   int  = 4096,
        d_model:      int  = 512,
        n_head:       int  = 8,
        n_layer:      int  = 6,
        seq_len:      int  = 96,
        n_components: int  = 64,
        model_path:   str  = "",
    ) -> None:
        self.vocab_size   = vocab_size
        self.seq_len      = seq_len
        self.n_components = n_components
        self.tokenizer    = Tokenizer(vocab_size)
        self._model: Optional[Any] = None

        if TORCH_AVAILABLE:
            self._model = KronosTransformer(
                vocab_size=vocab_size, d_model=d_model,
                n_head=n_head, n_layer=n_layer,
                seq_len=seq_len, n_components=n_components,
            )
            self._model.eval()
            self._load_checkpoint(model_path or os.environ.get("KRONOS_MODEL_PATH", ""))

    def _load_checkpoint(self, path: str) -> None:
        if not path or not Path(path).exists():
            return
        try:
            state_dict = torch.load(path, map_location="cpu")
            self._model.load_state_dict(state_dict, strict=False)
            print(f"[Kronos] Loaded checkpoint from {path}")
        except Exception as e:
            print(f"[Kronos] Could not load checkpoint: {e} — using random weights.")

    def save_checkpoint(self, path: str) -> None:
        if TORCH_AVAILABLE and self._model:
            torch.save(self._model.state_dict(), path)

    def _mog_cdf(self, x: np.ndarray, mu: np.ndarray, sigma: np.ndarray, pi: np.ndarray) -> np.ndarray:
        """Compute CDF of a Mixture of Gaussians at values x."""
        from scipy.special import ndtr  # fast Gaussian CDF
        result = np.zeros_like(x, dtype=np.float64)
        for k in range(len(mu)):
            z = (x - mu[k]) / sigma[k]
            result += pi[k] * ndtr(z)
        return result

    def _mog_quantile(self, q: float, mu: np.ndarray, sigma: np.ndarray, pi: np.ndarray) -> float:
        """Binary-search for the q-th quantile of the MoG."""
        lo = float(mu.min() - 4 * sigma.max())
        hi = float(mu.max() + 4 * sigma.max())
        for _ in range(64):
            mid = (lo + hi) / 2.0
            cdf = self._mog_cdf(np.array([mid]), mu, sigma, pi)[0]
            if cdf < q:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    def forecast(
        self,
        prices: List[float],
        market_type: str = "<CRYPTO>",
    ) -> Dict[str, Any]:
        """
        Generate a full probabilistic price forecast.
        Returns predicted price, confidence intervals, and MoG parameters.
        """
        if len(prices) < 2:
            return {"error": "Need at least 2 price points", "predicted_price": prices[0] if prices else 0.0}

        # Always try statistical fallback first if torch not available
        if not TORCH_AVAILABLE or self._model is None:
            return self._statistical_forecast(prices)

        # ── Tokenize ─────────────────────────────────────────────────────────
        self.tokenizer.fit(prices)
        ids = self.tokenizer.encode(prices, market_type)

        # Pad/truncate to seq_len
        target_len = self.seq_len
        if len(ids) > target_len:
            ids = ids[-target_len:]
        elif len(ids) < target_len:
            ids = [0] * (target_len - len(ids)) + ids

        input_tensor = torch.tensor([ids], dtype=torch.long)

        # ── Forward pass ──────────────────────────────────────────────────────
        with torch.no_grad():
            dist = self._model(input_tensor)

        mu_raw    = dist["mu"][0].numpy()         # [n_components]
        sigma_raw = dist["sigma"][0].numpy()
        pi_raw    = dist["pi"][0].numpy()

        # ── Denormalize to price space ────────────────────────────────────────
        p_range  = self.tokenizer.price_max - self.tokenizer.price_min
        mu       = mu_raw    * p_range / self.n_components + self.tokenizer.price_min
        sigma    = sigma_raw * p_range / self.n_components + 1e-8

        # ── Quantile forecast ─────────────────────────────────────────────────
        try:
            q10  = self._mog_quantile(0.10, mu, sigma, pi_raw)
            q25  = self._mog_quantile(0.25, mu, sigma, pi_raw)
            q50  = self._mog_quantile(0.50, mu, sigma, pi_raw)   # median
            q75  = self._mog_quantile(0.75, mu, sigma, pi_raw)
            q90  = self._mog_quantile(0.90, mu, sigma, pi_raw)
        except Exception:
            # scipy not available → use weighted mean ± sigma
            q50 = float(np.average(mu, weights=pi_raw))
            std = float(np.average(sigma, weights=pi_raw))
            q10, q25, q75, q90 = q50-2*std, q50-std, q50+std, q50+2*std

        return {
            "predicted_price":       q50,
            "median_price":          q50,
            "confidence_intervals":  {
                "p10_p90": {"lower": q10, "upper": q90},
                "p25_p75": {"lower": q25, "upper": q75},
            },
            "distribution": {
                "mu":    mu.tolist(),
                "sigma": sigma.tolist(),
                "pi":    pi_raw.tolist(),
            },
            "price_range": [self.tokenizer.price_min, self.tokenizer.price_max],
            "market_type": market_type,
        }

    def _statistical_forecast(self, prices: List[float]) -> Dict[str, Any]:
        """Pure numpy fallback forecast using historical volatility + mean reversion."""
        arr = np.array(prices, dtype=np.float64)
        returns = np.diff(arr) / arr[:-1]
        returns = returns[np.isfinite(returns)]

        mu_ret   = float(np.mean(returns)) if len(returns) else 0.0
        vol      = float(np.std(returns))  if len(returns) else 0.01
        current  = float(arr[-1])

        # AR(1) mean-reverting step
        predicted = current * (1 + mu_ret * 0.5)

        ci_68_lo = predicted - vol * current
        ci_68_hi = predicted + vol * current
        ci_95_lo = predicted - 1.96 * vol * current
        ci_95_hi = predicted + 1.96 * vol * current

        return {
            "predicted_price":      predicted,
            "median_price":         current,
            "confidence_intervals": {
                "p10_p90": {"lower": ci_95_lo, "upper": ci_95_hi},
                "p25_p75": {"lower": ci_68_lo, "upper": ci_68_hi},
            },
            "volatility": vol,
            "price_range": [float(arr.min()), float(arr.max())],
            "market_type": "statistical_fallback",
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Dual-Market Data Pipeline
# ══════════════════════════════════════════════════════════════════════════════

class KronosDataPipeline:
    """Loads and preprocesses dual-market CSV data for Kronos."""

    def __init__(self, tokenizer: Tokenizer, sequence_length: int = 96) -> None:
        self.tokenizer       = tokenizer
        self.sequence_length = sequence_length

    def load_csv(self, csv_path: str) -> List[Tuple[float, float, float]]:
        """Load OHLCV CSV: timestamp,open,high,low,close,volume"""
        records: List[Tuple[float, float, float]] = []
        path = Path(csv_path)
        if not path.exists():
            return records
        with open(path) as f:
            f.readline()  # header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 6:
                    try:
                        ts, close, volume = float(parts[0]), float(parts[4]), float(parts[5])
                        records.append((close, volume, ts))
                    except ValueError:
                        continue
        return records

    def prepare_tensor(self, prices: List[float]) -> Tuple[Any, Any]:
        if not TORCH_AVAILABLE:
            return np.array(prices), np.array(prices[1:] + [prices[-1]])
        self.tokenizer.fit(prices)
        ids     = self.tokenizer.encode(prices)
        targets = ids[1:] + [self.tokenizer._tok2id["<END>"]]
        if len(ids) > self.sequence_length:
            ids, targets = ids[-self.sequence_length:], targets[-self.sequence_length:]
        else:
            pad = self.sequence_length - len(ids)
            ids     = [0] * pad + ids
            targets = [0] * pad + targets
        return torch.tensor([ids], dtype=torch.long), torch.tensor([targets], dtype=torch.long)


# ══════════════════════════════════════════════════════════════════════════════
#  Async stream processor
# ══════════════════════════════════════════════════════════════════════════════

class DualMarketDataStream:
    """Buffers incoming tick data and triggers Kronos forecasts."""

    def __init__(self, model: KronosProbabilisticModel, buffer_size: int = 192) -> None:
        self.model        = model
        self.buffer_size  = buffer_size
        self._crypto_buf: List[float] = []
        self._forex_buf:  List[float] = []

    async def process_crypto_tick(self, price: float) -> Dict[str, Any]:
        self._crypto_buf.append(price)
        if len(self._crypto_buf) > self.buffer_size:
            self._crypto_buf = self._crypto_buf[-self.buffer_size:]
        if len(self._crypto_buf) >= 8:
            return self.model.forecast(self._crypto_buf, market_type="<CRYPTO>")
        return {"predicted_price": price, "note": "buffering"}

    async def process_forex_tick(self, price: float) -> Dict[str, Any]:
        self._forex_buf.append(price)
        if len(self._forex_buf) > self.buffer_size:
            self._forex_buf = self._forex_buf[-self.buffer_size:]
        if len(self._forex_buf) >= 8:
            return self.model.forecast(self._forex_buf, market_type="<FOREX>")
        return {"predicted_price": price, "note": "buffering"}


__all__ = [
    "Tokenizer", "KronosProbabilisticModel", "KronosDataPipeline",
    "DualMarketDataStream", "ProbabilisticHead", "TORCH_AVAILABLE",
]