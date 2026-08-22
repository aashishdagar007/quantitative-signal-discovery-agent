import sys
sys.path.insert(0, r'D:\AASHISH\Projects\Bot')

print("=" * 60)
print("AI TRADING SYSTEM - COMPLETE VERIFICATION")
print("=" * 60)

passed = 0
failed = 0

# Task 1: NeMo deps in pyproject.toml
print("\n--- Task 1: NeMo Agent Toolkit Dependencies ---")
with open('pyproject.toml') as f:
    content = f.read()
deps = ['nvidia-nat[langchain]==1.6.*', 'nvidia-nat-phoenix==1.6.*', 'yfinance',
        'arize-phoenix', 'arize-phoenix-otel', 'openinference-instrumentation-langchain', 'jupyter']
for d in deps:
    if d in content:
        print(f"  [OK] {d}")
        passed += 1
    else:
        print(f"  [FAIL] {d}")
        failed += 1

try:
    import backend.app
    print(f"  [OK] backend.app imports OK")
    passed += 1
except Exception as e:
    print(f"  [FAIL] backend.app: {e}")
    failed += 1

# Task 2: Pine Script transpilation
print("\n--- Task 2: Pine Script Transpiler ---")
from core_engine.pine_script import PineScriptService
svc = PineScriptService(strategies_dir='strategies')
for fn in ['pulse_hybrid_eurusd.pine', 'btc_momentum.pine']:
    code = svc.load_strategy(fn)
    if code:
        try:
            compile(code, fn, 'exec')
            print(f"  [OK] {fn} transpiles")
            passed += 1
        except SyntaxError as e:
            print(f"  [FAIL] {fn}: {e}")
            failed += 1
    else:
        print(f"  [FAIL] {fn} failed to load")
        failed += 1

# Task 3: HRP.fit() with DataFrame
print("\n--- Task 3: HRP.fit() DataFrame Columns ---")
import pandas as pd, numpy as np
from core_engine.portfolio_allocation import HierarchicalRiskParity
rets = pd.DataFrame(np.random.normal(0, 0.01, (200, 3)), columns=['BTCUSDT','EURUSD','GBPUSD'])
w = HierarchicalRiskParity().fit(rets).allocate()
keys = set(w.keys())
expected = {'BTCUSDT', 'EURUSD', 'GBPUSD'}
if keys == expected:
    print(f"  [OK] Symbols preserved: {keys}")
    passed += 1
else:
    print(f"  [FAIL] Symbols: {keys} (expected {expected})")
    failed += 1

# Task 4: Cleanup
print("\n--- Task 4: Cleanup ---")
import os
gitignore = open('.gitignore').read()
status1 = 'OK' if 'pip_install.log' in gitignore else 'FAIL'
status2 = 'OK' if 'pytest_output.txt' in gitignore else 'FAIL'
with open('backend/routers/__init__.py') as f:
    rcontent = f.read()
status3 = 'OK' if 'Reserved' in rcontent else 'FAIL'
print(f"  [pip_install.log in .gitignore]: [{status1}]")
print(f"  [pytest_output.txt in .gitignore]: [{status2}]")
print(f"  [routers/__init__.py comment]: [{status3}]")
if status1 == 'OK' and status2 == 'OK' and status3 == 'OK':
    passed += 1
else:
    failed += 1

print(f"\n=== RESULTS: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)