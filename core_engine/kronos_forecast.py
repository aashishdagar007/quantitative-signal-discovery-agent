import asyncio
import gzip
import json
import os
import re
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import Dataset, DataLoader
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    nn = None
    F = None
    Dataset = None
    DataLoader = None


class Tokenizer:
    """Tokenizes dual-market CSV data for Kronos model input"""
    
    def __init__(self, vocab_size: int = 10000):
        self.vocab_size = vocab_size
        self.token_to_idx: Dict[str, int] = {}
        self.idx_to_token: Dict[int, str] = {}
        self.price_to_token: Dict[float, int] = {}
        self.idx_to_price: Dict[int, float] = {}
        self.fitted = False
        self.price_min = 0.0
        self.price_max = 1.0
    
    def fit(self, data: List[Tuple[float, float, float]]) -> None:
        """
        Fit tokenizer on OHLCV data.
        data: list of (price, volume, timestamp) tuples
        """
        # Extract all prices
        all_prices = [d[0] for d in data]
        self.price_min = min(all_prices)
        self.price_max = max(all_prices)
        
        # Create price-based tokens
        unique_prices = sorted(set(all_prices))
        
        # Add special tokens
        special_tokens = ["<PAD>", "<START>", "<END>", "<MASK>", "<CRYPTO>", "<FOREX>"]
        
        self.token_to_idx = {token: idx for idx, token in enumerate(special_tokens)}
        self.idx_to_token = {idx: token for token, idx in self.token_to_idx.items()}
        
        next_idx = len(special_tokens)
        
        # Add price tokens (quantized)
        price_quantiles = np.linspace(self.price_min, self.price_max, min(self.vocab_size - len(special_tokens), len(unique_prices) + 1))
        for price in unique_prices:
            if next_idx < self.vocab_size:
                # Find closest quantile
                token_name = f"price_{price:.8f}"
                self.token_to_idx[token_name] = next_idx
                self.idx_to_token[next_idx] = token_name
                next_idx += 1
        
        # Add market type tokens
        for market in ["<CRYPTO>", "<FOREX>"]:
            if next_idx < self.vocab_size:
                self.token_to_idx[market] = next_idx
                self.idx_to_token[next_idx] = market
                next_idx += 1
        
        # Pad token
        if "<PAD>" not in self.token_to_idx:
            self.token_to_idx["<PAD>"] = 0
            self.idx_to_token[0] = "<PAD>"
        
        self.fitted = True
    
    def transform(self, price: float) -> int:
        """Convert price to token index"""
        if not self.fitted:
            return self.token_to_idx.get("<PAD>", 0)
        
        # Quantize price to token space
        if price <= self.price_min:
            return self.token_to_idx.get(f"price_{self.price_min:.8f}", 1)
        if price >= self.price_max:
            return self.token_to_idx.get(f"price_{self.price_max:.8f}", 1)
        
        # Find nearest token
        quantile = (price - self.price_min) / (self.price_max - self.price_min) * (self.vocab_size - 5)
        token_idx = int(quantile) + len(["<PAD>", "<START>", "<END>", "<MASK>", "<CRYPTO>", "<FOREX>"])
        
        if token_idx < self.vocab_size:
            token_name = f"price_{price:.8f}"
            if token_idx in self.idx_to_token:
                return token_idx
        
        return 1  # fallback to <START>
    
    def inverse_transform(self, token_idx: int) -> float:
        """Convert token index back to price"""
        if token_idx < len(["<PAD>", "<START>", "<END>", "<MASK>", "<CRYPTO>", "<FOREX>"]):
            return self.price_min  # fallback
        
        token_name = self.idx_to_token.get(token_idx, "<PAD>")
        if token_name.startswith("price_"):
            try:
                return float(token_name.split("_")[1])
            except:
                return self.price_min
        return self.price_min
    
    def encode(self, prices: List[float], market_type: str = "<CRYPTO>") -> List[int]:
        """Encode a sequence of prices"""
        if not self.fitted:
            return [self.token_to_idx.get("<PAD>", 0)] * len(prices)
        
        encoded = []
        encoded.append(self.token_to_idx.get("<START>", 1))
        
        for price in prices:
            token = self.transform(price)
            encoded.append(token)
        
        encoded.append(self.token_to_idx.get("<END>", 2))
        return encoded
    
    def decode(self, tokens: List[int]) -> List[float]:
        """Decode token sequence to prices"""
        if not self.fitted:
            return [self.price_min] * len(tokens)
        
        prices = []
        start_found = False
        
        for token in tokens:
            if token == self.token_to_idx.get("<START>", 1):
                start_found = True
                continue
            if token == self.token_to_idx.get("<END>", 2):
                break
            if start_found:
                price = self.inverse_transform(token)
                prices.append(price)
        
        return prices


