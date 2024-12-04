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
from constants import TIMER_DEBUG

def _log(message):
    """Conditional logging function"""
    if not TIMER_DEBUG:
        return
    LIGHT_YELLOW = "\033[93m"
    RESET = "\033[0m"
    print(f"{LIGHT_YELLOW}[TIMING] {message}{RESET}", file=sys.stderr)

def _ns_to_ms(ns):
    """Convert nanoseconds to milliseconds"""
    return ns / 1_000_000.0

class TimingStats:
    """Collects and manages timing statistics"""
    def __init__(self):
        self.reset_stats()
        self.current_message_times = {}

    def reset_stats(self):
        """Reset all timing statistics"""
        self.midi_receive_times = []
        self.router_process_times = []
        self.synth_process_times = []
        self.total_latencies = []
        self.max_samples = 1000  # Keep last 1000 samples
        self.current_message_times = {}

    def start_message_timing(self):
        """Start timing for a new MIDI message at UART arrival"""
        message_id = time.monotonic_ns()
        self.current_message_times[message_id] = {
            'uart_start': time.monotonic_ns(),
            'last_stage_end': time.monotonic_ns(),  # Track end of last stage
            'midi_duration': 0,
            'router_duration': 0,
            'synth_duration': 0
        }
        return message_id

    def start_stage(self, message_id, stage):
        """Record start time for a processing stage"""
        if message_id in self.current_message_times:
            # Start timing from end of last stage
            self.current_message_times[message_id][f'{stage}_start'] = self.current_message_times[message_id]['last_stage_end']

    def end_stage(self, message_id, stage):
        """Record end time and calculate duration for a processing stage"""
        if message_id in self.current_message_times:
            now = time.monotonic_ns()
            stage_start = self.current_message_times[message_id].get(f'{stage}_start')
            if stage_start:
                duration = _ns_to_ms(now - stage_start)
                self.current_message_times[message_id][f'{stage}_duration'] = duration
                self.add_timing(f"{stage}_process", duration)
                # Update last stage end time
                self.current_message_times[message_id]['last_stage_end'] = now

    def end_message_timing(self, message_id):
        """Complete timing for a message and log results"""
        if message_id in self.current_message_times:
            times = self.current_message_times[message_id]
            total_time = _ns_to_ms(time.monotonic_ns() - times['uart_start'])
            
            # Log timing breakdown
            _log("\nMessage Timing Breakdown:")
            _log(f"MIDI Processing: {times['midi_duration']:.3f}ms")
            _log(f"Router Processing: {times['router_duration']:.3f}ms")
            _log(f"Synth Processing: {times['synth_duration']:.3f}ms")
            _log(f"Total Time: {total_time:.3f}ms\n")
            
            # Add to total latency stats
            self.add_timing("total_latency", total_time)
            
            # Cleanup
            del self.current_message_times[message_id]

    def add_timing(self, category, duration_ms):
        """Add a timing measurement to the specified category"""
        if category == "midi_process":
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
        
        stats["midi_process"] = calc_stats(self.midi_receive_times)
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
                _log(f"  Min: {data['min']:.3f}")
                _log(f"  Max: {data['max']:.3f}")
                _log(f"  Avg: {data['avg']:.3f}")
                _log(f"  Samples: {data['samples']}")

class TimingContext:
    """Context manager for timing code blocks"""
    def __init__(self, stats, category, message_id=None):
        self.stats = stats
        self.category = category
        self.message_id = message_id
        self.start_time = None

    def __enter__(self):
        if self.message_id:
            self.stats.start_stage(self.message_id, self.category)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.message_id:
            self.stats.end_stage(self.message_id, self.category)

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
