"""
AI Trading System — LangGraph Multi-Agent AI Research Desk
Pipeline: Fundamentals → Sentiment → Technical → Debaters → Risk Manager
Each agent produces a signed directional consensus using ED25519 cryptography.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)
from dotenv import load_dotenv

# Load env
for _p in ["infrastructure/.env", ".env", "../infrastructure/.env"]:
    if os.path.exists(_p):
        load_dotenv(_p)
        break

from core_engine.kronos_forecast import KronosProbabilisticModel

# ── LangChain imports ─────────────────────────────────────────────────────────
try:
    from langchain_core.messages import SystemMessage
    from langchain_openai import ChatOpenAI
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    ChatOpenAI = None

# ── LangGraph imports ─────────────────────────────────────────────────────────
try:
    from langgraph.graph import END, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    StateGraph = None
    END = "__end__"


# ══════════════════════════════════════════════════════════════════════════════
#  Cryptographic Key Manager (ED25519, persistent PEM files)
# ══════════════════════════════════════════════════════════════════════════════

KEY_DIR = Path(os.environ.get("KEY_DIR", "./keys"))


class KeyManager:
    """
    Manages ED25519 key pairs for agent consensus signing.
    Keys are persisted to PEM files so they survive process restarts.
    """

    def __init__(self, key_dir: Path = KEY_DIR) -> None:
        self.key_dir = key_dir
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self._private_key: Ed25519PrivateKey = self._load_or_generate_key()
        self._public_key:  Ed25519PublicKey  = self._private_key.public_key()

    # ── Key persistence ───────────────────────────────────────────────────────

    def _priv_path(self) -> Path:
        return self.key_dir / "consensus_private.pem"

    def _pub_path(self) -> Path:
        return self.key_dir / "consensus_public.pem"

    def _load_or_generate_key(self) -> Ed25519PrivateKey:
        if self._priv_path().exists():
            pem = self._priv_path().read_bytes()
            key = load_pem_private_key(pem, password=None)
            return key
        # Generate new key pair
        priv = Ed25519PrivateKey.generate()
        priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        pub_pem  = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        self._priv_path().write_bytes(priv_pem)
        self._pub_path().write_bytes(pub_pem)
        return priv

    # ── Signing / verification ─────────────────────────────────────────────────

    def sign_consensus(self, consensus: str) -> str:
        """Sign consensus text with ED25519 private key. Returns hex signature."""
        sig = self._private_key.sign(consensus.encode("utf-8"))
        return sig.hex()

    def verify_consensus(self, consensus: str, signature_hex: str) -> bool:
        """Verify consensus signature with the public key."""
        try:
            self._public_key.verify(bytes.fromhex(signature_hex), consensus.encode("utf-8"))
            return True
        except Exception:
            return False

    def public_key_pem(self) -> str:
        return self._public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


# ══════════════════════════════════════════════════════════════════════════════
#  Shared Agent State (LangGraph TypedDict)
# ══════════════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    messages:          List[Dict[str, Any]]
    market_data:       Dict[str, Any]
    consensus:         Optional[str]
    signature:         Optional[str]
    risk_score:        float
    direction:         Optional[str]   # "long" | "short" | "neutral"
    confidence:        float
    position_size_pct: float
    kronos_forecast:   Optional[Dict[str, Any]]


# ══════════════════════════════════════════════════════════════════════════════
#  LLM helper
# ══════════════════════════════════════════════════════════════════════════════

def _make_llm(temperature: float = 0.3) -> Optional[Any]:
    if not LANGCHAIN_AVAILABLE:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o")
    if not api_key or api_key.startswith("your_"):
        return None
    return ChatOpenAI(model=model, temperature=temperature, api_key=api_key)


def _extract_direction_confidence(text: str) -> tuple[str, float]:
    """Parse direction and confidence from LLM output text."""
    direction = "neutral"
    confidence = 50.0
    low = text.lower()

    if "strong long" in low or "strongly bullish" in low:
        direction, confidence = "long", 75.0
    elif "strong short" in low or "strongly bearish" in low:
        direction, confidence = "short", 75.0
    elif "long" in low or "bullish" in low:
        direction = "long"
    elif "short" in low or "bearish" in low:
        direction = "short"

    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    if m:
        confidence = min(float(m.group(1)), 100.0)

    return direction, confidence


def _llm_or_heuristic(llm, prompt: str, fallback_fn) -> str:
    """Invoke LLM if available, otherwise call fallback heuristic."""
    if llm is None:
        return fallback_fn()
    try:
        resp = llm.invoke([SystemMessage(content=prompt)])
        return resp.content
    except Exception:
        return fallback_fn()


# ══════════════════════════════════════════════════════════════════════════════
#  Specialized Agents
# ══════════════════════════════════════════════════════════════════════════════

class ForecastAgent:
    """Probabilistic price forecasting agent powered by Kronos transformer model."""

    def __init__(self, key_manager: KeyManager) -> None:
        self.model = KronosProbabilisticModel()
        self.key_manager = key_manager

    def forecast(self, state: AgentState) -> AgentState:
        prices = state["market_data"].get("prices", [])
        symbol = state["market_data"].get("symbol", "EUR/USD")
        market_type = "<FOREX>" if any(curr in symbol for curr in ["EUR", "USD", "GBP", "JPY"]) else "<CRYPTO>"

        if len(prices) >= 2:
            fc = self.model.forecast(prices, market_type=market_type)
        else:
            current = prices[0] if prices else 1.0
            fc = {
                "predicted_price": current,
                "median_price": current,
                "confidence_intervals": {
                    "p10_p90": {"lower": current * 0.98, "upper": current * 1.02},
                    "p25_p75": {"lower": current * 0.99, "upper": current * 1.01},
                },
                "market_type": "fallback",
            }

        current_price = prices[-1] if prices else 1.0
        pred_price = float(fc.get("predicted_price", current_price))
        change_pct = (pred_price - current_price) / max(current_price, 1e-6) * 100.0

        direction = "long" if change_pct > 0.05 else "short" if change_pct < -0.05 else "neutral"
        confidence = min(50.0 + min(abs(change_pct) * 20.0, 40.0), 90.0)

        msg_content = (
            f"Kronos Probabilistic Forecast ({symbol}): "
            f"Current={current_price:.5f} -> Predicted={pred_price:.5f} ({change_pct:+.2f}%). "
            f"Directional bias: {direction.upper()} (confidence {confidence:.1f}%)."
        )

        return {
            **state,
            "kronos_forecast": fc,
            "messages": state["messages"] + [
                {
                    "agent": "kronos_forecast",
                    "role": "assessment",
                    "content": msg_content,
                    "direction": direction,
                    "confidence": confidence,
                    "forecast": fc,
                }
            ],
        }


class FundamentalsAgent:
    """Macroeconomic and on-chain fundamentals analyst."""

    def __init__(self, key_manager: KeyManager) -> None:
        self.llm = _make_llm(0.3)
        self.key_manager = key_manager

    def analyze(self, state: AgentState) -> AgentState:
        symbol   = state["market_data"].get("symbol", "EUR/USD")
        timeframe = state["market_data"].get("timeframe", "1h")

        prompt = f"""You are a senior macro analyst. Analyze the fundamentals for {symbol} on {timeframe} timeframe.
