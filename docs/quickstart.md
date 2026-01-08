# Quick Start

Get aiocop running in 5 minutes.

## Installation

```bash
pip install aiocop
```

## Try It Now

Copy this into a file and run it - no dependencies needed:

```python
# test_aiocop.py
import asyncio
import aiocop


def on_slow_task(event):
    print(f"SLOW TASK DETECTED: {event.elapsed_ms:.1f}ms")
    print(f"  Severity: {event.severity_level}")
    print(f"  Blocking events: {len(event.blocking_events)}")
    for evt in event.blocking_events:
        print(f"  - {evt['event']} at {evt['entry_point']}")


async def blocking_task():
    print("Executing task...")
    # This synchronous open() will block the loop!
    with open("/dev/null", "w") as f:
        f.write("data")
    await asyncio.sleep(0.1)


async def main():
    # Setup aiocop
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=5)
    aiocop.detect_slow_tasks(threshold_ms=10, on_slow_task=on_slow_task)
    aiocop.activate()

    # Run your code as normal
    await asyncio.gather(blocking_task(), blocking_task())

    aiocop.deactivate()


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
python test_aiocop.py
```

**Output:**

```
Executing task...
Executing task...
SLOW TASK DETECTED: 102.3ms
  Severity: medium
  Blocking events: 1
  - open(/dev/null, w) at test_aiocop.py:15:blocking_task
SLOW TASK DETECTED: 103.1ms
  Severity: medium
  Blocking events: 1
  - open(/dev/null, w) at test_aiocop.py:15:blocking_task
```

## Understanding the Setup

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

## The Callback

The callback receives a `SlowTaskEvent` with all the details:

```python
def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    # Callback is invoked for ALL blocking I/O, not just slow tasks.
    # Use exceeded_threshold to check if it was actually slow.
    if event.exceeded_threshold:
        print(f"SLOW TASK: {event.elapsed_ms:.1f}ms (threshold: {event.threshold_ms}ms)")
        print(f"  Severity: {event.severity_level} (score: {event.severity_score})")
        print(f"  Reason: {event.reason}")

        for evt in event.blocking_events:
            print(f"  - {evt['event']}")
            print(f"    at {evt['trace']}")
```

**Note:** The callback is invoked for **all tasks with blocking I/O detected**, even fast ones. Check `event.exceeded_threshold` to filter for slow tasks only.

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
