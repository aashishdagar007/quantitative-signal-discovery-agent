/**
 * AI Trading System — Security Profiler Implementation
 * C++17 compatible.
 */

#include "security_profiler.h"
#include <iomanip>
#include <sstream>

// ── Global singleton definition (ONE definition rule) ────────────────────────
SecurityProfiler g_security_profiler;

// ── summary_json implementation ──────────────────────────────────────────────

std::string SecurityProfiler::summary_json() const {
    SecurityState state = get_current_state();

    std::ostringstream oss;
    oss << "{"
        << "\"state\":\"" << security_state_name(state) << "\","
        << "\"anomaly_count\":" << anomaly_count() << ","
        << "\"active_leaks\":" << active_leak_count() << ","
        << "\"bytes_in_flight\":" << bytes_in_flight()
        << "}";
    return oss.str();
}