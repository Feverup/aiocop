# Benchmarks

aiocop is designed to be production-safe with minimal overhead. This page documents performance characteristics and how to run benchmarks yourself.

aiocop works with both standard asyncio and uvloop, with similar low overhead on both.

## Summary

### asyncio

| Scenario | Per-Task Overhead | Impact on 50ms Request |
|----------|-------------------|------------------------|
| Pure async (no blocking I/O) | ~1 us | 0.002% |
| Light blocking (os.stat) | ~14 us | 0.03% |
| Moderate blocking (file read) | ~12 us | 0.02% |
| Realistic HTTP handler | ~22 us | 0.04% |

### uvloop

| Scenario | Per-Task Overhead | Impact on 50ms Request |
|----------|-------------------|------------------------|
| Pure async (no blocking I/O) | ~3 us | 0.006% |
| Light blocking (os.stat) | ~29 us | 0.06% |
| Moderate blocking (file read) | ~17 us | 0.03% |
| Realistic HTTP handler | ~56 us | 0.11% |

**Bottom line:** aiocop adds ~13 microseconds per task on asyncio and ~27 microseconds on uvloop. For typical web applications where requests take 10-100ms, this translates to **less than 0.1% overhead** on either event loop.

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
# Run both asyncio and uvloop benchmarks
uv run python benchmarks/run_benchmark.py

# Run only asyncio benchmarks
uv run python benchmarks/run_benchmark.py --asyncio-only

# Run only uvloop benchmarks
uv run python benchmarks/run_benchmark.py --uvloop-only
```

### Sample Output

```
======================================================================
aiocop Benchmark Results
======================================================================

ASYNCIO Results:
----------------------------------------------------------------------
  Scenario                                 Overhead        Impact on 50ms
  ---------------------------------------- --------------- --------------
  Pure async (no blocking)                      1.2 us      0.002%
  Trivial blocking (getcwd)                    15.3 us      0.031%
  Light blocking (stat)                        13.5 us      0.027%
  Moderate blocking (file read)                12.3 us      0.025%
  Realistic HTTP handler                       21.6 us      0.043%

  Average: 12.8 us per task (0.026% on 50ms request)

UVLOOP Results:
----------------------------------------------------------------------
  Scenario                                 Overhead        Impact on 50ms
  ---------------------------------------- --------------- --------------
  Pure async (no blocking)                      2.7 us      0.005%
  Trivial blocking (getcwd)                    29.5 us      0.059%
  Light blocking (stat)                        28.4 us      0.057%
  Moderate blocking (file read)                16.8 us      0.034%
  Realistic HTTP handler                       56.4 us      0.113%

  Average: 26.8 us per task (0.054% on 50ms request)

======================================================================
COMPARISON: asyncio vs uvloop
======================================================================
  Scenario                       asyncio      uvloop       Difference
  ------------------------------ ------------ ------------ ------------
  Pure async (no blocking)            1.2 us        2.7 us   +1.5 us
  Trivial blocking (getcwd)          15.3 us       29.5 us   +14.2 us
  Light blocking (stat)              13.5 us       28.4 us   +14.9 us
  Moderate blocking (file read)      12.3 us       16.8 us   +4.5 us
  Realistic HTTP handler             21.6 us       56.4 us   +34.8 us

  Average                            12.8 us       26.8 us   +14.0 us
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

aiocop prioritizes Python's `sys.audit` hooks (using minimal wrappers only where necessary), which is more efficient than alternatives like:

- **Heavy monkey-patching of every function**: Higher overhead, more intrusive
- **Periodic sampling**: Misses events, less accurate
- **External profilers**: Much higher overhead, not production-safe

The audit hook approach means aiocop only adds overhead when blocking I/O actually occurs.