Consider:
- For forex: interest rate differentials, CPI, PMI, central bank stance
- For crypto: on-chain activity, hash rate, exchange reserves, institutional flows
- Risk sentiment: VIX, DXY, global liquidity

Provide: (1) directional bias [LONG/SHORT/NEUTRAL], (2) confidence 0-100%, (3) 3-sentence rationale."""

        def _fallback():
            prices = state["market_data"].get("prices", [])
            if len(prices) >= 2:
                trend = "LONG" if prices[-1] > prices[0] else "SHORT"
                return f"Heuristic fundamental analysis: {trend} based on price trend. Confidence: 55%."
            return "Insufficient data. Direction: NEUTRAL. Confidence: 50%."

        text = _llm_or_heuristic(self.llm, prompt, _fallback)
        direction, confidence = _extract_direction_confidence(text)

        return {
            **state,
            "messages": state["messages"] + [
                {"agent": "fundamentals", "role": "assessment", "content": text,
                 "direction": direction, "confidence": confidence}
            ],
        }


class SentimentAgent:
    """Market sentiment from news, social, and on-chain signals."""

    def __init__(self, key_manager: KeyManager) -> None:
        self.llm = _make_llm(0.4)
        self.key_manager = key_manager

    def analyze(self, state: AgentState) -> AgentState:
        symbol = state["market_data"].get("symbol", "EUR/USD")

        prompt = f"""You are a sentiment analyst. Analyze current market sentiment for {symbol}.
Sources to consider:
- Social sentiment (Twitter/X, Reddit, Telegram)
- News headlines from last 24h
- Fear & Greed Index
- Whale wallet activity and exchange flows

