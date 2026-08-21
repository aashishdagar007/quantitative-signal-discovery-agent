#!/usr/bin/env python
"""Functional tests for AI Trading System components"""

import sys
import os
import asyncio
sys.path.insert(0, r'D:\AASHISH\Projects\Bot')

passed = 0
failed = 0

def test(name, func):
    global passed, failed
    try:
        result = func()
        print(f"  [OK] {name}")
        passed += 1
        return result
    except Exception as e:
        print(f"  [FAIL] {name}: {str(e)[:80]}")
        failed += 1
        return None

print("=== Functional Tests ===\n")

# Test 1: Blockchain Ledger
def test_blockchain():
    from blockchain_audit.ledger import ImmutableLedger, MerkleTree
    ledger = ImmutableLedger("./test_chain.db")
    
    # Log a trade
    block = ledger.log_trade({
        "symbol": "BTC/USD",
        "price": 65000.0,
        "side": "buy",
        "quantity": 0.01
    })
    
    # Log a consensus
    block2 = ledger.log_ai_consensus({
        "symbol": "ETH/USD",
        "direction": "long",
        "confidence": 85.5,
        "signature": "abc123"
    })
    
    # Verify chain
    valid, msg = ledger.verify_chain()
    
    # Get blocks
    blocks = ledger.get_blocks(limit=5)
    
    # Get block count
    count = ledger.block_count()
    
    # Cleanup
    ledger.close()
    
    # Remove test db
    if os.path.exists("./test_chain.db"):
        os.remove("./test_chain.db")
    
    return True

test("Blockchain Ledger", test_blockchain)

# Test 2: Pine Script Transpilation
def test_pine_script():
    from core_engine.pine_script import PineScriptParser
    
    pine_code = """
//@version=5
strategy("Test Strategy", overlay=true)
input.int(14, "RSI Length")
float rsi = ta.rsi(close, 14)
bool long_signal = rsi < 30
if long_signal
    strategy.entry("Long", strategy.long)
"""
    
    python_code = PineScriptParser().transpile(pine_code)
    
    # Verify it's valid Python by compiling
    compile(python_code, "<pine_transpiled>", "exec")
    
    return True

test("Pine Script Transpilation", test_pine_script)

# Test 3: Security Profiler
def test_security_profiler():
    from security.python_security_profiler import _PythonSecurityProfiler, AnomalyType
    profiler = _PythonSecurityProfiler()
    
    # Report anomaly with AnomalyType enum
    aid = profiler.report_anomaly(
        AnomalyType.EXECUTION_DEVIATION,
        "Test deviation: 2.5%",
        severity=0.025
    )
    
    # Check state
    state = profiler.get_current_state()
    
    # Track and untrack memory - use 'ptr' not 'point'
    profiler.track_memory(ptr=12345, size=512, location="test_location")
    profiler.untrack_memory(ptr=12345)
    
    # Monitor execution
    profiler.monitor_execution(
        order_id="ORDER_001",
        exec_price=105.50,
        expected_price=100.00,
        deviation_pct=5.5
    )
    
    return True

test("Security Profiler", test_security_profiler)

# Test 3: HRP Portfolio Allocation
def test_portfolio_allocation():
    import numpy as np
    from core_engine.portfolio_allocation import HierarchicalRiskParity
    
    # Generate sample returns data
    np.random.seed(42)
    n_assets = 4
    n_obs = 100
    returns = np.random.normal(0.001, 0.02, (n_obs, n_assets))
    
    # Asset symbols
    symbols = ["BTC", "ETH", "EUR/USD", "GBP/USD"]
    
    # Fit HRP model
    hrp = HierarchicalRiskParity()
    hrp.fit(returns, symbols)
    
    # Allocate positions
    positions = hrp.allocate()
    
    # Weights are in _weights attribute (private)
    weights = hrp._weights
    
    # Compute CVaR
    from core_engine.portfolio_allocation import CVaROptimizer
    cvar_optimizer = CVaROptimizer(confidence_level=0.95)
    portfolio_returns = returns @ weights
    risk_metrics = cvar_optimizer.compute_portfolio_risk(weights, np.cov(returns.T))
    
    return True

test("HRP Portfolio Allocation", test_portfolio_allocation)

# Test 4: AI Desk Quick Run
def test_ai_desk():
    from core_engine.ai_desk import run_ai_desk
    
    result = asyncio.run(run_ai_desk(
        symbol="EUR/USD",
        prices=[1.0800, 1.0815, 1.0795, 1.0820, 1.0810]
    ))
    
    # Verify result has required fields
    assert "direction" in result, "Missing direction"
    assert "confidence" in result, "Missing confidence"
    assert "consensus" in result, "Missing consensus"
    
    return True

test("AI Desk Quick Run", test_ai_desk)

# Test 5: Kronos Forecast
def test_kronos():
    from core_engine.kronos_forecast import KronosProbabilisticModel, Tokenizer
    
    model = KronosProbabilisticModel(vocab_size=1000, d_model=64, n_head=2, n_layer=2)
    
    # Test forecast
    prices = [1.0800, 1.0810, 1.0815, 1.0820, 1.0815, 1.0825, 1.0830, 1.0820]
    forecast = model.forecast(prices, market_type="<CRYPTO>")
    
    # Check median_price is always present
    assert "median_price" in forecast, "Missing median_price"
    
    return True

test("Kronos Forecast", test_kronos)

# Test 5: Execution Engine (simulation only - no MT5)
def test_execution_engine():
    from core_engine.execution_engine import DualMarketEngine
    
    engine = DualMarketEngine()
    
    # Initialize with known symbols (no MT5 config needed for crypto-only)
    engine.initialize(
        binance_symbols=["BTCUSDT"],
        mt5_config={}  # Empty - will use defaults
    )
    
    # Execute a test order
    order = asyncio.run(engine.execute_order(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.001,
        order_type="market"
    ))
    
    assert "id" in order, "Order missing ID"
    assert "status" in order, "Order missing status"
    
    return True

test("Execution Engine", test_execution_engine)

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)