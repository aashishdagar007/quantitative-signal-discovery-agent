import asyncio
import json
import time
from typing import Dict, List, Optional, Any, TypedDict
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
import numpy as np

from langgraph.graph import StateGraph, END
from langchain.llms import OpenAI
from langchain.schema import HumanMessage, SystemMessage


# --- Cryptographic Signing ---

class KeyManager:
    """Manages cryptographic key pairs for agent consensus signing"""
    
    def __init__(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self.public_key = self.private_key.public_key()
    
    def sign_consensus(self, consensus: str) -> str:
        """Sign the consensus decision"""
        signature = self.private_key.sign(
            consensus.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return signature.hex()
    
    def verify_consensus(self, consensus: str, signature: str) -> bool:
        """Verify consensus signature"""
        try:
            self.public_key.verify(
                bytes.fromhex(signature),
                consensus.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
        except Exception:
            return False


# --- Agent States ---

class AgentState(TypedDict):
    """State shared between LangGraph agents"""
    messages: List[Dict[str, Any]]
    market_data: Dict[str, Any]
    consensus: Optional[str]
    signature: Optional[str]
    risk_score: float
    direction: Optional[str]  # "long" or "short"
    confidence: float


# --- Specialized LLM Agents ---

class FundamentalsAgent:
    """Analyzes macroeconomic fundamentals for forex and crypto"""
    
    def __init__(self, key_manager: KeyManager):
        self.llm = OpenAI(temperature=0.3, max_tokens=512)
        self.key_manager = key_manager
    
    async def analyze(self, state: AgentState) -> AgentState:
        """Analyze fundamentals and return assessment"""
        market_data = state.get("market_data", {})
        
        # Extract relevant data
        symbol = market_data.get("symbol", "EUR/USD")
        timeframe = market_data.get("timeframe", "1h")
        
        prompt = f"""
        Analyze the macroeconomic fundamentals for {symbol} ({timeframe} timeframe).
        Consider:
        - Interest rate differentials (Fed vs ECB for EUR/USD)
        - GDP growth, employment data, CPI inflation
        - Crypto on-chain metrics: hash rate, transaction volume, active addresses
        - Risk sentiment: VIX, USD index, safe-haven flows
        
        Provide a fundamental assessment with a directional bias (long/short) 
        and confidence level (0-100).
        """
        
        messages = [SystemMessage(content=prompt)]
        response = await self.llm.agenerate(messages=messages)
        
        assessment_text = response.generations[0][0].text
        
        # Parse direction and confidence from assessment
        direction = "neutral"
        confidence = 50.0
        if "long" in assessment_text.lower():
            direction = "long"
        elif "short" in assessment_text.lower():
            direction = "short"
        
        try:
            # Try to extract confidence number
            import re
            match = re.search(r'(\d+(\.\d+)?)%', assessment_text)
            if match:
                confidence = float(match.group(1))
        except:
            pass
        
        return {
            **state,
            "messages": state.get("messages", []) + [
                {"agent": "fundamentals", "role": "assessment", "content": assessment_text}
            ],
            "risk_score": 0.3 if direction == "long" else 0.4  # simplified
        }


class SentimentAgent:
    """Analyzes market sentiment from news and on-chain data"""
    
    def __init__(self, key_manager: KeyManager):
        self.llm = OpenAI(temperature=0.3, max_tokens=512)
        self.key_manager = key_manager
    
    async def analyze(self, state: AgentState) -> AgentState:
        """Analyze sentiment and return assessment"""
        market_data = state.get("market_data", {})
        symbol = market_data.get("symbol", "EUR/USD")
        
        prompt = f"""
        Analyze market sentiment for {symbol} based on:
        - Recent cryptocurrency news (Twitter, Reddit, news sites)
        - Forex news: central bank speeches, geopolitical events
        - On-chain sentiment: whale movements, exchange inflows/outflows
        - Fear & Greed Index values
        
        Provide a sentiment analysis with directional bias (long/short) 
        and confidence level (0-100).
        """
        
        messages = [SystemMessage(content=prompt)]
        response = await self.llm.agenerate(messages=messages)
        
        assessment_text = response.generations[0][0].text
        
        direction = "neutral"
        confidence = 50.0
        if "long" in assessment_text.lower():
            direction = "long"
        elif "short" in assessment_text.lower():
            direction = "short"
        
        try:
            import re
            match = re.search(r'(\d+(\.\d+)?)%', assessment_text)
            if match:
                confidence = float(match.group(1))
        except:
            pass
        
        return {
            **state,
            "messages": state.get("messages", []) + [
                {"agent": "sentiment", "role": "assessment", "content": assessment_text}
            ]
        }


class TechnicalAgent:
    """Technical analysis agent using indicators"""
    
    def __init__(self, key_manager: KeyManager):
        self.llm = OpenAI(temperature=0.3, max_tokens=512)
        self.key_manager = key_manager
    
    async def analyze(self, state: AgentState) -> AgentState:
        """Technical analysis"""
        market_data = state.get("market_data", {})
        symbol = market_data.get("symbol", "EUR/USD")
        
        # Get recent price data
        prices = market_data.get("prices", [])
        if len(prices) < 20:
            return state
        
        # Calculate simple indicators
        prices_arr = np.array(prices[-50:])
        sma = np.mean(prices_arr[-20:])
        current_price = prices_arr[-1]
        rsi = 50.0  # simplified
        
        prompt = f"""
        Technical analysis for {symbol}:
        - Current price: {current_price:.5f}
        - 20-period SMA: {sma:.5f}
        - Recent price trend: {'upward' if current_price > sma else 'downward'}
        - Provide directional bias (long/short) and confidence (0-100).
        """
        
        messages = [SystemMessage(content=prompt)]
        response = await self.llm.agenerate(messages=messages)
        
        assessment_text = response.generations[0][0].text
        
        direction = "neutral"
        confidence = 50.0
        if "long" in assessment_text.lower():
            direction = "long"
        elif "short" in assessment_text.lower():
            direction = "short"
        
        try:
            import re
            match = re.search(r'(\d+(\.\d+)?)%', assessment_text)
            if match:
                confidence = float(match.group(1))
        except:
            pass
        
        return {
            **state,
            "messages": state.get("messages", []) + [
                {"agent": "technical", "role": "assessment", "content": assessment_text}
            ]
        }


class DebatersAgent:
    """Multi-agent debate to challenge and refine consensus"""
    
    def __init__(self, key_manager: KeyManager):
        self.llm = OpenAI(temperature=0.7, max_tokens=512)
        self.key_manager = key_manager
        self.positions = ["bull", "bear"]
    
    async def deliberate(self, state: AgentState) -> AgentState:
        """Run debate among agents"""
        messages = state.get("messages", [])
        
        # Summarize all agent assessments
        assessments = []
        for msg in messages:
            if msg.get("role") == "assessment":
                assessments.append(msg["content"])
        
        if not assessments:
            return state
        
        debate_prompt = f"""
        We have multiple agent assessments for market direction:
        
        {chr(10).join(assessments)}
        
        Conduct a structured debate:
        1. Bull case: Why the market will go long
        2. Bear case: Why the market will go short
        3. Identify the strongest arguments
        4. Reach a consensus direction (long/short/neutral) 
           and updated confidence level (0-100)
        
        Provide the final consensus direction and confidence.
        """
        
        messages_langgraph = [SystemMessage(content=debate_prompt)]
        response = await self.llm.agenerate(messages=messages_langgraph)
        
        consensus_text = response.generations[0][0].text
        
        direction = "neutral"
        confidence = 50.0
        if "long" in consensus_text.lower():
            direction = "long"
        elif "short" in consensus_text.lower():
            direction = "short"
        
        try:
            import re
            match = re.search(r'(\d+(\.\d+)?)%', consensus_text)
            if match:
                confidence = float(match.group(1))
        except:
            pass
        
        # Sign the consensus
        signature = self.key_manager.sign_consensus(consensus_text)
        
        return {
            **state,
            "consensus": consensus_text,
            "signature": signature,
            "direction": direction,
            "confidence": confidence,
            "messages": state.get("messages", []) + [
                {"agent": "debaters", "role": "consensus", "content": consensus_text}
            ]
        }


class RiskManagerAgent:
    """Risk management and position sizing"""
    
    def __init__(self, key_manager: KeyManager):
        self.llm = OpenAI(temperature=0.3, max_tokens=512)
        self.key_manager = key_manager
    
    async def assess(self, state: AgentState) -> AgentState:
        """Assess risk and calculate position sizing"""
        direction = state.get("direction", "neutral")
        confidence = state.get("confidence", 50.0)
        market_data = state.get("market_data", {})
        
        # Risk parameters
        cvar_confidence = 0.95
        max_risk_per_trade = 0.02  # 2% of capital
        
        # Calculate VaR/CVaR based on historical volatility
        prices = market_data.get("prices", [])
        if len(prices) > 1:
            returns = np.diff(prices) / prices[:-1]
            volatility = np.std(returns) * np.sqrt(24)  # daily vol assuming hourly
            
            # VaR at 95%
            var_95 = -np.percentile(returns, 5)
            
            # CVaR (Expected Shortfall)
            cvar = np.mean(returns[returns <= -var_95])
        else:
            volatility = 0.02
            var_95 = 0.01
            cvar = -0.02
        
        # Position sizing based on Kelly/HRP approach
        if direction != "neutral" and confidence > 0:
            # Risk-adjusted position size
            risk_factor = confidence / 100.0
            position_size_pct = max_risk_per_trade * risk_factor / max(abs(cvar), 0.001)
            position_size_pct = min(position_size_pct, 0.10)  # cap at 10%
        else:
            position_size_pct = 0.0
        
        # Generate risk report
        risk_report = f"""
        Risk Assessment:
        - Direction: {direction}
        - Confidence: {confidence:.1f}%
        - Portfolio VaR (95%): {var_95:.4f}
        - Portfolio CVaR (95%): {cvar:.4f}
        - Recommended position size: {position_size_pct:.2f}% of capital
        - Max allowed risk: {max_risk_per_trade:.1%}
        """
        
        return {
            **state,
            "risk_score": abs(cvar),
            "messages": state.get("messages", []) + [
                {"agent": "risk_manager", "role": "risk_report", "content": risk_report}
            ]
        }


# --- LangGraph Orchestration ---

def create_ai_desk():
    """Create and configure the LangGraph multi-agent pipeline"""
    
    key_manager = KeyManager()
    
    # Initialize agents
    fundamentals = FundamentalsAgent(key_manager)
    sentiment = SentimentAgent(key_manager)
    technical = TechnicalAgent(key_manager)
    debaters = DebatersAgent(key_manager)
    risk_manager = RiskManagerAgent(key_manager)
    
    # Build the state graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("fundamentals", lambda state: fundamentals.analyze(state))
    workflow.add_node("sentiment", lambda state: sentiment.analyze(state))
    workflow.add_node("technical", lambda state: technical.analyze(state))
    workflow.add_node("debaters", lambda state: debaters.deliberate(state))
    workflow.add_node("risk_manager", lambda state: risk_manager.assess(state))
    
    # Add edges - linear flow with debate in the middle
    workflow.set_entry_point("fundamentals")
    workflow.add_edge("fundamentals", "sentiment")
    workflow.add_edge("sentiment", "technical")
    workflow.add_edge("technical", "debaters")
    workflow.add_edge("debaters", "risk_manager")
    workflow.add_edge("risk_manager", END)
    
    app = workflow.compile()
    
    return app, key_manager


# --- Execution ---

async def run_ai_desk(symbol: str = "EUR/USD", 
                      prices: List[float] = None) -> Dict:
    """Run the AI desk and return consensus"""
    
    app, key_manager = create_ai_desk()
    
    # Prepare market data
    market_data = {
        "symbol": symbol,
        "prices": prices or [1.0800, 1.0810, 1.0795, 1.0820, 1.0815],
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Initial state
    initial_state: AgentState = {
        "messages": [],
        "market_data": market_data,
        "consensus": None,
        "signature": None,
        "risk_score": 0.0,
        "direction": None,
        "confidence": 0.0
    }
    
    # Run the graph
    result = await app.ainvoke(initial_state)
    
    return {
        "direction": result.get("direction"),
        "confidence": result.get("confidence"),
        "consensus": result.get("consensus"),
        "signature": result.get("signature"),
        "risk_score": result.get("risk_score"),
        "messages": result.get("messages", [])
    }


if __name__ == "__main__":
    import re
    
    print("=" * 60)
    print("AI Trading Desk - LangGraph Multi-Agent Pipeline")
    print("=" * 60)
    
    # Run with EUR/USD sample data
    result = asyncio.run(run_ai_desk(
        symbol="EUR/USD",
        prices=[1.0800, 1.0815, 1.0805, 1.0825, 1.0810, 1.0830, 1.0825, 1.0840]
    ))
    
    print(f"\nDirection: {result['direction'].upper()}")
    print(f"Confidence: {result['confidence']:.1f}%")
    print(f"Risk Score: {result['risk_score']:.4f}")
    print(f"\nConsensus: {result['consensus'][:100]}...")
    print(f"\nSignature valid: verification would use public key")
    print(f"\nMessages ({len(result['messages'])}):")
    for msg in result['messages'][-5:]:
        print(f"  {msg['agent']}: {msg['content'][:80]}...")