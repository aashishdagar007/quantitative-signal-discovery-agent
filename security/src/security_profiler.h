#pragma once

#include <atomic>
#include <mutex>
#include <unordered_map>
#include <vector>
#include <string>
#include <chrono>
#include <thread>
#include <cstdint>
#include <iostream>

// --- Security State Enums ---

enum class SecurityState {
    HEALTHY,
    WARNING,
    CRITICAL,
    SHUTDOWN
};

enum class AnomalyType {
    MEMORY_LEAK,
    EXECUTION_DEVIATION,
    PRICE_MANIPULATION,
    UNAUTHORIZED_ORDER,
    RATE_LIMIT_EXCEEDED,
    CONSENSUS_FAILURE,
    UNKNOWN
};

// --- Security Anomaly Record ---

struct SecurityAnomaly {
    AnomalyType type;
    std::string description;
    std::chrono::system_clock::time_point timestamp;
    uint64_t trigger_id;
    double severity; // 0.0 - 1.0
    bool auto_resolved;
    
    SecurityAnomaly(AnomalyType t, const std::string& desc, 
                    uint64_t id, double severity_val = 1.0)
        : type(t), description(desc), trigger_id(id), 
          severity(severity_val), auto_resolved(false) {
        timestamp = std::chrono::system_clock::now();
    }
};

// --- Security State Tracker Class ---

class SecurityProfiler {
public:
    SecurityProfiler() = default;
    
    // Track state transitions
    void transition_state(SecurityState new_state) {
        std::lock_guard<std::mutex> lock(state_mutex_);
        auto old_state = current_state_.load();
        state_transition_history_.push_back({
            .from = old_state,
            .to = new_state,
            .timestamp = std::chrono::system_clock::now()
        });
        current_state_.store(new_state);
        log_state_change(old_state, new_state);
    }
    
    SecurityState get_current_state() const {
        std::lock_guard<std::mutex> lock(state_mutex_);
        return current_state_.load();
    }
    
    // Report anomalies
    void report_anomaly(AnomalyType type, const std::string& description, 
                        double severity = 1.0) {
        std::lock_guard<std::mutex> lock(anomaly_mutex_);
        
        uint64_t anomaly_id = ++anomaly_counter_;
        auto anomaly = std::make_shared<SecurityAnomaly>(
            type, description, anomaly_id, severity
        );
        
        anomaly_history_.push_back(anomaly);
        
        // Check if state transition needed
        SecurityState current = get_current_state();
        if (severity > 0.7 && current != SecurityState::CRITICAL) {
            transition_state(SecurityState::CRITICAL);
        } else if (severity > 0.3 && current != SecurityState::WARNING) {
            transition_state(SecurityState::WARNING);
        }
        
        log_anomaly(anomaly);
    }
    
    // Memory leak monitoring
    void track_memory(void* pointer, size_t size, const std::string& location) {
        std::lock_guard<std::mutex> lock(memory_mutex_);
        
        MemoryEntry entry;
        entry.pointer = reinterpret_cast<uintptr_t>(pointer);
        entry.size = size;
        entry.location = location;
        entry.allocated_at = std::chrono::system_clock::now();
        entry.freed = false;
        
        memory_tracker_[reinterpret_cast<uint64_t>(pointer)] = entry;
        total_allocated_.fetch_add(size, std::memory_order_relaxed);
    }
    
    void untrack_memory(void* pointer) {
        std::lock_guard<std::mutex> lock(memory_mutex_);
        auto it = memory_tracker_.find(reinterpret_cast<uint64_t>(pointer));
        if (it != memory_tracker_.end()) {
            it->second.freed = true;
            it->second.freed_at = std::chrono::system_clock::now();
            total_freed_.fetch_add(it->second.size, std::memory_order_relaxed);
            
            // Check for leak
            check_memory_leak(it->second);
            memory_tracker_.erase(it);
        }
    }
    
