# aiocop

**Non-intrusive monitoring for Python asyncio.**

aiocop detects, pinpoints, and logs blocking I/O and CPU calls that freeze your event loop. It's designed to be production-safe with minimal overhead, leveraging Python's `sys.audit` hooks.

## Why aiocop?

Blocking calls in async code are a common source of performance issues. A single `time.sleep()` or synchronous file read can freeze your entire event loop, causing latency spikes and degraded user experience.

aiocop helps you:

- **Detect** blocking I/O operations in your async code automatically
- **Pinpoint** exactly where blocking calls originate with full stack traces
- **Prioritize** fixes with severity scoring
- **Monitor** in production with minimal overhead
- **Enforce** async best practices during development

## Quick Example

```python
import aiocop

def on_slow_task(event: aiocop.SlowTaskEvent) -> None:
    if event.exceeded_threshold:
        print(f"Blocking detected: {event.elapsed_ms:.1f}ms")
        for evt in event.blocking_events:
            print(f"  - {evt['event']}")

aiocop.patch_audit_functions()
aiocop.start_blocking_io_detection()
aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=on_slow_task)
aiocop.activate()
```

## Documentation

- [Installation](installation.md) - How to install aiocop
- [Quick Start](quickstart.md) - Get started in 5 minutes
- [User Guide](guide.md) - Complete guide to all features
- [API Reference](api.md) - Full API documentation
- [Integrations](integrations.md) - FastAPI, Datadog, and more
- [Benchmarks](benchmarks.md) - Performance and overhead analysis

## Features

- **Production-Safe**: Minimal runtime overhead using Python's audit hooks
- **asyncio & uvloop**: Works with both standard asyncio and uvloop out of the box
- **Blocking I/O Detection**: Detects file operations, network calls, subprocess, `time.sleep`, and more
- **Stack Trace Capture**: Full stack traces to pinpoint blocking calls
- **Severity Scoring**: Prioritize fixes based on impact
- **Callback System**: Handle events however you need (logging, metrics, alerts)
- **Dynamic Controls**: Enable/disable monitoring at runtime
- **Context Providers**: Capture request IDs, tracing spans, and other context
- **Exception Mode**: Raise exceptions on high-severity blocking for strict enforcement

## License

aiocop is released under the [MIT License](https://github.com/Feverup/aiocop/blob/master/LICENSE).

## Links

- [GitHub Repository](https://github.com/Feverup/aiocop)
- [PyPI Package](https://pypi.org/project/aiocop/)
- [Issue Tracker](https://github.com/Feverup/aiocop/issues)