class ProbabilisticHead(nn.Module):
    """Probabilistic output head for price distribution"""
    
    def __init__(self, input_dim: int, num_distribution_points: int = 100):
        super().__init__()
        self.input_dim = input_dim
        self.num_points = num_distribution_points
        
        # Head that outputs parameters of a mixture of Gaussians
        self.mu = nn.Linear(input_dim, num_distribution_points)
        self.sigma = nn.Linear(input_dim, num_distribution_points)
        self.pi = nn.Linear(input_dim, num_distribution_points)
        
        # Softmax for mixing coefficients
        self.softmax = nn.Softmax(dim=-1)
    
    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Forward pass producing price distribution"""
        mu = self.mu(x)
        sigma = F.softplus(self.sigma(x)) + 1e-6  # ensure positive
        pi_logits = self.pi(x)
        mixing_coeffs = self.softmax(pi_logits)
        
        return {
            "mu": mu,
            "sigma": sigma,
            "mixing_coeffs": mixing_coeffs
        }


class KronosDataPipeline:
    """Data pipeline for tokenizing and preprocessing dual-market data"""
    
    def __init__(self, tokenizer: Tokenizer, sequence_length: int = 96):
        self.tokenizer = tokenizer
        self.sequence_length = sequence_length
    
    def load_csv_dual_market(self, csv_path: str) -> List[Tuple[float, float, float]]:
        """Load dual-market CSV data (crypto & forex)"""
        records = []
        
        if not os.path.exists(csv_path):
            return records
        
        with open(csv_path, 'r') as f:
            header = f.readline()  # skip header
            
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split(',')
                if len(parts) >= 6:
                    try:
                        timestamp = float(parts[0])
                        open_price = float(parts[1])
                        high = float(parts[2])
                        low = float(parts[3])
                        close = float(parts[4])
                        volume = float(parts[5])
                        
                        # Use close price as primary signal
                        records.append((close, volume, timestamp))
                    except (ValueError, IndexError):
                        continue
        
        return records
    
    def prepare_sequence(self, data: List[Tuple[float, float, float]]) -> Tuple[torch.Tensor, torch.Tensor]:
        """Prepare tensor sequences for model input"""
        if not data:
            return torch.tensor([]), torch.tensor([])
        
        # Extract prices
        prices = [d[0] for d in data]
        
        # Fit and tokenize
        self.tokenizer.fit(data)
        encoded = self.tokenizer.encode(prices)
        
        # Pad or truncate to sequence length
        if len(encoded) > self.sequence_length:
            encoded = encoded[-self.sequence_length:]
        elif len(encoded) < self.sequence_length:
            padding = [self.tokenizer.token_to_idx.get("<PAD>", 0)] * (self.sequence_length - len(encoded))
            encoded = padding + encoded
        
        # Create target (next price)
        targets = encoded[1:] + [self.tokenizer.token_to_idx.get("<END>", 2)]
        
        # Convert to tensor
        if TORCH_AVAILABLE:
            input_tensor = torch.tensor(encoded, dtype=torch.long).unsqueeze(0)  # batch dim
            target_tensor = torch.tensor(targets, dtype=torch.long).unsqueeze(0)
        else:
            input_tensor = np.array(encoded)
            target_tensor = np.array(targets)
        
        return input_tensor, target_tensor
    
    def create_batch(self, datasets: List[List[Tuple[float, float, float]]]) -> Tuple[torch.Tensor, torch.Tensor]:
        """Create batch from multiple market datasets"""
        all_encoded = []
        all_targets = []
        
        for data in datasets:
            _, target = self.prepare_sequence(data)
            all_encoded.append(_)
            all_targets.append(target)
        
        if TORCH_AVAILABLE and all_encoded:
            batch = torch.nn.utils.rnn.pad_sequence(all_encoded, batch_first=True)
            targets = torch.nn.utils.rnn.pad_sequence(all_targets, batch_first=True)
            return batch, targets
        
        return torch.tensor([]), torch.tensor([])


class KronosProbabilisticModel:
    """Kronos-style decoder-only transformer for probabilistic price forecasting"""
    
    def __init__(self, 
                 vocab_size: int = 10000,
                 d_model: int = 512,
                 n_head: int = 8,
                 n_layer: int = 6,
                 sequence_length: int = 96,
                 num_distribution_points: int = 100):
        
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_head = n_head
        self.n_layer = n_layer
        self.sequence_length = sequence_length
        self.num_distribution_points = num_distribution_points
        
        self.embedding = None
        self.pos_embedding = None
        self.layers = None
        self.norm = None
        self.head = None
        self.tokenizer = Tokenizer(vocab_size)
        
        if TORCH_AVAILABLE:
            self._build_model()
    
    def _build_model(self):
        """Build the Kronos transformer model"""
        # embedding layer
        self.embedding = nn.Embedding(self.vocab_size, self.d_model)
        self.pos_embedding = nn.Embedding(self.sequence_length, self.d_model)
        
        # Transformer decoder layers
        decoder_layer = nn.TransformerDecoderLayer(
            d_model=self.d_model,
            nhead=self.n_head,
            dim_feedforward=self.d_model * 4,
            dropout=0.1,
            batch_first=True
        )
        
        self.layers = nn.TransformerDecoder(decoder_layer, num_layers=self.n_layer)
        self.norm = nn.LayerNorm(self.d_model)
        self.head = ProbabilisticHead(self.d_model, self.num_distribution_points)
    
    def forward(self, 
                src: torch.Tensor, 
                src_mask: Optional[torch.Tensor] = None) -> Dict[str, torch.Tensor]:
        """
        Forward pass through Kronos model
        src: input token indices [batch, seq_len]
        """
        if not TORCH_AVAILABLE or self.embedding is None:
            return {}
        
        seq_len = src.shape[1]
        
        # Embedding
        pos = torch.arange(0, seq_len, device=src.device).unsqueeze(0)
        tok_emb = self.embedding(src) * np.sqrt(self.d_model)
        pos_emb = self.pos_embedding(pos)
        x = tok_emb + pos_emb
        
        # causal mask
        if src_mask is None:
            src_mask = nn.Transformer.generate_square_subsequent_mask(seq_len).to(src.device)
        
        # Transformer decoder
        x = self.layers(x, mask=src_mask)
        x = self.norm(x)
        
        # Probabilistic head
        distribution = self.head(x)
        
        return distribution
    
    def forecast(self, 
                 prices: List[float], 
                 market_type: str = "<CRYPTO>") -> Dict[str, Any]:
        """
        Generate probabilistic price forecast
        Returns price distribution matrix
        """
        if not TORCH_AVAILABLE:
            return self._fallback_forecast(prices, market_type)
        
        # Tokenize input
        self.tokenizer.fit([(p, 0, 0) for p in prices])
        encoded = self.tokenizer.encode(prices, market_type)
        
        # Pad to sequence length
        if len(encoded) < self.sequence_length:
            padding = [self.tokenizer.token_to_idx.get("<PAD>", 0)] * (self.sequence_length - len(encoded))
            encoded = padding + encoded
        
        input_tensor = torch.tensor([encoded], dtype=torch.long)
        
        # Forward pass
        with torch.no_grad():
            distribution = self.forward(input_tensor)
        
        if not distribution:
            return self._fallback_forecast(prices, market_type)
        
        # Parse distribution
        mu = distribution["mu"][0].cpu().numpy()
        sigma = distribution["sigma"][0].cpu().numpy()
        mixing = distribution["mixing_coeffs"][0].cpu().numpy()
        
        # Denormalize prices
        price_range = self.tokenizer.price_max - self.tokenizer.price_min
        mu_denorm = mu * price_range + self.tokenizer.price_min
        sigma_denorm = sigma * price_range
        
        # Compute quantiles
        quantiles = {}
        cdf_total = 0.0
        
        for i in range(self.num_distribution_points):
            cdf_piece = mixing[i] * 0.5  # approximate CDF contribution
            cdf_total += cdf_piece
            
            # Find price at this quantile via interpolation
            q = cdf_total
            if q > 0 and q <= 1.0:
                # Interpolate between adjacent Gaussian components
                pass
        
        # Return key forecast metrics
        forecast_result = {
            "mu": mu_denorm.tolist(),
            "sigma": sigma_denorm.tolist(),
            "mixing_coeffs": mixing.tolist(),
            "price_range": [float(self.tokenizer.price_min), float(self.tokenizer.price_max)],
            "median_price": float((self.tokenizer.price_min + self.tokenizer.price_max) / 2),
            "confidence_intervals": self._compute_ci(mu_denorm, sigma_denorm, mixing),
            "timestamp": None
        }
        
        return forecast_result
    
    def _compute_ci(self, mu, sigma, mixing, levels: List[float] = None) -> Dict:
        """Compute confidence intervals from mixture of Gaussians"""
        if levels is None:
            levels = [0.68, 0.95, 0.99]
        
        ci = {}
        for level in levels:
            alpha = 1.0 - level
            # Find the quantile of the mixture distribution
            # Simplified: use median +- z * sigma
            z_score = {
                0.68: 1.0,
                0.95: 1.96,
                0.99: 2.58
            }.get(level, 1.96)
            
            # Weighted average of sigmas
            avg_sigma = np.average(sigma, weights=mixing + 1e-10)
            
            lower = mu - z_score * avg_sigma
            upper = mu + z_score * avg_sigma
            
            ci[f"_{level}"] = {
                "lower": float(min(lower)),
                "upper": float(max(upper))
            }
        
        return ci
    
    def _fallback_forecast(self, prices: List[float], market_type: str) -> Dict[str, Any]:
        """Fallback forecast when model is not available"""
        if len(prices) < 2:
            return {"error": "Not enough data for forecast"}
        
        prices_arr = np.array(prices)
        current_price = prices_arr[-1]
        
        # Simple historical volatility
        returns = np.diff(prices_arr) / prices_arr[:-1]
        volatility = np.std(returns)
        
        # Simple forecast: price change based on mean reversion
        mean_return = np.mean(returns)
        predicted_change = mean_return * 0.5  # half-mean reversion
        predicted_price = current_price * (1 + predicted_change)
        
        # Confidence interval based on volatility
        vol_scale = volatility * np.sqrt(1)  # 1-period ahead
        
        ci_95_lower = predicted_price - 1.96 * abs(current_price * vol_scale)
        ci_95_upper = predicted_price + 1.96 * abs(current_price * vol_scale)
        
        return {
            "predicted_price": float(predicted_price),
            "median_price": float(current_price),
            "volatility": float(volatility),
            "confidence_intervals": {
                "_0.95": {"lower": float(ci_95_lower), "upper": float(ci_95_upper)}
            },
            "price_range": [float(min(prices)), float(max(prices))],
            "timestamp": None
        }


# --- Data Stream Ingestion ---

class DualMarketDataStream:
    """Real-time data stream ingestion for both crypto and forex"""
    
    def __init__(self, kronos_model: KronosProbabilisticModel):
        self.kronos = kronos_model
        self.crypto_buffer: List[float] = []
        self.forex_buffer: List[float] = []
        self.buffer_size = 192
    
    async def process_crypto_tick(self, price: float, source: str = "binance"):
        """Process incoming crypto tick data"""
        self.crypto_buffer.append(price)
        if len(self.crypto_buffer) > self.buffer_size:
            self.crypto_buffer = self.crypto_buffer[-self.buffer_size:]
        
        # Generate forecast when buffer is full
        if len(self.crypto_buffer) >= self.buffer_size // 2:
            forecast = self.kronos.forecast(
                self.crypto_buffer, 
                market_type="<CRYPTO>"
            )
            forecast["timestamp"] = asyncio.get_event_loop().time()
            return forecast
    
    async def process_forex_tick(self, price: float, symbol: str = "EUR/USD"):
        """Process incoming forex tick data"""
        self.forex_buffer.append(price)
        if len(self.forex_buffer) > self.buffer_size:
            self.forex_buffer = self.forex_buffer[-self.buffer_size:]
        
        # Generate forecast when buffer is full
        if len(self.forex_buffer) >= self.buffer_size // 2:
            forecast = self.kronos.forecast(
                self.forex_buffer,
                market_type="<FOREX>"
            )
            forecast["timestamp"] = asyncio.get_event_loop().time()
            return forecast


# --- Export symbols ---

__all__ = [
    "Tokenizer",
    "KronosProbabilisticModel",
    "KronosDataPipeline",
    "DualMarketDataStream",
    "ProbabilisticHead",
    "TORCH_AVAILABLE"
]