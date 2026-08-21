#pragma once

/**
 * AI Trading System — C++ Security Behavior Profiler
 * C++17 compatible. Tracks security state changes, prevents memory leaks
 * in the HFT loop, and monitors execution anomalies.
 *
 * Usage:
 *   #include "security_profiler.h"
 *   SECURITY_TRANSITION(WARNING);
 *   REPORT_ANOMALY(EXECUTION_DEVIATION, "Slippage > 0.5%", 0.6);
 *   TRACK_MEMORY(ptr, size, "execution_engine.cpp:142");
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <ctime>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

// ─────────────────────────────────────────────────────────────────────────────
//  Security State Enum
// ─────────────────────────────────────────────────────────────────────────────

enum class SecurityState : int {
    HEALTHY   = 0,
    WARNING   = 1,
    CRITICAL  = 2,
    SHUTDOWN  = 3
};

inline const char* security_state_name(SecurityState s) {
    switch (s) {
        case SecurityState::HEALTHY:  return "HEALTHY";
        case SecurityState::WARNING:  return "WARNING";
        case SecurityState::CRITICAL: return "CRITICAL";
        case SecurityState::SHUTDOWN: return "SHUTDOWN";
        default:                      return "UNKNOWN";
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Anomaly Type Enum
// ─────────────────────────────────────────────────────────────────────────────

enum class AnomalyType : int {
    MEMORY_LEAK         = 0,
    EXECUTION_DEVIATION = 1,
    PRICE_MANIPULATION  = 2,
    UNAUTHORIZED_ORDER  = 3,
    RATE_LIMIT_EXCEEDED = 4,
    CONSENSUS_FAILURE   = 5,
    UNKNOWN             = 6
};

inline const char* anomaly_type_name(AnomalyType t) {
    switch (t) {
        case AnomalyType::MEMORY_LEAK:          return "MEMORY_LEAK";
        case AnomalyType::EXECUTION_DEVIATION:  return "EXECUTION_DEVIATION";
        case AnomalyType::PRICE_MANIPULATION:   return "PRICE_MANIPULATION";
        case AnomalyType::UNAUTHORIZED_ORDER:   return "UNAUTHORIZED_ORDER";
        case AnomalyType::RATE_LIMIT_EXCEEDED:  return "RATE_LIMIT_EXCEEDED";
        case AnomalyType::CONSENSUS_FAILURE:    return "CONSENSUS_FAILURE";
        default:                                 return "UNKNOWN";
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  SecurityAnomaly record
// ─────────────────────────────────────────────────────────────────────────────

struct SecurityAnomaly {
    uint64_t                              id;
    AnomalyType                           type;
    std::string                           description;
    std::chrono::system_clock::time_point timestamp;
    double                                severity;   // [0.0, 1.0]
    bool                                  auto_resolved;

    // C++17 explicit constructor (no designated initializers)
    SecurityAnomaly(
        uint64_t    _id,
        AnomalyType _type,
        std::string _desc,
        double      _severity
    )
        : id(_id),
          type(_type),
          description(std::move(_desc)),
          timestamp(std::chrono::system_clock::now()),
          severity(_severity),
          auto_resolved(false)
    {}
};

// ─────────────────────────────────────────────────────────────────────────────
//  StateTransition record
// ─────────────────────────────────────────────────────────────────────────────

struct StateTransition {
    SecurityState                         from;
    SecurityState                         to;
    std::chrono::system_clock::time_point timestamp;

    StateTransition(SecurityState f, SecurityState t)
        : from(f), to(t), timestamp(std::chrono::system_clock::now())
    {}
};

// ─────────────────────────────────────────────────────────────────────────────
//  MemoryEntry record
// ─────────────────────────────────────────────────────────────────────────────

struct MemoryEntry {
    uintptr_t                             pointer;
    size_t                                size;
    std::string                           location;
    std::chrono::system_clock::time_point allocated_at;
    std::chrono::system_clock::time_point freed_at;
    bool                                  freed;

    MemoryEntry(uintptr_t p, size_t s, std::string loc)
        : pointer(p), size(s), location(std::move(loc)),
          allocated_at(std::chrono::system_clock::now()),
          freed(false)
    {}
};

// ─────────────────────────────────────────────────────────────────────────────
//  ExecutionAnomalyRecord
// ─────────────────────────────────────────────────────────────────────────────

struct ExecutionAnomalyRecord {
    std::string                           order_id;
    double                                executed_price;
    double                                expected_price;
    double                                deviation_pct;
    std::chrono::system_clock::time_point timestamp;

    ExecutionAnomalyRecord(
        std::string oid, double exec, double exp, double dev
    )
        : order_id(std::move(oid)),
          executed_price(exec),
          expected_price(exp),
          deviation_pct(dev),
          timestamp(std::chrono::system_clock::now())
    {}
};

// ─────────────────────────────────────────────────────────────────────────────
//  SecurityProfiler — main class
// ─────────────────────────────────────────────────────────────────────────────

class SecurityProfiler {
public:
    SecurityProfiler() = default;
    ~SecurityProfiler() = default;

    // Non-copyable
    SecurityProfiler(const SecurityProfiler&)            = delete;
    SecurityProfiler& operator=(const SecurityProfiler&) = delete;

    // ── State management ────────────────────────────────────────────────────

    void transition_state(SecurityState new_state) {
        std::lock_guard<std::mutex> lock(state_mutex_);
        SecurityState old_state = current_state_.load(std::memory_order_acquire);
        if (old_state == new_state) return;

        current_state_.store(new_state, std::memory_order_release);
        state_history_.emplace_back(old_state, new_state);

        log_state_change(old_state, new_state);
    }

    SecurityState get_current_state() const {
        return current_state_.load(std::memory_order_acquire);
    }

    // ── Anomaly reporting ────────────────────────────────────────────────────

    void report_anomaly(AnomalyType type, const std::string& description, double severity = 1.0) {
        uint64_t id = ++anomaly_counter_;
        auto anomaly = std::make_shared<SecurityAnomaly>(id, type, description, severity);

        {
            std::lock_guard<std::mutex> lock(anomaly_mutex_);
            anomaly_history_.push_back(anomaly);
        }

        // Automatic state escalation
        SecurityState current = get_current_state();
        if (severity >= 0.7 && current != SecurityState::CRITICAL && current != SecurityState::SHUTDOWN) {
            transition_state(SecurityState::CRITICAL);
        } else if (severity >= 0.3 && current == SecurityState::HEALTHY) {
            transition_state(SecurityState::WARNING);
        }

        log_anomaly(*anomaly);
    }

    // ── Memory tracking ───────────────────────────────────────────────────────

    void track_memory(void* ptr, size_t size, const std::string& location) {
        std::lock_guard<std::mutex> lock(memory_mutex_);
        uintptr_t addr = reinterpret_cast<uintptr_t>(ptr);
        memory_tracker_.emplace(addr, MemoryEntry(addr, size, location));
        total_allocated_.fetch_add(size, std::memory_order_relaxed);
    }

    void untrack_memory(void* ptr) {
        std::lock_guard<std::mutex> lock(memory_mutex_);
        uintptr_t addr = reinterpret_cast<uintptr_t>(ptr);
        auto it = memory_tracker_.find(addr);
        if (it != memory_tracker_.end()) {
            total_freed_.fetch_add(it->second.size, std::memory_order_relaxed);
            check_memory_leak(it->second);
            memory_tracker_.erase(it);
        }
    }

    // ── Execution monitoring ──────────────────────────────────────────────────

    void monitor_execution(
        const std::string& order_id,
        double executed_price,
        double expected_price,
        double deviation_pct
    ) {
        {
            std::lock_guard<std::mutex> lock(exec_mutex_);
            exec_anomalies_.emplace_back(order_id, executed_price, expected_price, deviation_pct);
        }

        if (deviation_pct > 0.5) {
            std::string desc = "Execution deviation: " + order_id +
                               " dev=" + std::to_string(deviation_pct) + "%";
            report_anomaly(AnomalyType::EXECUTION_DEVIATION, desc, deviation_pct / 100.0);
        }
    }

    // ── HFT loop safety check ─────────────────────────────────────────────────

    void hft_safety_check(const std::string& operation, uint64_t duration_ns) {
        constexpr uint64_t HFT_LATENCY_BUDGET_NS = 1'000'000ULL;  // 1 ms
        if (duration_ns > HFT_LATENCY_BUDGET_NS) {
            std::string desc = "HFT operation exceeded latency budget: " + operation +
                               " took " + std::to_string(duration_ns / 1'000) + " µs";
            report_anomaly(AnomalyType::EXECUTION_DEVIATION, desc,
                           static_cast<double>(duration_ns) / 10'000'000.0);
        }
    }

    // ── Accessors ─────────────────────────────────────────────────────────────

    size_t anomaly_count() const {
        std::lock_guard<std::mutex> lock(anomaly_mutex_);
        return anomaly_history_.size();
    }

    size_t active_leak_count() const {
        std::lock_guard<std::mutex> lock(memory_mutex_);
        return memory_tracker_.size();
    }

    size_t bytes_in_flight() const {
        return total_allocated_.load(std::memory_order_relaxed) -
               total_freed_.load(std::memory_order_relaxed);
    }

    std::string summary_json() const;

private:
    // ── Internal helpers ──────────────────────────────────────────────────────

    void check_memory_leak(const MemoryEntry& entry) {
        auto now      = std::chrono::system_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::seconds>(
            now - entry.allocated_at
        ).count();

        if (duration > 3600 && entry.size > 1024) {
            std::string desc = "Potential leak: " + std::to_string(entry.size) +
                               " bytes at " + entry.location +
                               " for " + std::to_string(duration) + "s";
            // Can't call report_anomaly (mutex re-entrancy) — log directly
            thread_safe_log("[LEAK] " + desc);
        }
    }

    static void thread_safe_log(const std::string& msg) {
        static std::mutex s_log_mutex;
        std::lock_guard<std::mutex> lock(s_log_mutex);
        auto t = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        char buf[32];
        struct tm tm_info;
#ifdef _WIN32
        localtime_s(&tm_info, &t);
#else
        localtime_r(&t, &tm_info);
#endif
        strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm_info);
        std::cerr << "[" << buf << "] " << msg << "\n";
    }

    void log_state_change(SecurityState from, SecurityState to) {
        std::ostringstream oss;
        oss << "[SecurityProfiler] State: "
            << security_state_name(from) << " -> "
            << security_state_name(to);
        thread_safe_log(oss.str());
    }

    void log_anomaly(const SecurityAnomaly& a) {
        std::ostringstream oss;
        oss << "[SecurityProfiler] ANOMALY[" << anomaly_type_name(a.type) << "]"
            << " id=" << a.id
            << " severity=" << a.severity
            << " desc=" << a.description;
        thread_safe_log(oss.str());
    }

    // ── State ──────────────────────────────────────────────────────────────────
    std::atomic<SecurityState> current_state_{SecurityState::HEALTHY};
    mutable std::mutex         state_mutex_;
    std::vector<StateTransition> state_history_;

    // ── Anomalies ──────────────────────────────────────────────────────────────
    std::atomic<uint64_t>                        anomaly_counter_{0};
    mutable std::mutex                           anomaly_mutex_;
    std::vector<std::shared_ptr<SecurityAnomaly>> anomaly_history_;

    // ── Memory ────────────────────────────────────────────────────────────────
    mutable std::mutex                            memory_mutex_;
    std::unordered_map<uintptr_t, MemoryEntry>    memory_tracker_;
    std::atomic<size_t>                           total_allocated_{0};
    std::atomic<size_t>                           total_freed_{0};

    // ── Execution ─────────────────────────────────────────────────────────────
    mutable std::mutex                     exec_mutex_;
    std::vector<ExecutionAnomalyRecord>    exec_anomalies_;
};

// ─────────────────────────────────────────────────────────────────────────────
//  Global instance declaration
// ─────────────────────────────────────────────────────────────────────────────

extern SecurityProfiler g_security_profiler;

// ─────────────────────────────────────────────────────────────────────────────
//  Convenience Macros
// ─────────────────────────────────────────────────────────────────────────────

#define SECURITY_TRANSITION(new_state) \
    g_security_profiler.transition_state(SecurityState::new_state)

#define REPORT_ANOMALY(type, desc, severity) \
    g_security_profiler.report_anomaly(AnomalyType::type, (desc), (severity))

#define TRACK_MEMORY(ptr, size, location) \
    g_security_profiler.track_memory((ptr), (size), (location))

#define UNTRACK_MEMORY(ptr) \
    g_security_profiler.untrack_memory(ptr)

#define MONITOR_EXECUTION(order_id, exec_price, exp_price, dev) \
    g_security_profiler.monitor_execution((order_id), (exec_price), (exp_price), (dev))

// ─────────────────────────────────────────────────────────────────────────────
//  RAII HFT Timer
// ─────────────────────────────────────────────────────────────────────────────

class HftScopedTimer {
public:
    explicit HftScopedTimer(std::string operation)
        : operation_(std::move(operation)),
          start_(std::chrono::high_resolution_clock::now())
    {}

    ~HftScopedTimer() {
        auto end      = std::chrono::high_resolution_clock::now();
        uint64_t ns   = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - start_).count()
        );
        g_security_profiler.hft_safety_check(operation_, ns);
    }

    uint64_t elapsed_ns() const {
        auto now = std::chrono::high_resolution_clock::now();
        return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(now - start_).count()
        );
    }

private:
    std::string                                         operation_;
    std::chrono::high_resolution_clock::time_point      start_;
};

#define HFT_TIMER(op) HftScopedTimer _hft_timer_##__LINE__((op))