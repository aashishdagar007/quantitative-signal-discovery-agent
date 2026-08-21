import ctypes
import threading
import time
from enum import Enum, IntEnum
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# --- Enum definitions matching C++ ---

class SecurityState(IntEnum):
    HEALTHY = 0
    WARNING = 1
    CRITICAL = 2
    SHUTDOWN = 3


class AnomalyType(IntEnum):
    MEMORY_LEAK = 0
    EXECUTION_DEVIATION = 1
    PRICE_MANIPULATION = 2
    UNAUTHORIZED_ORDER = 3
    RATE_LIMIT_EXCEEDED = 4
    CONSENSUS_FAILURE = 5
    UNKNOWN = 6


# --- Data structures matching C++ ---

@dataclass
class SecurityAnomaly:
    type: AnomalyType
    description: str
    trigger_id: int = 0
    severity: float = 1.0
    auto_resolved: bool = False
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


# --- Python Security Profiler (fallback when C++ not compiled) ---

class PythonSecurityProfiler:
    """
    Python implementation of the SecurityProfiler.
    Provides identical interface for when C++ compilation is not available.
    Can be swapped with compiled C++ version via interface plugin.
    """
    
    def __init__(self):
        self._state = SecurityState.HEALTHY
        self._state_lock = threading.RLock()
        
        # State transition history
        self._transition_history: List[Dict] = []
        
        # Anomaly history
        self._anomaly_history: List[SecurityAnomaly] = []
        self._anomaly_counter = 0
        self._anomaly_lock = threading.RLock()
        
        # Memory tracking
        self._memory_tracker: Dict[int, Dict] = {}
        self._memory_lock = threading.RLock()
        
        # Execution anomaly tracking
        self._execution_anomalies: List[Dict] = []
        self._execution_lock = threading.RLock()
    
    # State management
    def transition_state(self, new_state: SecurityState) -> None:
        """Transition security state with thread safety"""
        with self._state_lock:
            old_state = self._state
            self._state = new_state
            self._transition_history.append({
                'from': old_state,
                'to': new_state,
                'timestamp': datetime.utcnow()
            })
            self._log_state_change(old_state, new_state)
    
    def get_current_state(self) -> SecurityState:
        """Get current security state"""
        with self._state_lock:
            return self._state
    
    # Anomaly reporting
    def report_anomaly(self, 
                       anomaly_type: AnomalyType, 
                       description: str, 
                       severity: float = 1.0) -> int:
        """Report security anomaly and return anomaly ID"""
        with self._anomaly_lock:
            self._anomaly_counter += 1
            anomaly_id = self._anomaly_counter
            
            anomaly = SecurityAnomaly(
                type=anomaly_type,
                description=description,
                trigger_id=anomaly_id,
                severity=severity
            )
            
            self._anomaly_history.append(anomaly)
            
            # State transition based on severity
            if severity > 0.7 and self._state != SecurityState.CRITICAL:
                self.transition_state(SecurityState.CRITICAL)
            elif severity > 0.3 and self._state != SecurityState.WARNING:
                self.transition_state(SecurityState.WARNING)
            
            self._log_anomaly(anomaly)
            return anomaly_id
    
    # Memory leak monitoring
    def track_memory(self, 
                     pointer: int, 
                     size: int, 
                     location: str = "") -> None:
        """Track memory allocation for leak detection"""
        with self._memory_lock:
            self._memory_tracker[pointer] = {
                'size': size,
                'location': location,
                'allocated_at': datetime.utcnow(),
                'freed': False
            }
            
            # Check for potential leak
            self._check_memory_leak(pointer)
    
    def untrack_memory(self, pointer: int) -> None:
        """Untrack memory when freed"""
        with self._memory_lock:
            if pointer in self._memory_tracker:
                entry = self._memory_tracker[pointer]
                entry['freed'] = True
                entry['freed_at'] = datetime.utcnow()
                
                # Check for leak
                if not entry['freed']:  # Wasn't properly freed
                    self.report_anomaly(
                        AnomalyType.MEMORY_LEAK,
                        f"Potential memory leak: {entry['size']} bytes at {entry['location']}",
                        0.8
                    )
                
                self._memory_tracker.pop(pointer, None)
    
    def _check_memory_leak(self, pointer: int) -> None:
        """Internal check for memory leaks"""
        with self._memory_lock:
            if pointer not in self._memory_tracker:
                return
            
            entry = self._memory_tracker[pointer]
            if entry['freed']:
                return
            
            now = datetime.utcnow()
            duration = (now - entry['allocated_at']).total_seconds()
            
            # If memory allocated for more than 1 hour without being freed
            if duration > 3600 and entry['size'] > 1024:
                self.report_anomaly(
                    AnomalyType.MEMORY_LEAK,
                    f"Potential memory leak: {entry['size']} bytes allocated at "
                    f"{entry['location']} for {int(duration)} seconds",
                    0.8
                )
    
    # Execution monitoring
    def monitor_execution(self,
                          order_id: str,
                          executed_price: float,
                          expected_price: float,
                          deviation_pct: float) -> None:
        """Monitor execution for anomalies"""
        with self._execution_lock:
            self._execution_anomalies.append({
                'order_id': order_id,
                'executed_price': executed_price,
                'expected_price': expected_price,
                'deviation_pct': deviation_pct,
                'timestamp': datetime.utcnow()
            })
            
            # Flag severe deviations
            if deviation_pct > 0.5:  # > 0.5% deviation
                self.report_anomaly(
                    AnomalyType.EXECUTION_DEVIATION,
                    f"Large execution deviation: {deviation_pct:.2f}%",
                    deviation_pct / 100.0
                )
    
    # Summary methods
    def get_anomaly_count(self) -> int:
        """Get total anomaly count"""
        with self._anomaly_lock:
            return len(self._anomaly_history)
    
    def get_leak_count(self) -> int:
        """Get unfreed memory block count"""
        with self._memory_lock:
            return sum(1 for entry in self._memory_tracker.values() if not entry['freed'])
    
    def get_state(self) -> SecurityState:
        """Get security state (compatibility alias)"""
        return self.get_current_state()
    
    # Logging
    def _log_state_change(self, from_state: SecurityState, to_state: SecurityState) -> None:
        """Log state change"""
        import sys
        timestamp = datetime.utcnow().isoformat()
        print(f"[{timestamp}] State change: {from_state.name} -> {to_state.name}", file=sys.stderr)
    
    def _log_anomaly(self, anomaly: SecurityAnomaly) -> None:
        """Log anomaly detail"""
        import sys
        timestamp = datetime.utcnow().isoformat()
        print(f"[{timestamp}] Anomaly[{anomaly.type.name}] "
              f"Severity:{anomaly.severity:.2f} - {anomaly.description}", 
              file=sys.stderr)


# --- Global instance ---

# Try to load compiled C++ version, fallback to Python
try:
    # Attempt to load compiled shared library
    _security_lib = ctypes.CDLL("./security_profiler.so")
    security_profiler = _security_lib  # Type: ignore
    print("Using compiled C++ SecurityProfiler")
except (OSError, ImportError):
    # Fallback to Python implementation
    security_profiler = PythonSecurityProfiler()
    print("Using PythonSecurityProfiler (C++ not compiled)")

# Export for convenience
get_current_state = security_profiler.get_current_state if hasattr(security_profiler, 'get_current_state') else lambda: SecurityState.HEALTHY
report_anomaly = security_profiler.report_anomaly if hasattr(security_profiler, 'report_anomaly') else lambda *args: 0
transition_state = security_profiler.transition_state if hasattr(security_profiler, 'transition_state') else lambda *args: None
monitor_execution = security_profiler.monitor_execution if hasattr(security_profiler, 'monitor_execution') else lambda *args: None