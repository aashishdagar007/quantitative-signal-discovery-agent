# Fix Prompt #2: aashishdagar007/Bot — Regression + Unfinished Tasks

## Context
Current HEAD: `0a0696a`. The last pass correctly fixed the backend import bug
(`backend/app.py` now imports from `backend.database`) and the committed-key issue
(`keys/*.pem` is gitignored, `KeyManager` auto-generates a fresh keypair on first run).
**Do not touch `backend/app.py`'s imports or anything under `keys/` — both are verified
correct.** Same goes for `blockchain_audit/` and `security/` — still verified working,
leave them alone.

That pass also introduced one regression and left two tasks untouched. Fix all three
below, in order, and run each task's verification before moving to the next.

---

## Task 1 — Restore the original NeMo Agent Toolkit dependencies (REGRESSION, CRITICAL)
When the new backend dependencies (fastapi, torch, langgraph, etc.) were added to
`pyproject.toml`, the entire original dependency list for the `signal_discovery_workflow`
project was **deleted** instead of kept alongside the new ones:
```toml
"nvidia-nat[langchain]==1.6.*",
"nvidia-nat-phoenix==1.6.*",
"yfinance",
"arize-phoenix",
"arize-phoenix-otel",
"openinference-instrumentation-langchain",
"jupyter",
```
This broke the original project the repo is built on top of. Confirmed:
```
$ uv run python -c "import signal_discovery_workflow.signal_discovery_optimization_workflow"
ModuleNotFoundError: No module named 'nat'
```

**Fix:** add all seven of the above back into `pyproject.toml`'s `dependencies` list,
**alongside** (not instead of) the backend deps that are already there. Also restore
this comment, which documented a real, previously-hit gotcha and was deleted along with
the deps:
```toml
# Pin both NAT packages to the same compatible release line. Mixing different
# minor versions of nvidia-nat-* causes ImportErrors like
# "cannot import name 'register_dataset_loader' from 'nat.cli.register_workflow'".
```
Then re-lock: `uv lock`.

**If `uv lock` surfaces a genuine version conflict** between `nvidia-nat`'s pinned
dependencies and the newer backend deps (e.g. langchain/langgraph version ranges) —
do **not** silently drop either side to make the resolver pass. Stop and report the
exact conflicting constraints back to me instead of choosing one project over the other.

**Verify (both must succeed together — this is the actual regression test):**
```bash
uv sync --frozen
uv run python -c "import backend.app; print('backend OK')"
uv run python -c "import sys; sys.path.insert(0,'src'); import signal_discovery_workflow.signal_discovery_optimization_workflow; print('signal_discovery_workflow OK')"
```

---

## Task 2 — Fix the Pine Script transpiler on multi-line statements (HIGH, still open)
`core_engine/pine_script.py`'s `PineScriptParser.transpile()` processes Pine source
line-by-line without tracking parenthesis depth. Any statement spanning multiple
physical lines inside an unclosed `(` — e.g. both bundled strategies' `strategy(...)`
headers — produces invalid Python. Still reproduces as of `0a0696a`:
```python
from core_engine.pine_script import PineScriptService, PineScriptParser
svc = PineScriptService(strategies_dir='strategies')
code = svc.load_strategy('pulse_hybrid_eurusd.pine')
py = PineScriptParser().transpile(code)
compile(py, 'x', 'exec')   # SyntaxError: invalid syntax. Perhaps you forgot a comma? (line 20)
```

**Fix:** before `_transform_line` runs per line, join physical lines that are inside an
unclosed bracket depth (track `(`, `[`, `{` counts, respecting string literals and `//`
comments) into one logical line, then transpile that logical line as a unit.

**Verify:**
```python
for fn in ['pulse_hybrid_eurusd.pine', 'btc_momentum.pine']:
    compile(PineScriptParser().transpile(svc.load_strategy(fn)), fn, 'exec')
```
Both must succeed without raising.

---

## Task 3 — Stop HierarchicalRiskParity.fit() from silently discarding symbols (MEDIUM, still open)
`core_engine/portfolio_allocation.py`,
`HierarchicalRiskParity.fit(self, returns, asset_symbols=None)` falls back to generic
`asset_0, asset_1, ...` labels whenever `asset_symbols` isn't explicitly passed — even
when `returns` is a labeled `pandas.DataFrame`. Still reproduces as of `0a0696a`
(`allocate()` returns `asset_0/asset_1/asset_2` instead of the real symbols).

**Fix:** if `asset_symbols` is `None` and `returns` has a `.columns` attribute, default
to `list(returns.columns)` instead of the generic placeholder. Keep the explicit
`asset_symbols` override working for plain `ndarray` input.

**Verify:**
```python
import pandas as pd, numpy as np
from core_engine.portfolio_allocation import HierarchicalRiskParity
rets = pd.DataFrame(np.random.normal(0, 0.01, (200, 3)), columns=['BTCUSDT','EURUSD','GBPUSD'])
w = HierarchicalRiskParity().fit(rets).allocate()
assert set(w.keys()) == {'BTCUSDT', 'EURUSD', 'GBPUSD'}, w.keys()
```

---

## Task 4 — Cleanup (LOW, still open)
- Delete `pip_install.log` and `pytest_output.txt` from the repo (leftover local
  Windows logs); add both filenames to `.gitignore`.
- Remove the empty, unused `backend/routers/` package, or leave a one-line comment in
  `backend/routers/__init__.py` noting it's reserved for future route splitting if
  that's the intent.

---

## Done means
- Task 1's two import checks pass **together** — no regression traded for a fix.
- Both files under `strategies/*.pine` transpile to code that passes `compile()`.
- `HierarchicalRiskParity().fit(df)` without `asset_symbols` returns weights keyed by
  the DataFrame's real column names.
- `uv run pytest tests/` collects without import errors.
- Repo root has no `pip_install.log` / `pytest_output.txt`, and `backend/routers/` is
  either removed or has a comment explaining why it's still there.

End with a diff/PR-style summary of every file changed, and flag anything you had to
touch beyond what's listed here.
