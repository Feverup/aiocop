# Benchmarks

aiocop is designed to be production-safe with minimal overhead. This page documents performance characteristics and how to run benchmarks yourself.

## Summary

| Scenario | Per-Task Overhead | Impact on 50ms Request |
|----------|-------------------|------------------------|
| Pure async (no blocking I/O) | ~1 us | 0.002% |
| Light blocking (os.stat) | ~14 us | 0.03% |
| Moderate blocking (file read) | ~12 us | 0.02% |
| Realistic HTTP handler | ~22 us | 0.04% |

**Bottom line:** aiocop adds ~13 microseconds per task on average. For typical web applications where requests take 10-100ms, this translates to **less than 0.05% overhead**.

## Understanding the Numbers

### Percentage vs Absolute Overhead

Micro-benchmarks can show high percentage overhead (e.g., +100%) because the baseline is so small. What matters for real applications is the **absolute overhead per task**.

For example:
- Benchmark shows: 23us overhead per task
- Your HTTP request takes: 50ms (50,000us)
- Real overhead: 23us / 50,000us = **0.046%**

### When Overhead Matters

aiocop overhead comes from:

1. **Audit hook processing** - Triggered when blocking I/O is detected
2. **Stack trace capture** - Configurable via `trace_depth` parameter
3. **Callback invocation** - Your callback function execution time

If your application:
- Has many rapid blocking calls in tight loops: Consider deactivating aiocop for those sections
- Has typical async workloads with occasional blocking: Overhead is negligible

## Running Benchmarks

Run the included benchmark script:

```bash
# With uv
uv run python benchmarks/run_benchmark.py

# Or directly
python benchmarks/run_benchmark.py
```

### Sample Output

```
======================================================================
aiocop Benchmark Results
======================================================================

Per-Task Overhead (lower is better):

  Scenario                                 Overhead        Impact on 50ms request
  ---------------------------------------- --------------- ----------------------
  Pure async (no blocking)                      1.2 us      0.002%
  Trivial blocking (getcwd)                    15.3 us      0.031%
  Light blocking (stat)                        13.5 us      0.027%
  Moderate blocking (file read)                12.3 us      0.025%
  Realistic HTTP handler                       21.6 us      0.043%

  Average: 12.8 us per task (0.026% on 50ms request)

----------------------------------------------------------------------

What this means:
  - Each async task adds ~13 microseconds of overhead
  - A typical 50ms HTTP request sees 0.03% overhead
  - A typical 100ms database query sees 0.01% overhead
```

## Tuning for Performance

### Reduce Stack Trace Depth

The `trace_depth` parameter controls how many stack frames are captured. Lower values reduce overhead:

```python
# Default: 20 frames
aiocop.start_blocking_io_detection(trace_depth=20)

# Faster: 5 frames (still useful for pinpointing issues)
aiocop.start_blocking_io_detection(trace_depth=5)

# Fastest: 1 frame (minimal context)
aiocop.start_blocking_io_detection(trace_depth=1)
```

### Use Sampling

For high-throughput applications, enable monitoring for only a percentage of requests:

```python
import random

# In your request middleware
if random.random() < 0.1:  # 10% of requests
    aiocop.activate()
else:
    aiocop.deactivate()
```

### Deactivate for Known-Safe Sections

If you have sections with intentional blocking that you don't need to monitor:

```python
aiocop.deactivate()
# ... known blocking code ...
aiocop.activate()
```

### Keep Callbacks Fast

Your callback function runs in the event loop. Keep it fast:

```python
# Good: Quick append to list, process later
def fast_callback(event):
    events_queue.append(event)

# Avoid: Heavy processing in callback
def slow_callback(event):
    send_to_remote_server(event)  # Don't do this!
```

## Benchmark Methodology

The benchmark script:

1. **Warmup**: Runs each scenario once to warm up caches
2. **Iterations**: Runs 5 iterations of each scenario
3. **Median**: Reports median time (more stable than mean)
4. **GC**: Forces garbage collection between runs

### Scenarios Tested

| Scenario | Description | Tasks |
|----------|-------------|-------|
| Pure async | `await asyncio.sleep(0)` only | 10,000 |
| Trivial blocking | `os.getcwd()` | 5,000 |
| Light blocking | `os.stat(".")` | 5,000 |
| Moderate blocking | File open/read | 2,000 |
| Realistic HTTP | 2ms async + light blocking | 500 |

## Comparison with Alternatives

aiocop uses Python's `sys.audit` hooks, which is more efficient than alternatives like:

- **Monkey-patching every function**: Higher overhead, more intrusive
- **Periodic sampling**: Misses events, less accurate
- **External profilers**: Much higher overhead, not production-safe

The audit hook approach means aiocop only adds overhead when blocking I/O actually occurs.
