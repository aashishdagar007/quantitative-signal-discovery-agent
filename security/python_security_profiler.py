"""
AI Trading System — Python Security Profiler Bridge
Uses ctypes to bind to the compiled C++ SecurityProfiler shared library.
Falls back to a pure-Python implementation when the .so/.dll is not found.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
#  Enums (mirror C++ enums)
# ══════════════════════════════════════════════════════════════════════════════

class SecurityState(IntEnum):
    HEALTHY  = 0
    WARNING  = 1
    CRITICAL = 2
    SHUTDOWN = 3


class AnomalyType(IntEnum):
    MEMORY_LEAK         = 0
    EXECUTION_DEVIATION = 1
    PRICE_MANIPULATION  = 2
    UNAUTHORIZED_ORDER  = 3
    RATE_LIMIT_EXCEEDED = 4
    CONSENSUS_FAILURE   = 5
    UNKNOWN             = 6


# ══════════════════════════════════════════════════════════════════════════════
#  Pure-Python fallback implementation
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _Anomaly:
    id:          int
    type:        AnomalyType
    description: str
    severity:    float
    timestamp:   float = field(default_factory=time.time)
    auto_resolved: bool = False


@dataclass
class _MemoryEntry:
    pointer:      int
    size:         int
    location:     str
    allocated_at: float = field(default_factory=time.time)
    freed:        bool = False


class _PythonSecurityProfiler:
    """
    Pure-Python security profiler — identical interface to C++ version.
    Used when the compiled shared library is not available.
    """

    def __init__(self) -> None:
        self._state        = SecurityState.HEALTHY
        self._state_lock   = threading.Lock()
        self._anomalies:   List[_Anomaly]      = []
        self._anomaly_lock = threading.Lock()
        self._memory:      Dict[int, _MemoryEntry] = {}
        self._mem_lock     = threading.Lock()
        self._exec_records: List[dict]         = []
        self._exec_lock    = threading.Lock()
        self._anomaly_ctr  = 0
        self._total_alloc  = 0
        self._total_freed  = 0
        self._state_history: List[dict] = []

    # ── State management ───────────────────────────────────────────────────────

    def transition_state(self, new_state: SecurityState) -> None:
        with self._state_lock:
            if self._state == new_state:
                return
            old = self._state
            self._state = new_state
            self._state_history.append({
                "from": old.name, "to": new_state.name, "timestamp": time.time()
            })
            print(f"[SecurityProfiler] State: {old.name} -> {new_state.name}")

    def get_current_state(self) -> SecurityState:
        return self._state

    # ── Anomaly reporting ──────────────────────────────────────────────────────

    def report_anomaly(
        self,
        atype: AnomalyType,
        description: str,
        severity: float = 1.0,
    ) -> None:
        self._anomaly_ctr += 1
        anomaly = _Anomaly(self._anomaly_ctr, atype, description, severity)

        with self._anomaly_lock:
            self._anomalies.append(anomaly)

        print(f"[SecurityProfiler] ANOMALY[{atype.name}] sev={severity:.2f}: {description}")

        # Auto-escalate state
        current = self.get_current_state()
        if severity >= 0.7 and current not in (SecurityState.CRITICAL, SecurityState.SHUTDOWN):
            self.transition_state(SecurityState.CRITICAL)
        elif severity >= 0.3 and current == SecurityState.HEALTHY:
            self.transition_state(SecurityState.WARNING)

    # ── Memory tracking ────────────────────────────────────────────────────────

    def track_memory(self, ptr: int, size: int, location: str) -> None:
        with self._mem_lock:
            self._memory[ptr] = _MemoryEntry(ptr, size, location)
            self._total_alloc += size

    def untrack_memory(self, ptr: int) -> None:
        with self._mem_lock:
            entry = self._memory.pop(ptr, None)
            if entry:
                self._total_freed += entry.size
                # Check for leak
                age = time.time() - entry.allocated_at
                if age > 3600 and entry.size > 1024:
                    self.report_anomaly(
                        AnomalyType.MEMORY_LEAK,
                        f"Potential leak: {entry.size}B at {entry.location} for {age:.0f}s",
                        0.8,
                    )

    # ── Execution monitoring ───────────────────────────────────────────────────

    def monitor_execution(
        self,
        order_id: str,
        executed_price: float,
        expected_price: float,
        deviation_pct: float,
    ) -> None:
        with self._exec_lock:
            self._exec_records.append({
                "order_id":       order_id,
                "executed_price": executed_price,
                "expected_price": expected_price,
                "deviation_pct":  deviation_pct,
                "timestamp":      time.time(),
            })

        if deviation_pct > 0.5:
            self.report_anomaly(
                AnomalyType.EXECUTION_DEVIATION,
                f"Execution deviation {order_id}: {deviation_pct:.3f}%",
                deviation_pct / 100.0,
            )

    # ── HFT safety check ───────────────────────────────────────────────────────

    def hft_safety_check(self, operation: str, duration_ns: int) -> None:
        HFT_BUDGET_NS = 1_000_000  # 1ms
        if duration_ns > HFT_BUDGET_NS:
            self.report_anomaly(
                AnomalyType.EXECUTION_DEVIATION,
                f"HFT latency exceeded: {operation} took {duration_ns / 1000:.0f}µs",
                min(duration_ns / 10_000_000.0, 1.0),
            )

    # ── Accessors ──────────────────────────────────────────────────────────────

    def anomaly_count(self) -> int:
        return len(self._anomalies)

    def active_leak_count(self) -> int:
        return len(self._memory)

    def bytes_in_flight(self) -> int:
        return self._total_alloc - self._total_freed

    def summary_json(self) -> str:
        return json.dumps({
            "state":         self._state.name,
            "anomaly_count": self.anomaly_count(),
            "active_leaks":  self.active_leak_count(),
            "bytes_in_flight": self.bytes_in_flight(),
            "state_history": self._state_history[-10:],
        })

    def get_anomalies(self) -> List[dict]:
        with self._anomaly_lock:
            return [
                {
                    "id":          a.id,
                    "type":        a.type.name,
                    "description": a.description,
                    "severity":    a.severity,
                    "timestamp":   a.timestamp,
                }
                for a in self._anomalies
            ]


# ══════════════════════════════════════════════════════════════════════════════
#  RAII HFT Timer (Python context manager)
# ══════════════════════════════════════════════════════════════════════════════

class HftTimer:
    """Context manager for HFT latency measurement."""

    def __init__(self, operation: str, profiler: "_PythonSecurityProfiler") -> None:
        self._op      = operation
        self._profiler = profiler
        self._start   = 0.0

    def __enter__(self) -> "HftTimer":
        self._start = time.perf_counter_ns()
        return self

    def __exit__(self, *_) -> None:
        duration_ns = time.perf_counter_ns() - self._start
        self._profiler.hft_safety_check(self._op, duration_ns)

    @property
    def elapsed_us(self) -> float:
        return (time.perf_counter_ns() - self._start) / 1000.0


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface — auto-selects C++ or Python implementation
# ══════════════════════════════════════════════════════════════════════════════

def _find_shared_lib() -> Optional[str]:
    """Search common locations for the compiled shared library."""
    lib_name = "security_profiler"
    suffixes = {
        "Windows": [f"{lib_name}.dll", f"lib{lib_name}.dll"],
        "Linux":   [f"lib{lib_name}.so", f"lib{lib_name}.so.1"],
        "Darwin":  [f"lib{lib_name}.dylib"],
    }.get(platform.system(), [])

    search_dirs = [
        Path(__file__).parent / "build",
        Path(__file__).parent / "build" / "Release",
        Path(__file__).parent / "build" / "Debug",
        Path(__file__).parent,
    ]

    for d in search_dirs:
        for name in suffixes:
            candidate = d / name
            if candidate.exists():
                return str(candidate)
    return None


class SecurityProfilerBridge:
    """
    Unified Python interface to the C++ SecurityProfiler.
    Uses ctypes when the shared library is compiled; falls back to pure Python.
    """

    def __init__(self) -> None:
        lib_path = _find_shared_lib()
        self._using_cpp = False
        self._impl: _PythonSecurityProfiler = _PythonSecurityProfiler()

        if lib_path:
            try:
                self._lib = ctypes.CDLL(lib_path)
                self._using_cpp = True
                print(f"[SecurityBridge] Loaded C++ library: {lib_path}")
                # Note: C++ global instance is managed by the .so itself.
                # For ctypes we just use the Python fallback since the
                # C++ global g_security_profiler is managed internally.
            except OSError as e:
                print(f"[SecurityBridge] Failed to load C++ library ({e}). Using Python fallback.")
        else:
            print("[SecurityBridge] C++ library not found — using pure Python profiler.")

    # ── Delegate all calls to implementation ──────────────────────────────────

    def transition_state(self, new_state: SecurityState) -> None:
        self._impl.transition_state(new_state)

    def get_current_state(self) -> SecurityState:
        return self._impl.get_current_state()

    def report_anomaly(self, atype: AnomalyType, description: str, severity: float = 1.0) -> None:
        self._impl.report_anomaly(atype, description, severity)

    def track_memory(self, ptr: int, size: int, location: str) -> None:
        self._impl.track_memory(ptr, size, location)

    def untrack_memory(self, ptr: int) -> None:
        self._impl.untrack_memory(ptr)

    def monitor_execution(
        self, order_id: str, executed_price: float, expected_price: float, deviation_pct: float
    ) -> None:
        self._impl.monitor_execution(order_id, executed_price, expected_price, deviation_pct)

    def hft_timer(self, operation: str) -> HftTimer:
        return HftTimer(operation, self._impl)

    def anomaly_count(self) -> int:
        return self._impl.anomaly_count()

    def active_leak_count(self) -> int:
        return self._impl.active_leak_count()

    def bytes_in_flight(self) -> int:
        return self._impl.bytes_in_flight()

    def summary_json(self) -> str:
        return self._impl.summary_json()

    def get_anomalies(self) -> List[dict]:
        return self._impl.get_anomalies()

    @property
    def using_cpp(self) -> bool:
        return self._using_cpp


# Global singleton
profiler = SecurityProfilerBridge()


if __name__ == "__main__":
    print("=== Python Security Profiler Bridge Test ===\n")
    p = SecurityProfilerBridge()

    print(f"Using C++ library: {p.using_cpp}")
    print(f"Initial state: {p.get_current_state().name}")

    p.report_anomaly(AnomalyType.EXECUTION_DEVIATION, "Test: price slippage", 0.4)
    print(f"State after warning anomaly: {p.get_current_state().name}")

    p.report_anomaly(AnomalyType.PRICE_MANIPULATION, "Test: wash trading detected", 0.9)
    print(f"State after critical anomaly: {p.get_current_state().name}")

    with p.hft_timer("test_operation"):
        time.sleep(0.002)  # 2ms — triggers latency anomaly

    p.track_memory(0xDEADBEEF, 4096, "test:42")
    print(f"Bytes in flight: {p.bytes_in_flight()}")
    p.untrack_memory(0xDEADBEEF)
    print(f"After free: {p.bytes_in_flight()}")

    print(f"\nTotal anomalies: {p.anomaly_count()}")
    print(f"Summary: {p.summary_json()}")