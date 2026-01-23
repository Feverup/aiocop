# API Reference

Complete API documentation for aiocop.

## Setup Functions

### patch_audit_functions

```python
aiocop.patch_audit_functions() -> None
```

Patches Python stdlib functions to emit audit events for blocking I/O detection.

**Must be called first**, before `start_blocking_io_detection()`.

Functions patched include `time.sleep`, socket operations, SSL operations, and various `os` functions that don't emit native audit events.

---

### start_blocking_io_detection

```python
aiocop.start_blocking_io_detection(trace_depth: int = 20) -> None
```

Registers the audit hook to capture blocking I/O events.

**Parameters:**
- `trace_depth`: Number of stack frames to capture per event. Default: 20.

**Should be called after** `patch_audit_functions()` and **before** `detect_slow_tasks()`.

---

### detect_slow_tasks

```python
aiocop.detect_slow_tasks(
    threshold_ms: int = 30,
    on_slow_task: Callable[[SlowTaskEvent], None] | None = None,
) -> None
```

Patches the event loop to detect slow tasks. Works with both standard asyncio and uvloop.

**Parameters:**
- `threshold_ms`: Threshold in milliseconds. Tasks exceeding this have `exceeded_threshold=True`. Default: 30.
- `on_slow_task`: Optional callback invoked when blocking I/O is detected. Can also use `register_slow_task_callback()`.

**Should be called after** `start_blocking_io_detection()`.

**Note:** Can only be called once per process. Subsequent calls log a warning and return.

---

### activate

```python
aiocop.activate() -> None
```

Activates monitoring. Call this after setup when you want to start detecting blocking I/O.

---

### deactivate

```python
aiocop.deactivate() -> None
```

Deactivates monitoring. Pauses all detection without unregistering hooks.

---

### is_monitoring_active

```python
aiocop.is_monitoring_active() -> bool
```

Returns `True` if monitoring is currently active.

---

## Callback Management

### register_slow_task_callback

```python
aiocop.register_slow_task_callback(
    callback: Callable[[SlowTaskEvent], None]
) -> None
```

Registers a callback to be invoked when a slow task is detected.

Multiple callbacks can be registered. Duplicate registrations are ignored.

---

### unregister_slow_task_callback

```python
aiocop.unregister_slow_task_callback(
    callback: Callable[[SlowTaskEvent], None]
) -> None
```

Unregisters a previously registered callback. No error if callback wasn't registered.

---

### clear_slow_task_callbacks

```python
aiocop.clear_slow_task_callbacks() -> None
```

Removes all registered callbacks.

---

## Context Provider Management

### register_context_provider

```python
aiocop.register_context_provider(
    provider: Callable[[], dict[str, Any]]
) -> None
```

Registers a context provider. Providers are called at the start of each task to capture context that will be passed to callbacks.

**Example:**
```python
def my_provider() -> dict[str, Any]:
    return {"request_id": get_request_id()}

aiocop.register_context_provider(my_provider)
```

---

### unregister_context_provider

```python
aiocop.unregister_context_provider(
    provider: Callable[[], dict[str, Any]]
) -> None
```

Unregisters a previously registered context provider.

---

### clear_context_providers

```python
aiocop.clear_context_providers() -> None
```

Removes all registered context providers.

---

## Raise on Violations

### enable_raise_on_violations

```python
aiocop.enable_raise_on_violations() -> None
```

Enables raising `HighSeverityBlockingIoException` on high-severity blocking I/O for the current context.

---

### disable_raise_on_violations

```python
aiocop.disable_raise_on_violations() -> None
```

Disables raising exceptions on blocking I/O for the current context.

---

### is_raise_on_violations_enabled

```python
aiocop.is_raise_on_violations_enabled() -> bool
```

Returns `True` if raise-on-violations is enabled for the current context.

---

### raise_on_violations

```python
aiocop.raise_on_violations() -> ContextManager
```

Context manager that temporarily enables raise-on-violations.

**Example:**
```python
with aiocop.raise_on_violations():
    await some_operation()  # Raises if high-severity blocking
# Outside: no exception raised
```

---

## Utility Functions

### get_patched_functions

```python
aiocop.get_patched_functions() -> list[str]
```

