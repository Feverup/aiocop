# Quick Start

Get aiocop running in 5 minutes.

## Installation

```bash
pip install aiocop
```

## Basic Setup

aiocop requires three setup steps, then activation:

```python
import aiocop

# Step 1: Patch stdlib functions to emit audit events
aiocop.patch_audit_functions()

# Step 2: Register the audit hook to capture blocking I/O
aiocop.start_blocking_io_detection()

# Step 3: Patch the event loop to detect slow tasks
aiocop.detect_slow_tasks(threshold_ms=30)

# Step 4: Activate monitoring
aiocop.activate()
```

That's it! aiocop is now monitoring your async code.

## Adding a Callback

To actually see the detected events, register a callback:

```python
import aiocop

def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    # Callback is invoked for ALL blocking I/O, not just slow tasks.
    # Use exceeded_threshold to check if it was actually slow.
    if event.exceeded_threshold:
        print(f"SLOW TASK: {event.elapsed_ms:.1f}ms (threshold: {event.threshold_ms}ms)")
        print(f"   Severity: {event.severity_level} (score: {event.severity_score})")
        print(f"   Reason: {event.reason}")
        
        for evt in event.blocking_events:
            print(f"   - {evt['event']}")
            print(f"      at {evt['trace']}")

# Setup
aiocop.patch_audit_functions()
aiocop.start_blocking_io_detection()
aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=on_slow_task)
aiocop.activate()
```

**Note:** The callback is invoked for **all tasks with blocking I/O detected**, even fast ones. Check `event.exceeded_threshold` to filter for slow tasks only.

## Complete Example

Here's a complete example that demonstrates aiocop detecting blocking I/O:

```python
import asyncio
import time
import aiocop

def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    if event.exceeded_threshold:
        print(f"\nBlocking detected!")
        print(f"   Duration: {event.elapsed_ms:.1f}ms")
        print(f"   Severity: {event.severity_level}")
        for evt in event.blocking_events:
            print(f"   - {evt['event']}")

async def bad_async_function():
    """This function has a blocking call - aiocop will detect it!"""
    await asyncio.sleep(0.01)  # This is fine (async)
    time.sleep(0.05)           # This is BAD (blocking) - aiocop will catch it!
    await asyncio.sleep(0.01)  # This is fine (async)

async def main():
    # Setup aiocop
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection()
    aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=on_slow_task)
    aiocop.activate()
    
    print("Running async task with blocking call...")
    await bad_async_function()
    print("\nDone!")

if __name__ == "__main__":
    asyncio.run(main())
```

**Output:**

```
Running async task with blocking call...

Blocking detected!
   Duration: 52.3ms
   Severity: high
   - time.sleep(0.05)

Done!
```

## What Gets Detected?

aiocop monitors many blocking operations:

| Category | Examples |
|----------|----------|
| **Sleep** | `time.sleep()` |
| **File I/O** | `open()`, `os.listdir()`, `os.walk()` |
| **Network** | `socket.connect()`, DNS lookups |
| **Subprocess** | `subprocess.Popen()`, `os.system()` |
| **Database** | `sqlite3.connect()` |

See the [User Guide](guide.md) for the complete list.

## Next Steps

- [User Guide](guide.md) - Learn about severity scoring, context providers, and more
- [Integrations](integrations.md) - Set up with FastAPI, Datadog, etc.
- [API Reference](api.md) - Full API documentation