Provide: (1) sentiment direction [LONG/SHORT/NEUTRAL], (2) confidence 0-100%, (3) key sentiment drivers."""

        def _fallback():
            return "Sentiment data unavailable. Direction: NEUTRAL. Confidence: 50%."

        text = _llm_or_heuristic(self.llm, prompt, _fallback)
        direction, confidence = _extract_direction_confidence(text)

        return {
            **state,
            "messages": state["messages"] + [
                {"agent": "sentiment", "role": "assessment", "content": text,
                 "direction": direction, "confidence": confidence}
            ],
        }


class TechnicalAgent:
    """Technical analysis with indicators computed from live price data."""

    def __init__(self, key_manager: KeyManager) -> None:
        self.llm = _make_llm(0.2)
        self.key_manager = key_manager

    @staticmethod
    def _compute_rsi(prices: List[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(np.array(prices[-period - 1:]))
        gains  = deltas[deltas > 0].mean() if (deltas > 0).any() else 1e-9
        losses = -deltas[deltas < 0].mean() if (deltas < 0).any() else 1e-9
        rs  = gains / losses
        return float(100.0 - 100.0 / (1.0 + rs))

    @staticmethod
    def _compute_ema(prices: List[float], period: int = 20) -> float:
        if not prices:
            return 0.0
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = k * p + (1 - k) * ema
        return ema

    def analyze(self, state: AgentState) -> AgentState:
        symbol = state["market_data"].get("symbol", "EUR/USD")
        prices = state["market_data"].get("prices", [])

        # Compute indicators
        current  = prices[-1] if prices else 0.0
        sma20    = np.mean(prices[-20:]) if len(prices) >= 20 else current
        ema14    = self._compute_ema(prices[-50:], 14) if len(prices) >= 14 else current
        rsi      = self._compute_rsi(prices)
        vol      = float(np.std(np.diff(prices) / np.array(prices[:-1]) if len(prices) > 1 else [0]))

        prompt = f"""You are a technical analyst. Analyze {symbol}:
- Current price: {current:.5f}
- 20-bar SMA: {sma20:.5f} (price is {'above' if current > sma20 else 'below'} SMA)
- 14-bar EMA: {ema14:.5f}
- RSI(14): {rsi:.1f} ({'overbought' if rsi > 70 else 'oversold' if rsi < 30 else 'neutral'})
- Realized volatility: {vol:.5f}

Provide: (1) directional bias [LONG/SHORT/NEUTRAL], (2) confidence 0-100%, (3) key technical levels."""

        def _fallback():
            if len(prices) < 2:
                return "NEUTRAL. Confidence: 50%."
            direction = "LONG" if current > sma20 and rsi < 70 else "SHORT" if current < sma20 and rsi > 30 else "NEUTRAL"
            conf = 60.0 if rsi < 30 or rsi > 70 else 52.0
            return f"Technical: {direction}. RSI={rsi:.1f}, Price vs SMA={current - sma20:.5f}. Confidence: {conf}%."

        text = _llm_or_heuristic(self.llm, prompt, _fallback)
        direction, confidence = _extract_direction_confidence(text)

        return {
            **state,
            "messages": state["messages"] + [
                {"agent": "technical", "role": "assessment", "content": text,
                 "direction": direction, "confidence": confidence,
                 "indicators": {"rsi": rsi, "sma20": sma20, "ema14": ema14}}
            ],
        }


class DebatersAgent:
    """Bull/bear debate to stress-test consensus and refine confidence."""

    def __init__(self, key_manager: KeyManager) -> None:
        self.bull_llm = _make_llm(0.7)   # higher temp for bull
        self.bear_llm = _make_llm(0.7)   # higher temp for bear
        self.key_manager = key_manager

    def deliberate(self, state: AgentState) -> AgentState:
        assessments = [m["content"] for m in state["messages"] if m.get("role") == "assessment"]
        summary = "\n\n".join(assessments) if assessments else "No prior assessments."

        def _bull_fallback():
            return "Bull case: Fundamentals and momentum support a long position. Confidence: 65%."

        def _bear_fallback():
            return "Bear case: Risk-off environment and overbought conditions favor shorts. Confidence: 60%."

        bull_prompt = f"""You are an aggressive bull debater. Given these analyst assessments:

{summary}

Make the strongest LONG case. Challenge bear arguments. End with: direction=LONG, confidence=XX%."""

        bear_prompt = f"""You are a contrarian bear debater. Given these analyst assessments:

{summary}

