<p align="center">
  <img src="https://raw.githubusercontent.com/feverup/aiocop/master/docs/images/aiocop_logo.png" width="400" alt="AioCop Logo">
</p>

<p align="center">
    Non-intrusive monitoring for Python asyncio.<br>
    Detects, pinpoints, and logs blocking IO and CPU calls that freeze your event loop.
</p>

<p align="center">
    <a href="https://pypi.org/project/aiocop/"><img src="https://img.shields.io/pypi/v/aiocop.svg" alt="PyPI version"></a>
    <a href="https://pypi.org/project/aiocop/"><img src="https://img.shields.io/pypi/pyversions/aiocop.svg" alt="Python versions"></a>
    <a href="https://github.com/feverup/aiocop/blob/master/LICENSE"><img src="https://img.shields.io/pypi/l/aiocop.svg" alt="License"></a>
    <a href="https://feverup.github.io/aiocop/"><img src="https://img.shields.io/badge/docs-GitHub%20Pages-blue.svg" alt="Documentation"></a>
</p>

## Features

* **Production-Safe & Low Overhead**: Leverages Python's `sys.audit` hooks for minimal runtime overhead, making it safe for production use
* **Blocking I/O Detection**: Automatically detects blocking I/O calls (file operations, network calls, subprocess, etc.) in your async code
* **Stack Trace Capture**: Captures full stack traces to pinpoint exactly where blocking calls originate
* **Severity Scoring**: Assigns severity scores to blocking events to help prioritize fixes
* **Callback-based Events**: Register callbacks to handle slow task events however you need (logging, metrics, alerts)
* **Dynamic Controls**: Enable/disable monitoring at runtime, useful for gradual rollout or debugging sessions
* **Exception Raising**: Optionally raise exceptions on high-severity blocking I/O for strict enforcement during development

## How It Works

<p align="center">
  <img src="https://raw.githubusercontent.com/feverup/aiocop/master/docs/images/explanation_diagram.png" alt="aiocop architecture diagram">
</p>

aiocop wraps `asyncio.Handle._run` (the method that executes every task in the event loop) and uses Python's `sys.audit` hooks to detect blocking calls. When your code calls a blocking function like `open()`, the audit event is captured along with the full stack trace—letting you know exactly where the problem is.

## Why aiocop?

aiocop was built to solve specific production constraints that existing approaches didn't quite fit.

**vs. Heavy Monkey-Patching** (e.g., blockbuster): Many excellent tools rely on extensive monkey-patching of standard library logic to detect blocking calls. While effective, this approach can sometimes conflict with other libraries that instrument code (like APMs). aiocop prioritizes native `sys.audit` hooks, using minimal wrappers only where necessary to emit audit events. This significantly reduces the risk of conflicts with other instrumentation tools.

**vs. asyncio Debug Mode**: Python's built-in debug mode is invaluable during development. However, it can be heavy on logs and performance, making it impractical to leave on in high-traffic production environments. aiocop is designed to be "always-on" safe.

| Feature | Heavy Monkey-Patching Tools | asyncio Debug Mode | aiocop |
|---------|----------------------|-------------------|--------|
| Detection Method | Extensive Wrappers | Event Loop Instrumentation | `sys.audit` Hooks + Minimal Wrappers |
| Interference Risk | Medium (can conflict with APMs) | None | None |
| Production Overhead | Low-Medium | High | Very Low (~13μs/task) |
| Stack Traces | Yes | No (timing only) | Yes |
| Runtime Control | Varies | Flag at startup | Dynamic on/off |

## Performance

aiocop adds approximately **13 microseconds** of overhead per async task:

| Scenario | Overhead | Impact on 50ms Request |
|----------|----------|------------------------|
| Pure async (no blocking I/O) | ~1 us | 0.002% |
| Light blocking (os.stat) | ~14 us | 0.03% |
| Moderate blocking (file read) | ~12 us | 0.02% |
| Realistic HTTP handler | ~22 us | 0.04% |

For typical web applications, this means **less than 0.05% overhead**.

Run the benchmark yourself: `python benchmarks/run_benchmark.py`

## Installation

```bash
pip install aiocop
```

## Quick Start

Copy this into a file and run it - no dependencies needed besides aiocop:

