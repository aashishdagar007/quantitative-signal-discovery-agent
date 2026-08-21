"""Verification script for all AI Trading System modules."""
import sys
sys.path.insert(0, '.')

results = []

# ── Test 1: Database models ───────────────────────────────────────────────────
try:
    from backend.database import Base, User, Signal, AuditLog, hash_password, verify_password
    h = hash_password('AdminPass#2026!')
    assert verify_password('AdminPass#2026!', h)
    results.append(('database models + bcrypt', True, None))
except Exception as e:
    results.append(('database models + bcrypt', False, str(e)))

# ── Test 2: Merkle tree ───────────────────────────────────────────────────────
try:
    from blockchain_audit.merkle import MerkleTree
    tree = MerkleTree(['tx1', 'tx2', 'tx3', 'tx4', 'tx5'])
    proof0 = tree.get_proof(0)
    proof4 = tree.get_proof(4)
    assert proof0.verify() and proof4.verify()
    results.append(('Merkle tree proof[0] + proof[4]', True, f'root={tree.root[:16]}'))
except Exception as e:
    results.append(('Merkle tree', False, str(e)))

# ── Test 3: Blockchain ledger ─────────────────────────────────────────────────
try:
    from blockchain_audit.ledger import ImmutableLedger
    ledger = ImmutableLedger(':memory:')
    b1 = ledger.log_trade({'symbol': 'BTCUSDT', 'price': 65000, 'side': 'buy', 'quantity': 0.01})
    b2 = ledger.log_ai_consensus({'symbol': 'EUR/USD', 'direction': 'long', 'confidence': 73.2})
    b3 = ledger.log_state_change({'component': 'engine', 'from': 'stopped', 'to': 'running'})
    valid, msg = ledger.verify_chain()
    assert valid, msg
    proof = ledger.get_proof(b1.tx_id)
    assert proof and proof.verify()
    results.append(('Blockchain ledger', True, f'{msg} | blocks={ledger.block_count()}'))
    ledger.close()
except Exception as e:
    import traceback
    traceback.print_exc()
    results.append(('Blockchain ledger', False, str(e)))

# ── Test 4: Pine Script transpiler ────────────────────────────────────────────
try:
    from core_engine.pine_script import PineScriptParser
    parser = PineScriptParser()
    pine = '\n'.join([
        '//@version=5',
        'strategy(Test, overlay=true)',
        'float ema_f = ta.ema(close, 8)',
        'float rsi_val = ta.rsi(close, 14)',
        'bool sig = ta.crossover(ema_f, close)',
        'if sig',
        '    strategy.entry(Long, strategy.long)',
    ])
    py = parser.transpile(pine)
    assert '_pine.ema' in py
    assert '_pine.rsi' in py
    assert 'strategy_entry' in py
    assert '_pine.crossover' in py
    results.append(('Pine Script transpiler', True, f'{len(py.splitlines())} Python lines'))
except Exception as e:
    import traceback
    traceback.print_exc()
    results.append(('Pine Script transpiler', False, str(e)))

# ── Test 5: Pine stdlib ───────────────────────────────────────────────────────
try:
    from core_engine.pine_script import PineStdLib
    prices = [1.0800, 1.0815, 1.0805, 1.0825, 1.0810, 1.0830,
              1.0820, 1.0840, 1.0815, 1.0845, 1.0838, 1.0850, 1.0842]
    ema_val = PineStdLib.ema(prices, 8)
    rsi_val = PineStdLib.rsi(prices, 12)
    sma_val = PineStdLib.sma(prices, 8)
    assert isinstance(ema_val, float)
    assert 0 <= rsi_val <= 100
    results.append(('Pine stdlib ema/rsi/sma', True, f'EMA={ema_val:.5f} RSI={rsi_val:.2f} SMA={sma_val:.5f}'))
except Exception as e:
    import traceback
    traceback.print_exc()
    results.append(('Pine stdlib', False, str(e)))

# ── Test 6: Security profiler ─────────────────────────────────────────────────
try:
    from security.python_security_profiler import SecurityProfilerBridge, AnomalyType, SecurityState
    import json
    p = SecurityProfilerBridge()
    p.report_anomaly(AnomalyType.EXECUTION_DEVIATION, 'Slippage 0.6pct', 0.4)
    p.track_memory(0xDEAD, 2048, 'test.py:99')
    p.untrack_memory(0xDEAD)
    summary = json.loads(p.summary_json())
    assert summary['anomaly_count'] >= 1
    results.append(('Security profiler (Python)', True,
                    'using_cpp=' + str(p.using_cpp) + ' anomalies=' + str(summary['anomaly_count'])))
except Exception as e:
    import traceback
    traceback.print_exc()
    results.append(('Security profiler', False, str(e)))

# ── Test 7: Strategy files ────────────────────────────────────────────────────
try:
    from core_engine.pine_script import PineScriptService
    svc = PineScriptService('strategies')
    strats = svc.list_strategies()
    assert len(strats) == 2, 'Expected 2 strategies, got ' + str(len(strats))
    for s in strats:
        code = svc.load_strategy(s)
        assert code and len(code) > 100
    results.append(('Pine strategy files (' + str(len(strats)) + ')', True,
                    str(strats)))
except Exception as e:
    results.append(('Pine strategy files', False, str(e)))

# ── Test 8: Kronos forecast (numpy fallback) ──────────────────────────────────
try:
    from core_engine.kronos_forecast import KronosProbabilisticModel
    model = KronosProbabilisticModel()
    prices = [65000.0 + i * 50 + (i % 3) * -30 for i in range(30)]
    fc = model.forecast(prices)
    assert 'predicted_price' in fc
    assert fc['predicted_price'] > 0
    results.append(('Kronos forecast', True,
                    'predicted=' + str(round(fc['predicted_price'], 2)) +
                    ' range=' + str([round(x, 0) for x in fc.get('confidence_intervals', {}).get('p10_p90', {}).values()])))
except Exception as e:
    import traceback
    traceback.print_exc()
    results.append(('Kronos forecast', False, str(e)))

# ── Print summary ─────────────────────────────────────────────────────────────
print()
print('=' * 70)
print('  AI Trading System — Full Verification Suite')
print('=' * 70)
passed = sum(1 for _, ok, _ in results if ok)
for name, ok, detail in results:
    status = 'PASS' if ok else 'FAIL'
    mark   = 'v' if ok else 'X'
    line   = f'  [{mark}] {status}  {name}'
    if detail:
        line += f'  ({detail})'
    print(line)
print()
print(f'  {passed}/{len(results)} tests passed')
print('=' * 70)
