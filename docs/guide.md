# User Guide

This guide covers all aiocop features in detail.

## Table of Contents

- [How aiocop Works](#how-aiocop-works)
- [Setup Functions](#setup-functions)
- [Callbacks](#callbacks)
- [Severity Scoring](#severity-scoring)
- [Dynamic Controls](#dynamic-controls)
- [Context Providers](#context-providers)
- [Raise on Violations](#raise-on-violations)
- [Event Types](#event-types)
- [Monitored Operations](#monitored-operations)

## How aiocop Works

aiocop uses three mechanisms to detect blocking I/O:

1. **Audit Hook Patching** (`patch_audit_functions`): Wraps stdlib functions that don't emit native audit events (like `time.sleep`, socket operations) to emit custom audit events.

2. **Audit Hook Registration** (`start_blocking_io_detection`): Registers a `sys.audit` hook that listens for blocking I/O events and captures stack traces.

3. **Event Loop Patching** (`detect_slow_tasks`): Patches `asyncio.Handle._run` to measure task execution time and invoke callbacks when blocking is detected.

```
┌─────────────────────────────────────────────────────────────┐
│                      Event Loop                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                   Handle._run()                      │    │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │              Your Async Task                   │  │    │
│  │  │                                               │  │    │
│  │  │   time.sleep(0.1)  ──► Audit Event Emitted   │  │    │
│  │  │         │                     │               │  │    │
│  │  │         ▼                     ▼               │  │    │
│  │  │   [Blocking!]          [Captured by Hook]     │  │    │
│  │  └───────────────────────────────────────────────┘  │    │
│  │                         │                            │    │
│  │                         ▼                            │    │
│  │              Callback Invoked with Event             │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Setup Functions

### patch_audit_functions()

Patches Python stdlib functions to emit audit events. **Must be called first.**

```python
aiocop.patch_audit_functions()

# Check what was patched
patched = aiocop.get_patched_functions()
print(f"Patched {len(patched)} functions: {patched[:5]}...")
```

Functions patched include:
- `time.sleep`
- `socket.socket.connect`, `send`, `recv`, etc.
- `ssl.SSLSocket.read`, `write`, etc.
- `os.stat`, `os.access`, etc.

### start_blocking_io_detection()

Registers the audit hook to capture blocking I/O events.

```python
aiocop.start_blocking_io_detection(trace_depth=20)
```

**Parameters:**
- `trace_depth` (int, default=20): Number of stack frames to capture per event.

### detect_slow_tasks()

Patches the event loop to detect slow tasks and invoke callbacks.

```python
aiocop.detect_slow_tasks(
    threshold_ms=30,
    on_slow_task=my_callback,
)
```

**Parameters:**
- `threshold_ms` (int, default=30): Tasks taking longer than this trigger callbacks with `exceeded_threshold=True`.
- `on_slow_task` (callable, optional): Callback to invoke when events are detected.

### activate() / deactivate()

Control monitoring at runtime.

```python
# Start monitoring
aiocop.activate()

# Pause monitoring (hooks remain registered but events are ignored)
aiocop.deactivate()

# Check status
if aiocop.is_monitoring_active():
    print("Monitoring is running")
```

## Callbacks

Callbacks are invoked when blocking I/O is detected or when a task exceeds the threshold.

### Registering Callbacks

```python
def my_callback(event: aiocop.SlowTaskEvent) -> None:
    print(f"Event: {event.reason}, {event.elapsed_ms}ms")

# Register via detect_slow_tasks
aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=my_callback)

# Or register separately
aiocop.register_slow_task_callback(my_callback)

# Register multiple callbacks
aiocop.register_slow_task_callback(log_callback)
aiocop.register_slow_task_callback(metrics_callback)
```

### Managing Callbacks

```python
# Remove a specific callback
aiocop.unregister_slow_task_callback(my_callback)

# Remove all callbacks
aiocop.clear_slow_task_callbacks()
```

### Callback Best Practices

1. **Keep callbacks fast**: They run in the event loop thread.
2. **Don't do blocking I/O in callbacks**: This would defeat the purpose!
3. **Handle exceptions**: aiocop catches callback exceptions, but it's good practice to handle them yourself.

```python
def safe_callback(event: aiocop.SlowTaskEvent) -> None:
    try:
        # Your logic here
        send_to_metrics(event)
    except Exception as e:
        logging.error(f"Callback error: {e}")
```

## Severity Scoring

aiocop assigns severity scores based on the type and impact of blocking operations.

### Severity Weights

| Constant | Value | Description | Examples |
|----------|-------|-------------|----------|
| `WEIGHT_HEAVY` | 50 | High-impact blocking | `socket.connect`, `subprocess.Popen`, `time.sleep`, DNS lookups |
| `WEIGHT_MODERATE` | 10 | Medium-impact | `open()`, file mutations, `os.listdir` |
| `WEIGHT_LIGHT` | 1 | Low-impact | `os.stat`, `fcntl.flock`, `os.kill` |
| `WEIGHT_TRIVIAL` | 0 | Negligible | `os.getcwd`, `os.path.abspath` |

### Severity Levels

The aggregate score determines the severity level:

| Level | Score Range | Meaning |
|-------|-------------|---------|
| `"high"` | ≥ 50 | Critical - likely to cause noticeable latency |
| `"medium"` | ≥ 10 | Warning - may cause issues under load |
| `"low"` | < 10 | Informational - minor impact |

### Using Severity in Callbacks

```python
def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    if event.severity_level == "high":
        alert_oncall(event)
    elif event.severity_level == "medium":
        log_warning(event)
    else:
        log_debug(event)
```

### Manual Severity Calculation

```python
# Calculate severity from events
score = aiocop.calculate_io_severity_score(event.blocking_events)

# Get level from score
level = aiocop.get_severity_level_from_score(score)
```

## Dynamic Controls

### Runtime Enable/Disable

```python
# Useful for gradual rollout
import random

if random.random() < 0.1:  # 10% of requests
    aiocop.activate()
else:
    aiocop.deactivate()
```

### Environment-Based Control

```python
import os

if os.getenv("AIOCOP_ENABLED", "true").lower() == "true":
    aiocop.activate()
```

## Context Providers

Context providers capture additional context (like request IDs, tracing spans) that gets passed to callbacks.

### Why Context Providers?

Callbacks are invoked **after** the task completes. By then, context like the active tracing span may no longer be accessible. Context providers capture this data **at the start** of task execution.

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
    print(f"Slow task in request {request_id}")
```

### Multiple Providers

Context from multiple providers is merged:

```python
def provider_a() -> dict[str, Any]:
    return {"key_a": "value_a"}

def provider_b() -> dict[str, Any]:
    return {"key_b": "value_b"}

aiocop.register_context_provider(provider_a)
aiocop.register_context_provider(provider_b)

# event.context = {"key_a": "value_a", "key_b": "value_b"}
```

### Managing Providers

```python
aiocop.unregister_context_provider(my_provider)
aiocop.clear_context_providers()
```

## Raise on Violations

For strict enforcement during development, aiocop can raise exceptions on high-severity blocking I/O.

### Global Enable

```python
aiocop.enable_raise_on_violations()

# Now high-severity blocking will raise HighSeverityBlockingIoException
await some_operation()

aiocop.disable_raise_on_violations()
```

### Context Manager

```python
# Only raise within this block
with aiocop.raise_on_violations():
    await some_operation()  # Raises if high-severity blocking detected

# Outside the block, no exceptions raised
await some_operation()
```

### Check Status

```python
if aiocop.is_raise_on_violations_enabled():
    print("Strict mode enabled")
```

### The Exception

```python
try:
    with aiocop.raise_on_violations():
        time.sleep(0.1)  # Blocking!
except aiocop.HighSeverityBlockingIoException as e:
    print(f"Severity: {e.severity_score}")
    print(f"Elapsed: {e.elapsed_ms}ms")
    print(f"Events: {e.events}")
```

## Event Types

### SlowTaskEvent

The main event passed to callbacks:

```python
@dataclass(frozen=True)
class SlowTaskEvent:
    elapsed_ms: float        # How long the task took
    threshold_ms: float      # Configured threshold
    exceeded_threshold: bool # True if elapsed >= threshold
    severity_score: int      # Aggregate severity score
    severity_level: str      # "low", "medium", or "high"
    reason: str              # "io_blocking" or "cpu_blocking"
    blocking_events: list[BlockingEventInfo]  # Detected blocking operations
    context: dict[str, Any]  # Context from providers (default: {})
```

**Fields:**

- `reason="io_blocking"`: Blocking I/O was detected
- `reason="cpu_blocking"`: Task exceeded threshold but no I/O detected (CPU-bound)

### BlockingEventInfo

Details about each blocking operation:

```python
class BlockingEventInfo(TypedDict):
    event: str        # e.g., "open(/path/to/file)"
    trace: str        # Stack trace
    entry_point: str  # First frame in the trace
    severity: int     # Weight of this event
```

## Monitored Operations

aiocop monitors a wide range of blocking operations:

### Network Operations

| Operation | Weight | Event |
|-----------|--------|-------|
| DNS lookup | Heavy | `socket.getaddrinfo`, `socket.gethostbyname` |
| Socket connect | Heavy | `socket.socket.connect` |
| Socket I/O | Moderate | `socket.socket.send`, `recv`, etc. |
| SSL I/O | Moderate | `ssl.SSLSocket.read`, `write` |

### File Operations

| Operation | Weight | Event |
|-----------|--------|-------|
| Open file | Moderate | `open` |
| List directory | Moderate | `os.listdir`, `os.scandir` |
| Walk directory | Heavy | `os.walk`, `glob.glob` |
| File mutations | Moderate | `os.remove`, `os.rename`, etc. |
| File stat | Light | `os.stat`, `os.access` |

### Process Operations

| Operation | Weight | Event |
|-----------|--------|-------|
| Subprocess | Heavy | `subprocess.Popen`, `os.system` |
| Fork/exec | Heavy | `os.fork`, `os.exec` |
| Sleep | Heavy | `time.sleep` |

### Get Full List

```python
events_dict = aiocop.get_blocking_events_dict()
for event, weight in sorted(events_dict.items()):
    print(f"{event}: {weight}")
```