```python
# test_aiocop.py
import asyncio
import aiocop


def on_slow_task(event):
    print(f"SLOW TASK DETECTED: {event.elapsed_ms:.1f}ms")
    print(f"  Severity: {event.severity_level}")
    for evt in event.blocking_events:
        print(f"  - {evt['event']} at {evt['entry_point']}")


async def blocking_task():
    # This synchronous open() will block the loop - aiocop will catch it!
    with open("/dev/null", "w") as f:
        f.write("data")
    await asyncio.sleep(0.1)


async def main():
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection()
    aiocop.detect_slow_tasks(threshold_ms=10, on_slow_task=on_slow_task)
    aiocop.activate()

    await asyncio.gather(blocking_task(), blocking_task())


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
python test_aiocop.py
# Output:
# SLOW TASK DETECTED: 102.3ms
#   Severity: medium
#   - open(/dev/null, w) at test_aiocop.py:14:blocking_task
```

## Usage with ASGI (FastAPI, Starlette, etc.)

```python
# In your ASGI application setup (e.g., main.py or asgi.py)
from contextlib import asynccontextmanager

import aiocop

def setup_monitoring() -> None:
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=20)
    aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=log_to_monitoring)

def log_to_monitoring(event: aiocop.SlowTaskEvent) -> None:
    # Send to your monitoring system (Datadog, Prometheus, etc.)
    if event.exceeded_threshold:
        metrics.increment("async.slow_task", tags={
            "severity": event.severity_level,
            "reason": event.reason,
        })
        metrics.gauge("async.slow_task.elapsed_ms", event.elapsed_ms)

# Call setup early in your application lifecycle
setup_monitoring()

# Activate after startup (e.g., in a lifespan handler)
@asynccontextmanager
async def lifespan(app):
    aiocop.activate()  # Start monitoring after startup
    yield
    aiocop.deactivate()
```

## Dynamic Controls

### Enable/Disable Monitoring at Runtime

```python
# Pause monitoring
aiocop.deactivate()

# Resume monitoring
aiocop.activate()

# Check if monitoring is active
if aiocop.is_monitoring_active():
    print("Monitoring is running")
```

### Raise Exceptions on High Severity Blocking I/O

Useful during development and testing to catch blocking calls immediately:

```python
# Enable globally for current context
aiocop.enable_raise_on_violations()

# Disable
aiocop.disable_raise_on_violations()

# Or use as a context manager
with aiocop.raise_on_violations():
    await some_operation()  # Will raise HighSeverityBlockingIoException if blocking
```

### CI/CD Integration - Fail Tests on Blocking I/O

Use aiocop in your integration tests to **prevent blocking code from being merged**:

```python
# conftest.py
import pytest
import aiocop

@pytest.fixture(scope="session", autouse=True)
def setup_aiocop():
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection()
    aiocop.detect_slow_tasks(threshold_ms=50)
    aiocop.activate()

# test_views.py
@pytest.mark.asyncio
async def test_my_async_endpoint(client):
    # Setup code can have blocking I/O (fixtures, test data, etc.)
    
    # Only the view execution is wrapped - this is what we care about
    with aiocop.raise_on_violations():
        response = await client.get("/api/endpoint")
    
    # Assertions can have blocking I/O too (DB checks, etc.)
    assert response.status_code == 200
```

