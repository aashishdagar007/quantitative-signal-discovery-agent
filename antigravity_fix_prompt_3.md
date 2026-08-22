# Fix Prompt #3: aashishdagar007/Bot — Pine Transpiler + Untrack Log Files

## Context
Current HEAD: `71bf517`. Everything else is now verified correct — do not touch any of
this: `backend/app.py`'s imports, `keys/` handling, `pyproject.toml`'s dependency list
(both the NeMo Agent Toolkit deps and the backend deps are correctly present together),
`core_engine/portfolio_allocation.py`'s `HierarchicalRiskParity.fit()`, `backend/routers/`,
`blockchain_audit/`, or `security/`. Only the two tasks below are still open.

---

## Task 1 — Fix the Pine Script transpiler on multi-line statements (HIGH)
`core_engine/pine_script.py`'s `PineScriptParser.transpile()` processes Pine source
line-by-line without tracking parenthesis depth. Any statement spanning multiple
physical lines inside an unclosed `(` — e.g. both bundled strategies' `strategy(...)`
headers — produces invalid Python. This has been skipped in two prior fix passes.
Still reproduces as of `71bf517`:
```python
from core_engine.pine_script import PineScriptService, PineScriptParser
svc = PineScriptService(strategies_dir='strategies')
code = svc.load_strategy('pulse_hybrid_eurusd.pine')
py = PineScriptParser().transpile(code)
compile(py, 'x', 'exec')
# SyntaxError: invalid syntax. Perhaps you forgot a comma? (line 20)
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

## Task 2 — Actually untrack the already-gitignored log files (LOW)
`.gitignore` already lists `pip_install.log` and `pytest_output.txt`, but adding a
gitignore rule doesn't remove files that were already committed — `git ls-files` still
shows both as tracked.

**Fix:**
```bash
git rm --cached pip_install.log pytest_output.txt
```
This removes them from tracking going forward while leaving the local files alone (or
delete them locally too if they're not needed — they're leftover Windows build logs).
Commit the removal.

**Verify:**
```bash
git ls-files | grep -E "pip_install.log|pytest_output.txt"
```
Must return nothing.

---

## Done means
- Both files under `strategies/*.pine` transpile to code that passes `compile()`.
- `git ls-files` no longer lists `pip_install.log` or `pytest_output.txt`.
- Nothing outside `core_engine/pine_script.py` and the git-tracking change is modified.

End with a diff/PR-style summary of every file changed, and flag anything you had to
touch beyond what's listed here.
