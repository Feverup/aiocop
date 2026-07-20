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
- [Extending aiocop (Advanced)](#extending-aiocop-advanced)

## How aiocop Works

aiocop uses three mechanisms to detect blocking I/O:

1. **Audit Hook Patching** (`patch_audit_functions`): Wraps stdlib functions that don't emit native audit events (like socket operations, or `time.sleep` on Python < 3.13) to emit custom audit events.

2. **Audit Hook Registration** (`start_blocking_io_detection`): Registers a `sys.audit` hook that listens for blocking I/O events and captures stack traces.

3. **Event Loop Patching** (`detect_slow_tasks`): Patches the event loop's scheduling methods (`call_soon`, `call_later`, `call_at`) to measure task execution time and invoke callbacks when blocking is detected. This approach works with both standard asyncio and uvloop.

![aiocop architecture diagram](images/explanation_diagram.png)

The diagram above shows the complete flow:

1. The **Event Loop** schedules a callback via `call_soon` (or similar)
2. **aiocop's wrapper** intercepts the callback, starts a timer and creates an events list
3. Your **task code** executes
4. When a blocking function (like `open()`) is called, the **Python VM** (for native functions) or **aiocop's wrapper** (for patched functions) emits a `sys.audit` event
5. The **audit hook** captures the event and stack trace, appending it to the events list
6. After the task completes, aiocop calculates severity and invokes callbacks with the full `SlowTaskEvent`

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
- `time.sleep` (Python < 3.13 only - it gained its own native audit event in 3.13)
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

The main event passed to callbacks.

**Important:** Callbacks are invoked for **all tasks where blocking I/O is detected**, regardless of whether the threshold was exceeded. The `exceeded_threshold` field tells you if the task was actually slow.

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

### When Callbacks Are Invoked

| Condition | `reason` | `exceeded_threshold` |
|-----------|----------|---------------------|
| Blocking I/O detected, task was fast | `"io_blocking"` | `False` |
| Blocking I/O detected, task was slow | `"io_blocking"` | `True` |
| No blocking I/O, but task was slow | `"cpu_blocking"` | `True` |

This means you can:
- **Log all blocking I/O** (even fast ones) for analysis
- **Alert only on slow tasks** by checking `exceeded_threshold`

```python
def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    # Log all blocking I/O for debugging/analysis
    if event.reason == "io_blocking":
        log_blocking_io(event)
    
    # Only alert if the task was actually slow
    if event.exceeded_threshold:
        send_alert(event)
```

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

## Extending aiocop (Advanced)

For advanced users who need to monitor additional blocking operations, aiocop's internal dictionaries can be modified before setup.

### Adding Custom Audit Events

To listen for additional Python audit events (no patching required):

```python
from aiocop.core.blocking_io import BLOCKING_EVENTS_DICT
from aiocop.types.severity import WEIGHT_MODERATE

# Add before calling start_blocking_io_detection()
BLOCKING_EVENTS_DICT["my.custom.audit.event"] = WEIGHT_MODERATE
```

This is safe for any audit event that Python's VM already emits. See [Python's audit events documentation](https://docs.python.org/3/library/audit_events.html) for the full list.

### Adding Custom Functions to Patch

To wrap additional Python functions with audit event emission:

```python
from aiocop.core.audit_patcher import FUNCTIONS_TO_PATCH_DICT
from aiocop.types.severity import WEIGHT_HEAVY

# Add before calling patch_audit_functions()
FUNCTIONS_TO_PATCH_DICT["mylib.sync_http_call"] = WEIGHT_HEAVY
FUNCTIONS_TO_PATCH_DICT["legacy_module.blocking_operation"] = WEIGHT_MODERATE
```

### Important Limitations

**You can only patch pure Python functions.** C-level built-in functions cannot be monkey-patched and will silently fail or cause crashes.

| Can Patch | Cannot Patch |
|-----------|--------------|
| `mylib.my_function` | `len`, `sum`, `sorted` |
| `json.dumps` (Python wrapper) | `str.encode` (C method) |
| `configparser.read` | `list.append` (C method) |
| Third-party pure Python code | Most built-in types' methods |

**How to tell if a function is patchable:**

```python
import inspect

def is_patchable(func):
    """Check if a function can be safely patched."""
    try:
        # Built-in functions implemented in C
        if isinstance(func, type(len)):
            return False
        # Methods of built-in types
        if isinstance(func, type(str.encode)):
            return False
        # Has Python source code
        return inspect.isfunction(func) or inspect.ismethod(func)
    except:
        return False

# Examples
import json
print(is_patchable(json.dumps))  # True - Python wrapper
print(is_patchable(len))          # False - C built-in
```

### Example: Monitoring a Custom Library

```python
from aiocop.core.audit_patcher import FUNCTIONS_TO_PATCH_DICT
from aiocop.core.blocking_io import BLOCKING_EVENTS_DICT
from aiocop.types.severity import WEIGHT_HEAVY, WEIGHT_MODERATE
import aiocop

# 1. Add custom functions BEFORE setup
FUNCTIONS_TO_PATCH_DICT["requests.get"] = WEIGHT_HEAVY
FUNCTIONS_TO_PATCH_DICT["requests.post"] = WEIGHT_HEAVY
FUNCTIONS_TO_PATCH_DICT["myapp.legacy.sync_db_query"] = WEIGHT_MODERATE

# 2. These will also be added to BLOCKING_EVENTS_DICT automatically
# when patch_audit_functions() is called

# 3. Normal setup
aiocop.patch_audit_functions()
aiocop.start_blocking_io_detection()
aiocop.detect_slow_tasks(threshold_ms=30)
aiocop.activate()
```

**Note:** This is an advanced feature. The internal APIs may change between versions. If you find yourself needing to monitor many custom operations, please [open an issue](https://github.com/feverup/aiocop/issues) - we'd love to hear your use case!