We wrap only the async view (not the entire test) because test setup/teardown often has legitimate blocking code. See [Integrations](https://feverup.github.io/aiocop/integrations/) for complete examples.

## Context Providers

Context providers allow you to capture external context (like tracing spans, request IDs, etc.) that will be passed to your callbacks. The context is captured **within the asyncio task's context**, ensuring proper propagation of contextvars.

### Basic Usage

```python
from typing import Any

def my_context_provider() -> dict[str, Any]:
    return {
        "request_id": get_current_request_id(),
        "user_id": get_current_user_id(),
    }

aiocop.register_context_provider(my_context_provider)

def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    request_id = event.context.get("request_id")
    print(f"Slow task in request {request_id}: {event.elapsed_ms}ms")
```

### Integration with Datadog

```python
from ddtrace import tracer
from typing import Any

def datadog_context_provider() -> dict[str, Any]:
    return {"datadog_span": tracer.current_span()}

aiocop.register_context_provider(datadog_context_provider)

def log_to_datadog(event: aiocop.SlowTaskEvent) -> None:
    if event.exceeded_threshold is False:
        return

    span = event.context.get("datadog_span")
    if span is None:
        return

    span.set_tag("slow_task.detected", True)
    span.set_metric("slow_task.elapsed_ms", event.elapsed_ms)
    span.set_metric("slow_task.severity_score", event.severity_score)
    span.set_tag("slow_task.severity_level", event.severity_level)
    span.set_tag("slow_task.reason", event.reason)

aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=log_to_datadog)
```

### Why Context Providers?

When aiocop detects a slow task, the callback is invoked **after** the task completes. By that time, the original context (like the active tracing span) might no longer be accessible via standard context lookups.

Context providers solve this by capturing the context **at the start of each task execution**, within the task's own contextvars context. This ensures that:

1. Tracing spans are captured before they're closed
2. Request-scoped data is available to callbacks
3. Any contextvar-based state is properly preserved

### Managing Context Providers

```python
# Register a provider
aiocop.register_context_provider(my_provider)

# Unregister a specific provider
aiocop.unregister_context_provider(my_provider)

# Clear all providers
aiocop.clear_context_providers()
```

Context providers are **completely optional**. If none are registered, `event.context` will simply be an empty dict.

## Event Types

### SlowTaskEvent

Emitted when either:
- **Blocking I/O is detected** (`reason="io_blocking"`) - regardless of whether the task exceeded the threshold
- **Task exceeds threshold but no blocking I/O detected** (`reason="cpu_blocking"`) - indicates CPU-bound blocking

```python
@dataclass(frozen=True)
class SlowTaskEvent:
    elapsed_ms: float        # How long the task took
    threshold_ms: float      # Configured threshold
    exceeded_threshold: bool # True if elapsed > threshold
    severity_score: int      # Aggregate severity (sum of event weights), 0 for cpu_blocking
    severity_level: str      # "low", "medium", or "high"
    reason: str              # "io_blocking" or "cpu_blocking"
    blocking_events: list[BlockingEventInfo]  # List of detected events (empty for cpu_blocking)
    context: dict[str, Any]  # Custom context from context providers (default: {})
```

### BlockingEventInfo

Information about each blocking event:

```python
class BlockingEventInfo(TypedDict):
    event: str        # e.g., "open(/path/to/file)"
    trace: str        # Stack trace
    entry_point: str  # First frame in the trace
    severity: int     # Weight of this event
```

## Severity Weights

Events are classified by severity:

| Weight | Value | Examples |
|--------|-------|----------|
| `WEIGHT_HEAVY` | 50 | `socket.connect`, `subprocess.Popen`, `time.sleep`, DNS lookups |
| `WEIGHT_MODERATE` | 10 | `open()`, file mutations, `os.listdir` |
| `WEIGHT_LIGHT` | 1 | `os.stat`, `fcntl.flock`, `os.kill` |
| `WEIGHT_TRIVIAL` | 0 | `os.getcwd`, `os.path.abspath` |

Severity levels are determined by aggregate score:
- **high**: score >= 50
- **medium**: score >= 10
- **low**: score < 10

## API Reference

### Setup Functions

- `patch_audit_functions()` - Patches stdlib functions to emit audit events
- `start_blocking_io_detection(trace_depth=20)` - Registers the audit hook
- `detect_slow_tasks(threshold_ms=30, on_slow_task=None)` - Patches the event loop
- `activate()` / `deactivate()` - Control monitoring at runtime

### Callback Management

- `register_slow_task_callback(callback)` - Add a callback
- `unregister_slow_task_callback(callback)` - Remove a callback
- `clear_slow_task_callbacks()` - Remove all callbacks

### Context Provider Management

- `register_context_provider(provider)` - Add a context provider
- `unregister_context_provider(provider)` - Remove a context provider
- `clear_context_providers()` - Remove all context providers

### Raise-on-Violations Controls

- `enable_raise_on_violations()` - Enable for current context
- `disable_raise_on_violations()` - Disable for current context
- `is_raise_on_violations_enabled()` - Check current state
- `raise_on_violations()` - Context manager

### Utility Functions

- `calculate_io_severity_score(events)` - Calculate severity from events
- `get_severity_level_from_score(score)` - Get "low"/"medium"/"high"
- `format_blocking_event(raw_event)` - Format a raw event
- `get_blocking_events_dict()` - Get all monitored events with weights
- `get_patched_functions()` - Get list of patched functions
