"""
tests_new/test_pine_script.py
Coverage for core_engine/pine_script.py — Pine Script transpiler.

Rules enforced:
  - Always use PineScriptService.load_strategy() — it transpiles internally.
  - Never double-wrap its result in PineScriptParser().transpile().
"""

from __future__ import annotations

import os
import textwrap

import pytest

from core_engine.pine_script import PineScriptParser, PineScriptService

# ── Helpers ──────────────────────────────────────────────────────────────────

def _service_for_dir(tmpdir: str) -> PineScriptService:
    """Return a fresh PineScriptService pointing at a temp strategies dir."""
    return PineScriptService(strategies_dir=tmpdir)


def _write_pine(tmpdir: str, filename: str, content: str) -> str:
    """Write a .pine file into tmpdir and return its filename."""
    path = os.path.join(tmpdir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))
    return filename


# ── Test 1: Both bundled strategies transpile and compile ─────────────────────

class TestBundledStrategies:
    """PineScriptService.load_strategy() must succeed for all shipped .pine files."""

    BUNDLED = ["pulse_hybrid_eurusd.pine", "btc_momentum.pine"]

    @pytest.mark.parametrize("filename", BUNDLED)
    def test_transpile_and_compile(self, filename: str) -> None:
        """load_strategy() returns Python code that compile() accepts without error."""
        svc = PineScriptService(strategies_dir="strategies")
        code = svc.load_strategy(filename)
        assert code is not None, f"load_strategy returned None for {filename}"
        # compile() raises SyntaxError on bad Python — must not raise
        compile(code, filename, "exec")

    @pytest.mark.parametrize("filename", BUNDLED)
    def test_contains_pine_stdlib_import(self, filename: str) -> None:
        """Transpiled output must include the PineStdLib import header."""
        svc = PineScriptService(strategies_dir="strategies")
        code = svc.load_strategy(filename)
        assert "from core_engine.pine_stdlib import PineStdLib as _pine" in code


# ── Test 2: Multi-line strategy() header ─────────────────────────────────────

class TestMultiLineStrategyHeader:
    """
    _join_continuations() must collapse a multi-line strategy() call into one
    logical statement before the transpiler processes it.
    """

    PINE = """\
        //@version=5
        strategy("Multi-Line Test",
            overlay=true,
            initial_capital=10000,
            default_qty_type=strategy.percent_of_equity,
            default_qty_value=10)
        longCondition = close > open
        if longCondition
            strategy.entry("Long", strategy.long)
    """

    def test_multiline_header_compiles(self, tmp_path) -> None:
        fn = _write_pine(str(tmp_path), "multi_line.pine", self.PINE)
        svc = _service_for_dir(str(tmp_path))
        code = svc.load_strategy(fn)
        assert code is not None
        compile(code, fn, "exec")

    def test_single_pass_only(self, tmp_path) -> None:
        """
        The result of load_strategy() is already-transpiled Python.
        Passing it through PineScriptParser().transpile() a second time
        would double-transpile — confirm load_strategy() result is Python
        (contains 'import math'), not Pine source.
        """
        fn = _write_pine(str(tmp_path), "single_pass.pine", self.PINE)
        svc = _service_for_dir(str(tmp_path))
        code = svc.load_strategy(fn)
        assert code is not None
        assert "import math" in code, "Expected Python output, not raw Pine source"
        # Single compile — must not raise
        compile(code, fn, "exec")


# ── Test 3: Ternary nested inside a function call ────────────────────────────

class TestTernaryInsideCall:
    """
    _transform_expr() must correctly unwrap a wrapping call (e.g. bgcolor(...))
    before applying the ternary regex, so bgcolor(cond ? a : b) becomes
    valid Python instead of a SyntaxError.
    """

    PINE = """\
        //@version=5
        indicator("Ternary Test", overlay=true)
        bullish = close > open
        bgColor = bullish ? color.green : color.red
        bgcolor(bullish ? color.green : color.red)
        plot(close)
    """

    def test_ternary_in_call_compiles(self, tmp_path) -> None:
        fn = _write_pine(str(tmp_path), "ternary.pine", self.PINE)
        svc = _service_for_dir(str(tmp_path))
        code = svc.load_strategy(fn)
        assert code is not None
        compile(code, fn, "exec")

    def test_standalone_ternary_compiles(self, tmp_path) -> None:
        """Plain ternary assignment (no wrapping call) must also work."""
        pine = """\
            //@version=5
            indicator("Standalone Ternary")
            x = close > open ? 1.0 : -1.0
            plot(x)
        """
        fn = _write_pine(str(tmp_path), "standalone_ternary.pine", pine)
        svc = _service_for_dir(str(tmp_path))
        code = svc.load_strategy(fn)
        assert code is not None
        compile(code, fn, "exec")


# ── Test 4: Parser unit-level smoke tests ────────────────────────────────────

class TestParserUnit:
    """Direct parser tests for edge cases."""

    def test_join_continuations_single_line(self) -> None:
        parser = PineScriptParser()
        lines = ["strategy('Test', overlay=true)"]
        result = parser._join_continuations(lines)
        assert result == lines

    def test_join_continuations_multiline(self) -> None:
        parser = PineScriptParser()
        lines = [
            "strategy('Test',",
            "    overlay=true,",
            "    initial_capital=10000)",
        ]
        result = parser._join_continuations(lines)
        assert len(result) == 1
        assert "overlay=true" in result[0]
        assert "initial_capital=10000" in result[0]

    def test_join_continuations_comment_not_counted(self) -> None:
        """A // comment after ( should not keep depth > 0."""
        parser = PineScriptParser()
        lines = [
            "x = nz(close) // comment with (unmatched paren",
            "plot(x)",
        ]
        result = parser._join_continuations(lines)
        # The comment's unmatched paren should be ignored
        assert len(result) == 2
