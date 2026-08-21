#include "security_profiler.h"

// Global instance definition
SecurityProfiler g_security_profiler;

// --- Performance Monitoring Integration ---

// High-frequency trading loop safety check
inline void hft_safety_check(const char* operation, uint64_t duration_ns) {
    // Flag operations taking too long (> 1ms in HFT context)
    if (duration_ns > 1000000) {  // 1ms in nanoseconds
        REPORT_ANOMALY(EXECUTION_DEVIATION,
                      std::string("HFT operation too slow: ") + 
                      std::string(operation) + 
                      " took " + std::to_string(duration_ns) + "ns",
                      duration_ns / 1000000.0 / 1000.0);
    }
}

// Memory barrier for lock-free data structures
inline void hft_memory_barrier() {
    std::atomic_thread_fence(std::memory_order::memory_order_acquire);
}

// Console output mutex for thread-safe logging
std::mutex g_console_mutex;

void thread_safe_log(const std::string& message) {
    std::lock_guard<std::mutex> lock(g_console_mutex);
    std::cout << message << std::endl;
}

// Performance timer utility
class HftTimer {
public:
    HftTimer() : start_(std::chrono::high_resolution_clock::now()) {}
    
    ~HftTimer() {
        auto end = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(
            end - start_
        ).count();
        
        hft_safety_check("timer_cleanup", duration);
    }
    
    uint64_t elapsed_ns() const {
        auto end = std::chrono::high_resolution_clock::now();
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            end - start_
        ).count();
    }
    
    double elapsed_ms() const {
        return elapsed_ns() / 1000000.0;
    }
};

// Global console mutex definition
std::mutex g_console_mutex;