    // Execution anomaly monitoring
    void monitor_execution(const std::string& order_id, double executed_price,
                          double expected_price, double deviation_pct) {
        std::lock_guard<std::mutex> lock(execution_mutex_);
        
        execution_anomalies_.push_back({
            .order_id = order_id,
            .executed_price = executed_price,
            .expected_price = expected_price,
            .deviation_pct = deviation_pct,
            .timestamp = std::chrono::system_clock::now()
        });
        
        // Flag severe deviations
        if (deviation_pct > 0.5) {  // > 0.5% deviation
            report_anomaly(AnomalyType::EXECUTION_DEVIATION,
                          "Large execution deviation: " + 
                          std::to_string(deviation_pct) + "%",
                          deviation_pct / 100.0);
        }
    }
    
    // Get anomaly summary
    size_t get_anomaly_count() const {
        std::lock_guard<std::mutex> lock(anomaly_mutex_);
        return anomaly_history_.size();
    }
    
    size_t get_leak_count() const {
        std::lock_guard<std::mutex> lock(memory_mutex_);
        size_t leak_count = 0;
        for (const auto& [addr, entry] : memory_tracker_) {
            if (!entry.freed) {
                leak_count++;
            }
        }
        return leak_count;
    }
    
    SecurityState get_state() const { return get_current_state(); }
    
private:
    // Check for memory leaks
    void check_memory_leak(const MemoryEntry& entry) {
        auto now = std::chrono::system_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::seconds>(
            now - entry.allocated_at
        ).count();
        
        // If memory allocated for more than 3600 seconds (1 hour) without being freed
        if (duration > 3600 && entry.size > 1024) {
            report_anomaly(AnomalyType::MEMORY_LEAK,
                          "Potential memory leak: " + std::to_string(entry.size) + 
                          " bytes allocated at " + entry.location + 
                          " for " + std::to_string(duration) + " seconds",
                          0.8);
        }
    }
    
    // Log state change
    void log_state_change(SecurityState from, SecurityState to) {
        auto now = std::chrono::system_clock::now();
        auto time_t_now = std::chrono::system_clock::to_time_t(now);
        std::cout << "[" << std::ctime(&time_t_now) 
                  << "] State change: " << 
                  static_cast<int>(from) << " -> " << 
                  static_cast<int>(to) << std::endl;
    }
    
    // Log anomaly
    void log_anomaly(const std::shared_ptr<SecurityAnomaly>& anomaly) {
        auto now = std::chrono::system_clock::now();
        auto time_t_now = std::chrono::system_clock::to_time_t(now);
        std::cout << "[" << std::ctime(&time_t_now) 
                  << "] Anomaly[" << static_cast<int>(anomaly->type) 
                  << "] Severity: " << anomaly->severity 
                  << " - " << anomaly->description << std::endl;
    }
    
    // Memory entry tracking
    struct MemoryEntry {
        uintptr_t pointer;
        size_t size;
        std::string location;
        std::chrono::system_clock::time_point allocated_at;
        std::chrono::system_clock::time_point freed_at;
        bool freed;
    };
    
    std::atomic<SecurityState> current_state_{SecurityState::HEALTHY};
    std::mutex state_mutex_;
    
    std::vector<std::pair<SecurityState, SecurityState>> state_transition_history_;
    
    std::atomic<uint64_t> anomaly_counter_{0};
    std::mutex anomaly_mutex_;
    std::vector<std::shared_ptr<SecurityAnomaly>> anomaly_history_;
    
    std::mutex memory_mutex_;
    std::unordered_map<uint64_t, MemoryEntry> memory_tracker_;
    std::atomic<size_t> total_allocated_{0};
    std::atomic<size_t> total_freed_{0};
    
    std::mutex execution_mutex_;
    std::vector<std::tuple<std::string, double, double, double>> execution_anomalies_;
};

// --- Global Instance ---

extern SecurityProfiler g_security_profiler;

// --- Convenience Macros ---

#define SECURITY_PROFILER_TRANSITION(new_state) \
    g_security_profiler.transition_state(SecurityState::new_state)

#define REPORT_ANOMALY(type, desc, severity) \
    g_security_profiler.report_anomaly(AnomalyType::type, desc, severity)

#define TRACK_MEMORY(ptr, size, location) \
    g_security_profiler.track_memory(ptr, size, location)

#define UNTRACK_MEMORY(ptr) \
    g_security_profiler.untrack_memory(ptr)

#define MONITOR_EXECUTION(order_id, exec_price, exp_price, deviation) \
    g_security_profiler.monitor_execution(order_id, exec_price, exp_price, deviation)