Returns a list of function names that have been patched by `patch_audit_functions()`.

---

### get_blocking_events_dict

```python
aiocop.get_blocking_events_dict() -> dict[str, int]
```

Returns a dictionary of all monitored blocking events and their severity weights.

**Example:**
```python
events = aiocop.get_blocking_events_dict()
# {'time.sleep': 50, 'open': 10, 'os.stat': 1, ...}
```

---

### get_slow_task_threshold_ms

```python
aiocop.get_slow_task_threshold_ms() -> float
```

Returns the currently configured slow task threshold in milliseconds.

---

### calculate_io_severity_score

```python
aiocop.calculate_io_severity_score(
    blocking_events: list[BlockingEventInfo] | None
) -> int
```

Calculates the aggregate severity score from a list of blocking events.

**Parameters:**
- `blocking_events`: List of blocking event info dicts, or `None`.

**Returns:** Total severity score (sum of event weights). Returns 0 if `None` or empty.

---

### get_severity_level_from_score

```python
aiocop.get_severity_level_from_score(score: int) -> str
```

Converts a numeric severity score to a severity level string.

**Returns:**
- `"high"` if score ≥ 50
- `"medium"` if score ≥ 10
- `"low"` if score < 10

---

### format_blocking_event

```python
aiocop.format_blocking_event(raw_event: RawBlockingEvent) -> BlockingEventInfo
```

Formats a raw blocking event into a user-friendly structure.

---

### reset_blocking_events

```python
aiocop.reset_blocking_events() -> None
```

Clears all captured blocking events for the current task. Useful in testing.

---

## Types

### SlowTaskEvent

```python
@dataclass(frozen=True)
class SlowTaskEvent:
    elapsed_ms: float
    threshold_ms: float
    exceeded_threshold: bool
    severity_score: int
    severity_level: str  # "low", "medium", "high"
    reason: str          # "io_blocking" or "cpu_blocking"
    blocking_events: list[BlockingEventInfo]
    context: dict[str, Any] = field(default_factory=dict)
```

Event emitted when blocking I/O is detected or when a task exceeds the threshold.

**When events are emitted:**
- `reason="io_blocking"`: Blocking I/O was detected. `exceeded_threshold` indicates if the task was slow.
- `reason="cpu_blocking"`: No blocking I/O, but task exceeded threshold (CPU-bound work).

**Note:** Callbacks receive events for **all blocking I/O**, not just slow tasks. Use `exceeded_threshold` to filter.

---

### BlockingEventInfo

```python
class BlockingEventInfo(TypedDict):
    event: str        # e.g., "open(/path/to/file)"
    trace: str        # Stack trace string
    entry_point: str  # First frame in the trace
    severity: int     # Weight of this event
```

Information about a single blocking operation.

---

### SlowTaskCallback

```python
SlowTaskCallback = Callable[[SlowTaskEvent], None]
```

Type alias for slow task callback functions.

---

### ContextProvider

```python
ContextProvider = Callable[[], dict[str, Any]]
```

Type alias for context provider functions.

---

### IoSeverityLevel

```python
IoSeverityLevel = Literal["low", "medium", "high"]
```

Type alias for severity level strings.

---

## Exceptions

### HighSeverityBlockingIoException

```python
class HighSeverityBlockingIoException(Exception):
    severity_score: int
    severity_level: str
    elapsed_ms: float
    threshold_ms: float
    events: list[dict[str, str]]
```

Exception raised when high-severity blocking I/O is detected and `raise_on_violations` is enabled.

---

## Constants

### Severity Weights

```python
aiocop.WEIGHT_HEAVY = 50      # High-impact: network, subprocess, sleep
aiocop.WEIGHT_MODERATE = 10   # Medium-impact: file I/O, mutations
aiocop.WEIGHT_LIGHT = 1       # Low-impact: stat, access checks
aiocop.WEIGHT_TRIVIAL = 0     # Negligible: getcwd, path operations
```

### Severity Thresholds

```python
aiocop.THRESHOLD_HIGH = 50    # Score >= 50 is "high"
aiocop.THRESHOLD_MEDIUM = 10  # Score >= 10 is "medium"
aiocop.THRESHOLD_LOW = 1      # Score >= 1 is "low"
```
