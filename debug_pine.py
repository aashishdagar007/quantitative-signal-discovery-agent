from core_engine.pine_script import PineScriptService
svc = PineScriptService(strategies_dir='strategies')
code = svc.load_strategy('pulse_hybrid_eurusd.pine')
with open('transpiled.txt', 'w', encoding='utf-8') as f:
    f.write(code)
print('Written to transpiled.txt')