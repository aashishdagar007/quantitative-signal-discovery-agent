"""
AI Trading System — Pine Script Transpiler
Converts Pine Script v5 (.pine) files to executable Python strategies
using regex-based line-by-line parsing (NOT Python AST — Pine Script
is not valid Python and ast.parse() cannot process it).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════════════
#  Pine Script v5 Regex Transpiler
# ══════════════════════════════════════════════════════════════════════════════

class PineScriptParser:
    """
    Transpiles Pine Script v5 source to Python code via regex-based
    line-by-line pattern matching and substitution.

    Supported constructs:
    - //@version=5 directive
    - indicator() / strategy() declarations
    - var / varip variable declarations (all Pine types)
    - series (implicit): float, int, bool, color, string
    - Arithmetic, comparison, logical operators
    - if / else / for / while control flow
    - Functions: ta.sma(), ta.ema(), ta.rsi(), ta.atr(), ta.macd(), ta.bbands()
    - strategy.entry(), strategy.exit(), strategy.close()
    - plotshape(), plot(), hline(), bgcolor()
    - math.*, array.*, string.* namespaces
    - input.* functions
    """

    # ── Built-in Pine → Python function mappings ──────────────────────────────

    FUNC_MAP: Dict[str, str] = {
        # Technical indicators
        "ta.sma":              "_pine.sma",
        "ta.ema":              "_pine.ema",
        "ta.rsi":              "_pine.rsi",
        "ta.atr":              "_pine.atr",
        "ta.macd":             "_pine.macd",
        "ta.bbands":           "_pine.bbands",
        "ta.stoch":            "_pine.stoch",
        "ta.crossover":        "_pine.crossover",
        "ta.crossunder":       "_pine.crossunder",
        "ta.highest":          "_pine.highest",
        "ta.lowest":           "_pine.lowest",
        "ta.change":           "_pine.change",
        "ta.valuewhen":        "_pine.valuewhen",
        "ta.barssince":        "_pine.barssince",
        # Strategy actions
        "strategy.entry":      "_pine.strategy_entry",
        "strategy.exit":       "_pine.strategy_exit",
        "strategy.close":      "_pine.strategy_close",
        "strategy.close_all":  "_pine.strategy_close_all",
        # Plot / visual (no-op in Python)
        "plot":                "_pine.plot",
        "plotshape":           "_pine.plotshape",
        "hline":               "_pine.hline",
        "bgcolor":             "_pine.bgcolor",
        "label.new":           "_pine.label_new",
        "line.new":            "_pine.line_new",
        # Math
        "math.abs":            "abs",
        "math.max":            "max",
        "math.min":            "min",
        "math.sqrt":           "math.sqrt",
        "math.log":            "math.log",
        "math.exp":            "math.exp",
        "math.pow":            "math.pow",
        "math.round":          "round",
        "math.floor":          "math.floor",
        "math.ceil":           "math.ceil",
        "math.sign":           "_pine.sign",
        "math.pi":             "math.pi",
        # Inputs (return defaults in Python)
        "input.bool":          "_pine.input_bool",
        "input.int":           "_pine.input_int",
        "input.float":         "_pine.input_float",
        "input.string":        "_pine.input_string",
        "input.source":        "_pine.input_source",
        # Series builtins
        "nz":                  "_pine.nz",
        "na":                  "None",
        "not na":              "_pine.notna",
        "bar_index":           "_pine.bar_index",
        "last_bar_index":      "_pine.last_bar_index",
        "time":                "_pine.time_val",
        "timenow":             "_pine.timenow",
    }

    # Pine type keywords to strip
    TYPE_KEYWORDS = r"\b(float|int|bool|color|string|label|line|box|table|series|simple|const)\s+"

    # Pine operator → Python operator
    OP_MAP = {
        "and":  " and ",
        "or":   " or ",
        "not":  " not ",
        "!=":   " != ",
        "==":   " == ",
        "=>":   " => ",   # will be handled separately in lambdas
        ":=":   " = ",    # reassignment
    }

    def __init__(self) -> None:
        self._indent_stack: List[int] = [0]
        self._var_types: Dict[str, str] = {}

    def _join_continuations(self, lines: List[str]) -> List[str]:
        """
        Join physical lines that sit inside an unclosed ( [ { across lines
        (e.g. a multi-line strategy(...) / indicator(...) header), so each
        logical Pine statement becomes exactly one entry in the result.
        Skips characters inside string literals and after an unquoted //
        comment marker when counting bracket depth.
        """
        joined: List[str] = []
        buffer = ""
        depth = 0
        for raw_line in lines:
            in_string: Optional[str] = None
            idx = 0
            n = len(raw_line)
            while idx < n:
                ch = raw_line[idx]
                if in_string:
                    if ch == "\\" and idx + 1 < n:
                        idx += 2
                        continue
                    if ch == in_string:
                        in_string = None
                    idx += 1
                    continue
                if ch in ("\"", "'"):
                    in_string = ch
                    idx += 1
                    continue
                if ch == "/" and idx + 1 < n and raw_line[idx + 1] == "/":
                    break
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                idx += 1
            buffer = raw_line if not buffer else buffer + " " + raw_line.strip()
            if depth <= 0:
                joined.append(buffer)
                buffer = ""
                depth = 0
        if buffer:
            joined.append(buffer)
        return joined

    def transpile(self, pine_code: str) -> str:
        """Main entry: transpile full Pine Script source to Python."""
        lines = pine_code.splitlines()
        lines = self._join_continuations(lines)
        python_lines: List[str] = [
            "# Auto-transpiled from Pine Script v5",
            "import math",
            "from core_engine.pine_stdlib import PineStdLib as _pine",
            "",
        ]

        i = 0
        while i < len(lines):
            raw = lines[i]
            stripped = raw.rstrip()

            # Skip version directive and blank comments
            if stripped.lstrip().startswith("//@version"):
                i += 1
                continue

            # Block comments
            if "/*" in stripped:
                while i < len(lines) and "*/" not in lines[i]:
                    i += 1
                i += 1
                continue

            py_line = self._transform_line(stripped)
            if py_line is not None:
                python_lines.append(py_line)
            i += 1

        return "\n".join(python_lines)

    def _transform_line(self, line: str) -> Optional[str]:
        """Transform a single Pine Script line into Python."""
        stripped = line.lstrip()

        # Empty / pure comment
        if not stripped:
            return ""
        if stripped.startswith("//"):
            return line.replace("//", "#", 1)

        # Inline comment
        line_body, _, comment = line.partition("//")
        comment_part = f"  # {comment.strip()}" if comment.strip() else ""

        # Leading whitespace (preserve indentation)
        indent = len(line) - len(line.lstrip())
        body = line_body.strip()

        # ── Declarations & directives ─────────────────────────────────────────
        if re.match(r"indicator\s*\(", body) or re.match(r"strategy\s*\(", body):
            return " " * indent + f"_pine.declare({body})" + comment_part

        # var / varip variable declarations
        m = re.match(r"(?:var(?:ip)?\s+)?(?:float|int|bool|string|color)?\s*(\w+)\s*=\s*(.+)", body)
        if m and not body.startswith("if") and not body.startswith("for") and not body.startswith("while"):
            name = m.group(1)
            value = self._transform_expr(m.group(2))
            return " " * indent + f"{name} = {value}" + comment_part

        # ── Control flow ──────────────────────────────────────────────────────
        # if condition
        m = re.match(r"if\s+(.+)", body)
        if m:
            cond = self._transform_expr(m.group(1).rstrip(":"))
            return " " * indent + f"if {cond}:" + comment_part

        # else if
        m = re.match(r"else if\s+(.+)", body)
        if m:
            cond = self._transform_expr(m.group(1).rstrip(":"))
            return " " * indent + f"elif {cond}:" + comment_part

        # else
        if re.match(r"^else\s*$", body) or body == "else":
            return " " * indent + "else:" + comment_part

        # for loop: for i = start to end [by step]
        m = re.match(r"for\s+(\w+)\s*=\s*(.+?)\s+to\s+(.+?)(?:\s+by\s+(.+))?$", body)
        if m:
            var, start, end = m.group(1), m.group(2), m.group(3)
            step = m.group(4) or "1"
            start = self._transform_expr(start)
            end   = self._transform_expr(end)
            step  = self._transform_expr(step)
            return " " * indent + f"for {var} in range(int({start}), int({end}) + 1, int({step})):" + comment_part

        # while
        m = re.match(r"while\s+(.+)", body)
        if m:
            cond = self._transform_expr(m.group(1).rstrip(":"))
            return " " * indent + f"while {cond}:" + comment_part

        # ── Return statement ──────────────────────────────────────────────────
        m = re.match(r"return\s+(.*)", body)
        if m:
            return " " * indent + f"return {self._transform_expr(m.group(1))}" + comment_part

        # ── Function definition: name(params) => expr ─────────────────────────
        m = re.match(r"(\w+)\s*\(([^)]*)\)\s*=>\s*(.+)", body)
        if m:
            fname, params, expr = m.group(1), m.group(2), m.group(3)
            py_expr = self._transform_expr(expr)
            return " " * indent + f"def {fname}({params}):\n{' ' * (indent + 4)}return {py_expr}" + comment_part

        # ── Assignment / reassignment ──────────────────────────────────────────
        m = re.match(r"(\w[\w.]*)\s*(:?=)\s*(.+)", body)
        if m:
            name  = m.group(1)
            value = self._transform_expr(m.group(3))
            return " " * indent + f"{name} = {value}" + comment_part

        # ── Generic expression (function call, etc.) ──────────────────────────
        return " " * indent + self._transform_expr(body) + comment_part

    def _transform_expr(self, expr: str) -> str:
        """Transform a Pine Script expression to Python."""
        expr = expr.strip()

        # Strip Pine type annotations
        expr = re.sub(self.TYPE_KEYWORDS, "", expr)

        # Single call wrapping the whole expression, e.g. bgcolor(COND ? A : B).
        # Unwrap it first so a ternary living inside the call's argument is
        # transformed against the argument alone, not against "name(argument"
        # with the call's own opening paren swallowed into the condition.
        # Reassigns expr (rather than returning early) so the outer name
        # still passes through the FUNC_MAP renaming below.
        m_call = re.match(r"^([\w.]+)\((.*)\)$", expr)
        if m_call and m_call.group(2).count("(") == m_call.group(2).count(")"):
            fn_name, inner = m_call.group(1), m_call.group(2)
            expr = f"{fn_name}({self._transform_expr(inner)})"

        # Ternary: condition ? true_val : false_val → (true_val if condition else false_val)
        m = re.match(r"^(.+?)\s*\?\s*(.+?)\s*:\s*(.+)$", expr)
        if m:
            cond, t, f = m.group(1), m.group(2), m.group(3)
            return f"({self._transform_expr(t)} if {self._transform_expr(cond)} else {self._transform_expr(f)})"

        # Apply function mappings (longest first to avoid partial matches)
        for pine_fn, py_fn in sorted(self.FUNC_MAP.items(), key=lambda x: -len(x[0])):
            expr = re.sub(re.escape(pine_fn) + r"\b", py_fn, expr)

        # na → None
        expr = re.sub(r"\bna\b", "None", expr)
        # true/false → True/False
        expr = re.sub(r"\btrue\b",  "True",  expr)
        expr = re.sub(r"\bfalse\b", "False", expr)

        return expr


# ══════════════════════════════════════════════════════════════════════════════
#  Pine Script Standard Library (Python runtime)
# ══════════════════════════════════════════════════════════════════════════════

class PineStdLib:
    """
    Runtime implementation of Pine Script built-in functions.
    Injected as `_pine` into transpiled strategy namespaces.
    """

    # ── State ─────────────────────────────────────────────────────────────────
    signals:  List[Dict[str, Any]] = []
    _bar_idx: int = 0

    @classmethod
    def declare(cls, *args, **kwargs) -> None:
        pass  # no-op in Python

    # ── Series / data accessors ───────────────────────────────────────────────

    @property
    def bar_index(self) -> int:
        return self._bar_idx

    @property
    def last_bar_index(self) -> int:
        return self._bar_idx

    @staticmethod
    def time_val() -> int:
        import time
        return int(time.time())

    @staticmethod
    def timenow() -> int:
        import time
        return int(time.time() * 1000)

    # ── Null handling ─────────────────────────────────────────────────────────

    @staticmethod
    def nz(value: Any, replacement: float = 0.0) -> float:
        return replacement if value is None or (isinstance(value, float) and math.isnan(value)) else value

    @staticmethod
    def notna(value: Any) -> bool:
        return value is not None and not (isinstance(value, float) and math.isnan(value))

    # ── Math ──────────────────────────────────────────────────────────────────

    @staticmethod
    def sign(x: float) -> float:
        return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)

    # ── Technical Indicators ──────────────────────────────────────────────────

    @staticmethod
    def sma(series: List[float], length: int) -> float:
        if not series or len(series) < 1:
            return float("nan")
        window = series[-length:] if len(series) >= length else series
        return sum(window) / len(window)

    @staticmethod
    def ema(series: List[float], length: int) -> float:
        if not series:
            return float("nan")
        k = 2.0 / (length + 1)
        ema_val = series[0]
        for p in series[1:]:
            ema_val = k * p + (1 - k) * ema_val
        return ema_val

    @staticmethod
    def rsi(series: List[float], length: int = 14) -> float:
        if len(series) < length + 1:
            return 50.0
        deltas = [series[i] - series[i - 1] for i in range(1, len(series))]
        gains  = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_g  = sum(gains[-length:])  / length if gains  else 1e-9
        avg_l  = sum(losses[-length:]) / length if losses else 1e-9
        return 100.0 - 100.0 / (1.0 + avg_g / avg_l)

    @staticmethod
    def atr(high: List[float], low: List[float], close: List[float], length: int = 14) -> float:
        if len(high) < 2:
            return 0.0
        trs = []
        for i in range(1, len(high)):
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
            trs.append(tr)
        return sum(trs[-length:]) / min(length, len(trs)) if trs else 0.0

    @staticmethod
    def crossover(a: List[float], b: List[float]) -> bool:
        if len(a) < 2 or len(b) < 2:
            return False
        return a[-2] <= b[-2] and a[-1] > b[-1]

    @staticmethod
    def crossunder(a: List[float], b: List[float]) -> bool:
        if len(a) < 2 or len(b) < 2:
            return False
        return a[-2] >= b[-2] and a[-1] < b[-1]

    @staticmethod
    def highest(series: List[float], length: int) -> float:
        return max(series[-length:]) if series else float("nan")

    @staticmethod
    def lowest(series: List[float], length: int) -> float:
        return min(series[-length:]) if series else float("nan")

    @staticmethod
    def change(series: List[float], length: int = 1) -> float:
        if len(series) <= length:
            return 0.0
        return series[-1] - series[-1 - length]

    @staticmethod
    def valuewhen(condition: bool, series: List[float], occurrence: int = 0) -> float:
        return series[-1] if series else float("nan")

    @staticmethod
    def barssince(condition: bool) -> int:
        return 0  # placeholder

    @staticmethod
    def macd(series, fast=12, slow=26, signal=9):
        ema_fast = PineStdLib.ema(series, fast)
        ema_slow = PineStdLib.ema(series, slow)
        macd_line = ema_fast - ema_slow
        return macd_line, 0.0, macd_line  # macd, signal, hist simplified

    @staticmethod
    def bbands(series, length=20, mult=2.0):
        sma = PineStdLib.sma(series, length)
        window = series[-length:] if len(series) >= length else series
        std = (sum((x - sma) ** 2 for x in window) / len(window)) ** 0.5
        return sma + mult * std, sma, sma - mult * std

    @staticmethod
    def stoch(close, high, low, k_period=14, d_period=3):
        h = PineStdLib.highest(high, k_period)
        low_val = PineStdLib.lowest(low, k_period)
        k = (close[-1] - low_val) / (h - low_val) * 100 if h != low_val else 50.0
        return k, k  # simplified

    # ── Strategy signals ──────────────────────────────────────────────────────

    @classmethod
    def strategy_entry(cls, id: str, direction: str = "long", **kwargs) -> None:
        cls.signals.append({"action": "entry", "id": id, "direction": direction, **kwargs})

    @classmethod
    def strategy_exit(cls, id: str, from_entry: str = "", **kwargs) -> None:
        cls.signals.append({"action": "exit", "id": id, "from_entry": from_entry, **kwargs})

    @classmethod
    def strategy_close(cls, id: str, **kwargs) -> None:
        cls.signals.append({"action": "close", "id": id, **kwargs})

    @classmethod
    def strategy_close_all(cls, **kwargs) -> None:
        cls.signals.append({"action": "close_all", **kwargs})

    # ── Plot stubs (no-op) ────────────────────────────────────────────────────

    @staticmethod
    def plot(*args, **kwargs) -> None:
        pass

    @staticmethod
    def plotshape(*args, **kwargs) -> None:
        pass

    @staticmethod
    def hline(*args, **kwargs) -> None:
        pass

    @staticmethod
    def bgcolor(*args, **kwargs) -> None:
        pass

    @staticmethod
    def label_new(*args, **kwargs) -> None:
        pass

    @staticmethod
    def line_new(*args, **kwargs) -> None:
        pass

    # ── Input stubs ───────────────────────────────────────────────────────────

    @staticmethod
    def input_bool(defval=True, title="", **kwargs) -> bool:
        return defval

    @staticmethod
    def input_int(defval=0, title="", **kwargs) -> int:
        return defval

    @staticmethod
    def input_float(defval=0.0, title="", **kwargs) -> float:
        return defval

    @staticmethod
    def input_string(defval="", title="", **kwargs) -> str:
        return defval

    @staticmethod
    def input_source(defval=None, title="", **kwargs):
        return defval


# ══════════════════════════════════════════════════════════════════════════════
#  Pine Script Service — loads .pine files from /strategies
# ══════════════════════════════════════════════════════════════════════════════

class PineScriptService:
    """
    Loads, transpiles, and executes .pine strategy files.
    Strategies are parsed from the /strategies directory.
    """

    def __init__(self, strategies_dir: str = "strategies") -> None:
        self.strategies_dir = Path(strategies_dir)
        self.parser = PineScriptParser()
        self._cache: Dict[str, str] = {}

    def load_strategy(self, filename: str) -> Optional[str]:
        """Load and transpile a .pine file to Python code."""
        if filename in self._cache:
            return self._cache[filename]

        path = self.strategies_dir / filename
        if not path.exists():
            print(f"[PineService] Strategy not found: {path}")
            return None

        try:
            pine_code = path.read_text(encoding="utf-8")
            python_code = self.parser.transpile(pine_code)
            self._cache[filename] = python_code
            print(f"[PineService] Transpiled: {filename}")
            return python_code
        except Exception as e:
            print(f"[PineService] Error transpiling {filename}: {e}")
            return None

    def list_strategies(self) -> List[str]:
        """List all .pine files in the strategies directory."""
        if not self.strategies_dir.exists():
            return []
        return [f.name for f in self.strategies_dir.glob("*.pine")]

    def execute_strategy(
        self,
        filename: str,
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a transpiled Pine Script strategy against market data.
        Returns generated signals.
        """
        python_code = self.load_strategy(filename)
        if python_code is None:
            return {"error": f"Strategy not found: {filename}"}

        # Reset signal buffer
        PineStdLib.signals = []

        # Execution namespace
        close  = market_data.get("close",  [])
        high   = market_data.get("high",   close)
        low    = market_data.get("low",    close)
        open_  = market_data.get("open",   close)
        volume = market_data.get("volume", [0.0] * len(close))

        namespace: Dict[str, Any] = {
            "__builtins__": {
                "abs": abs, "max": max, "min": min, "len": len,
                "range": range, "int": int, "float": float, "bool": bool, "str": str,
                "print": print, "round": round, "True": True, "False": False, "None": None,
            },
            "math":    math,
            "_pine":   PineStdLib,
            "close":   close,
            "high":    high,
            "low":     low,
            "open":    open_,
            "volume":  volume,
            "barstate": type("_bs", (), {"islast": True, "isconfirmed": True})(),
        }

        try:
            exec(python_code, namespace)
            signals = PineStdLib.signals.copy()
            return {
                "signals": signals,
                "signal_count": len(signals),
                "last_signal": signals[-1] if signals else None,
            }
        except Exception as e:
            return {"error": f"Execution error: {e}", "signals": []}


__all__ = ["PineScriptParser", "PineScriptService", "PineStdLib"]