Make the strongest SHORT case. Challenge bull arguments. End with: direction=SHORT, confidence=XX%."""

        bull_text = _llm_or_heuristic(self.bull_llm, bull_prompt, _bull_fallback)
        bear_text = _llm_or_heuristic(self.bear_llm, bear_prompt, _bear_fallback)

        # Resolve: average confidence from previous assessments
        all_confidences = [m.get("confidence", 50.0) for m in state["messages"] if "confidence" in m]
        avg_conf = float(np.mean(all_confidences)) if all_confidences else 50.0

        # Direction from plurality vote
        votes = [m.get("direction", "neutral") for m in state["messages"] if "direction" in m]
        long_votes  = votes.count("long")
        short_votes = votes.count("short")
        if long_votes > short_votes:
            final_direction = "long"
        elif short_votes > long_votes:
            final_direction = "short"
        else:
            final_direction = "neutral"

        # Adjust confidence based on consensus strength
        consensus_strength = abs(long_votes - short_votes) / max(len(votes), 1)
        final_confidence = min(avg_conf * (0.8 + 0.4 * consensus_strength), 95.0)

        fc = state.get("kronos_forecast")
        fc_line = ""
        if fc and "predicted_price" in fc:
            fc_line = f"\nKronos Forecast: Predicted={fc['predicted_price']:.5f} ({fc.get('market_type', 'probabilistic')})\n"

        consensus_text = (
            f"DEBATE CONSENSUS: {final_direction.upper()}\n"
            f"Confidence: {final_confidence:.1f}%\n"
            f"{fc_line}\n"
            f"Bull argument:\n{bull_text}\n\n"
            f"Bear argument:\n{bear_text}"
        )

        # Cryptographically sign the consensus
        signature = self.key_manager.sign_consensus(consensus_text)

        return {
            **state,
            "consensus":  consensus_text,
            "signature":  signature,
            "direction":  final_direction,
            "confidence": final_confidence,
            "messages": state["messages"] + [
                {"agent": "debaters", "role": "consensus", "content": consensus_text,
                 "direction": final_direction, "confidence": final_confidence}
            ],
        }


class RiskManagerAgent:
    """CVaR/VaR risk assessment and Kelly-adjusted position sizing."""

    def __init__(self, key_manager: KeyManager) -> None:
        self.llm = _make_llm(0.1)
        self.key_manager = key_manager
        self.max_risk_per_trade = 0.02   # 2% of capital
        self.cvar_confidence    = 0.95

    def assess(self, state: AgentState) -> AgentState:
        direction  = state.get("direction", "neutral")
        confidence = state.get("confidence", 50.0)
        prices     = state["market_data"].get("prices", [])

        # ── Compute CVaR ──────────────────────────────────────────────────────
        if len(prices) > 1:
            returns = np.diff(prices) / np.array(prices[:-1])
            returns = returns[np.isfinite(returns)]
        else:
            returns = np.array([-0.01, 0.01])

        sorted_returns = np.sort(returns)
        n = len(sorted_returns)
        var_idx = max(int(n * (1 - self.cvar_confidence)), 0)
        var_95  = -float(sorted_returns[var_idx]) if var_idx < n else 0.01
        cvar_95 = float(-np.mean(sorted_returns[:max(var_idx, 1)]))
        volatility = float(np.std(returns) * np.sqrt(252))

        # ── Kelly position sizing ─────────────────────────────────────────────
        if direction != "neutral" and confidence > 50.0:
            win_prob = confidence / 100.0
            avg_win  = max(abs(float(np.mean(returns[returns > 0]))) if (returns > 0).any() else 0.005, 1e-6)
            avg_loss = max(abs(float(np.mean(returns[returns < 0]))) if (returns < 0).any() else 0.005, 1e-6)
            kelly    = win_prob - (1 - win_prob) / (avg_win / avg_loss)
            kelly    = max(kelly, 0.0)
            # Half-Kelly for safety, capped at max_risk
            pos_pct  = min(kelly * 0.5 * self.max_risk_per_trade / max(cvar_95, 0.001), 0.10)
        else:
            pos_pct = 0.0

        risk_report = (
            f"RISK ASSESSMENT\n"
            f"Direction:          {direction.upper()}\n"
            f"Confidence:         {confidence:.1f}%\n"
            f"Annualized Vol:     {volatility:.2%}\n"
            f"VaR(95%):           {var_95:.4f}\n"
            f"CVaR(95%):          {cvar_95:.4f}\n"
            f"Position Size:      {pos_pct:.2%} of capital\n"
            f"Max Allowed Risk:   {self.max_risk_per_trade:.1%}"
        )

        return {
            **state,
            "risk_score":        cvar_95,
            "position_size_pct": pos_pct,
            "messages": state["messages"] + [
                {"agent": "risk_manager", "role": "risk_report", "content": risk_report,
                 "cvar_95": cvar_95, "var_95": var_95, "position_size_pct": pos_pct}
            ],
        }


# ══════════════════════════════════════════════════════════════════════════════
#  LangGraph Pipeline Assembly
# ══════════════════════════════════════════════════════════════════════════════

def create_ai_desk():
    """Build and compile the LangGraph multi-agent workflow."""
    key_manager  = KeyManager()
    forecast     = ForecastAgent(key_manager)
    fundamentals = FundamentalsAgent(key_manager)
    sentiment    = SentimentAgent(key_manager)
    technical    = TechnicalAgent(key_manager)
    debaters     = DebatersAgent(key_manager)
    risk_manager = RiskManagerAgent(key_manager)

    if not LANGGRAPH_AVAILABLE:
        # Return a simple sequential runner when LangGraph isn't installed
        class FallbackPipeline:
            def invoke(self, state: AgentState) -> AgentState:
                state = forecast.forecast(state)
                state = fundamentals.analyze(state)
                state = sentiment.analyze(state)
                state = technical.analyze(state)
                state = debaters.deliberate(state)
                state = risk_manager.assess(state)
                return state
        return FallbackPipeline(), key_manager

    workflow = StateGraph(AgentState)

    # Wrap synchronous agent methods for LangGraph nodes
    workflow.add_node("forecast",      forecast.forecast)
    workflow.add_node("fundamentals",  fundamentals.analyze)
    workflow.add_node("sentiment",     sentiment.analyze)
    workflow.add_node("technical",     technical.analyze)
    workflow.add_node("debaters",      debaters.deliberate)
    workflow.add_node("risk_manager",  risk_manager.assess)

    workflow.set_entry_point("forecast")
    workflow.add_edge("forecast",     "fundamentals")
    workflow.add_edge("fundamentals", "sentiment")
    workflow.add_edge("sentiment",    "technical")
    workflow.add_edge("technical",    "debaters")
    workflow.add_edge("debaters",     "risk_manager")
    workflow.add_edge("risk_manager", END)

    return workflow.compile(), key_manager


# ══════════════════════════════════════════════════════════════════════════════
#  Public execution interface
# ══════════════════════════════════════════════════════════════════════════════

async def run_ai_desk(
    symbol: str = "EUR/USD",
    prices: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Run the full AI desk pipeline and return signed consensus."""
    pipeline, key_manager = create_ai_desk()

    market_data: Dict[str, Any] = {
        "symbol":    symbol,
        "prices":    prices or [1.0800, 1.0815, 1.0805, 1.0825, 1.0810, 1.0830],
        "timestamp": datetime.utcnow().isoformat(),
    }

    initial_state: AgentState = {
        "messages":          [],
        "market_data":       market_data,
        "consensus":         None,
        "signature":         None,
        "risk_score":        0.0,
        "direction":         None,
        "confidence":        0.0,
        "position_size_pct": 0.0,
        "kronos_forecast":   None,
    }

    # LangGraph compile() returns a synchronous runnable
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, pipeline.invoke, initial_state)

    # Verify the signature
    valid_signature = False
    if result.get("consensus") and result.get("signature"):
        valid_signature = key_manager.verify_consensus(result["consensus"], result["signature"])

    fc = result.get("kronos_forecast")
    predicted_price = fc.get("predicted_price") if fc else None

    return {
        "direction":                 result.get("direction"),
        "confidence":                result.get("confidence"),
        "risk_score":                result.get("risk_score"),
        "position_size_pct":         result.get("position_size_pct"),
        "consensus":                 result.get("consensus"),
        "signature":                 result.get("signature"),
        "signature_valid":           valid_signature,
        "public_key_pem":            key_manager.public_key_pem(),
        "kronos_forecast":           fc,
        "forecast_predicted_price":  predicted_price,
        "messages":                  result.get("messages", []),
        "timestamp":                 datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":

    print("=" * 70)
    print("  AI Trading Desk — LangGraph Multi-Agent Pipeline")
    print("=" * 70)

    result = asyncio.run(run_ai_desk(
        symbol="EUR/USD",
        prices=[1.0800, 1.0815, 1.0805, 1.0825, 1.0810, 1.0835, 1.0828, 1.0842],
    ))

    print(f"\nDirection:          {result['direction'].upper()}")
    print(f"Confidence:         {result['confidence']:.1f}%")
    print(f"Risk Score (CVaR):  {result['risk_score']:.5f}")
    print(f"Position Size:      {result['position_size_pct']:.2%}")
    print(f"Signature Valid:    {result['signature_valid']}")
    print(f"\nAgent messages ({len(result['messages'])}):")
    for msg in result["messages"]:
        print(f"  [{msg['agent']}] {msg['content'][:100]}…")
