"""
timing.py - Program-wide Performance Timing System

Tracks timing across the entire MIDI processing chain:
- MIDI UART reception
- Router message processing
- Synthesizer voice management
- Total system latency
"""

import time
import sys
from constants import DEBUG

def _log(message):
    """Conditional logging function"""
    if not DEBUG:
        return
    CYAN = "\033[96m"
    RESET = "\033[0m"
    print(f"{CYAN}[TIMING] {message}{RESET}", file=sys.stderr)

class TimingStats:
    """Collects and manages timing statistics"""
    def __init__(self):
        self.reset_stats()

    def reset_stats(self):
        """Reset all timing statistics"""
        self.midi_receive_times = []
        self.router_process_times = []
        self.synth_process_times = []
        self.total_latencies = []
        self.max_samples = 1000  # Keep last 1000 samples

    def add_timing(self, category, duration_ms):
        """Add a timing measurement to the specified category"""
        if category == "midi_receive":
            self.midi_receive_times.append(duration_ms)
            if len(self.midi_receive_times) > self.max_samples:
                self.midi_receive_times.pop(0)
        elif category == "router_process":
            self.router_process_times.append(duration_ms)
            if len(self.router_process_times) > self.max_samples:
                self.router_process_times.pop(0)
        elif category == "synth_process":
            self.synth_process_times.append(duration_ms)
            if len(self.synth_process_times) > self.max_samples:
                self.synth_process_times.pop(0)
        elif category == "total_latency":
            self.total_latencies.append(duration_ms)
            if len(self.total_latencies) > self.max_samples:
                self.total_latencies.pop(0)

    def get_stats(self):
        """Calculate statistics for all timing categories"""
        stats = {}
        
        def calc_stats(times):
            if not times:
                return None
            return {
                "min": min(times),
                "max": max(times),
                "avg": sum(times) / len(times),
                "samples": len(times)
            }
        
        stats["midi_receive"] = calc_stats(self.midi_receive_times)
        stats["router_process"] = calc_stats(self.router_process_times)
        stats["synth_process"] = calc_stats(self.synth_process_times)
        stats["total_latency"] = calc_stats(self.total_latencies)
        
        return stats

    def log_stats(self):
        """Log current timing statistics"""
        stats = self.get_stats()
        _log("\nTiming Statistics (ms):")
        
        for category, data in stats.items():
            if data:
                _log(f"\n{category.replace('_', ' ').title()}:")
                _log(f"  Min: {data['min']:.2f}")
                _log(f"  Max: {data['max']:.2f}")
                _log(f"  Avg: {data['avg']:.2f}")
                _log(f"  Samples: {data['samples']}")

class TimingContext:
    """Context manager for timing code blocks"""
    def __init__(self, stats, category):
        self.stats = stats
        self.category = category
        self.start_time = None

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = (time.monotonic() - self.start_time) * 1000  # Convert to ms
            self.stats.add_timing(self.category, duration)

# Global timing stats instance
timing_stats = TimingStats()

def get_timing_stats():
    """Get current timing statistics"""
    return timing_stats.get_stats()

def log_timing_stats():
    """Log current timing statistics"""
    timing_stats.log_stats()

def reset_timing_stats():
    """Reset all timing statistics"""
    timing_stats.reset_stats()
