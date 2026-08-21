/**
 * AI Trading System — Security Profiler Test Harness
 * Demonstrates HFT loop anomaly detection, memory tracking, and state transitions.
 */

#include "security_profiler.h"
#include <cassert>
#include <iostream>
#include <thread>
#include <chrono>

int main() {
    std::cout << "=== AI Trading System — Security Profiler Test ===\n\n";

    // ── State transitions ─────────────────────────────────────────────────────
    std::cout << "Initial state: "
              << security_state_name(g_security_profiler.get_current_state()) << "\n";

    g_security_profiler.transition_state(SecurityState::WARNING);
    assert(g_security_profiler.get_current_state() == SecurityState::WARNING);
    std::cout << "After WARNING transition: "
              << security_state_name(g_security_profiler.get_current_state()) << "\n";

    g_security_profiler.transition_state(SecurityState::HEALTHY);

    // ── Anomaly reporting ─────────────────────────────────────────────────────
    std::cout << "\nReporting anomalies...\n";
    REPORT_ANOMALY(EXECUTION_DEVIATION, "Test deviation anomaly", 0.3);
    std::cout << "Anomaly count: " << g_security_profiler.anomaly_count() << "\n";

    REPORT_ANOMALY(PRICE_MANIPULATION, "Suspicious price spike detected", 0.8);
    std::cout << "State after critical anomaly: "
              << security_state_name(g_security_profiler.get_current_state()) << "\n";

    // ── Memory tracking ───────────────────────────────────────────────────────
    std::cout << "\nTesting memory tracking...\n";
    char* test_buf = new char[1024];
    TRACK_MEMORY(test_buf, 1024, "security_main.cpp:main");
    std::cout << "Bytes in flight: " << g_security_profiler.bytes_in_flight() << "\n";
    UNTRACK_MEMORY(test_buf);
    delete[] test_buf;
    std::cout << "After free — bytes in flight: " << g_security_profiler.bytes_in_flight() << "\n";

    // ── HFT timer ─────────────────────────────────────────────────────────────
    std::cout << "\nHFT latency test (simulating slow op)...\n";
    {
        HFT_TIMER("order_placement");
        std::this_thread::sleep_for(std::chrono::milliseconds(2));  // 2ms — should trigger anomaly
    }

    // ── Execution monitoring ──────────────────────────────────────────────────
    std::cout << "\nMonitoring execution...\n";
    MONITOR_EXECUTION("ord_001", 65100.0, 65000.0, 0.154);  // 0.154% — OK
    MONITOR_EXECUTION("ord_002", 65500.0, 65000.0, 0.769);  // 0.769% — anomaly

    // ── Summary ───────────────────────────────────────────────────────────────
    std::cout << "\n=== Summary ===\n";
    std::cout << g_security_profiler.summary_json() << "\n";
    std::cout << "Total anomalies: " << g_security_profiler.anomaly_count() << "\n";
    std::cout << "Active leaks:    " << g_security_profiler.active_leak_count() << "\n";
    std::cout << "\nAll tests passed.\n";

    return 0;
}
