# Integrations

Real-world examples of integrating aiocop with popular frameworks and tools.

## Table of Contents

- [FastAPI](#fastapi)
- [Starlette](#starlette)
- [aiohttp](#aiohttp)
- [Datadog](#datadog)
- [Prometheus](#prometheus)
- [Structured Logging](#structured-logging)
- [Sentry](#sentry)

## FastAPI

### Basic Integration

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

import aiocop


def setup_aiocop() -> None:
    """Configure aiocop monitoring."""
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=20)
    aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=log_slow_task)


def log_slow_task(event: aiocop.SlowTaskEvent) -> None:
    """Log slow task events."""
    if event.exceeded_threshold:
        print(f"Slow task: {event.elapsed_ms:.1f}ms, severity: {event.severity_level}")
        for evt in event.blocking_events:
            print(f"  - {evt['event']} at {evt['entry_point']}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: activate monitoring
    aiocop.activate()
    yield
    # Shutdown: deactivate monitoring
    aiocop.deactivate()


# Setup before creating the app
setup_aiocop()

app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}
```

### With Request Context

Capture request information in aiocop events:

```python
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

import aiocop

# Context variable for request ID
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request_id_var.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def request_context_provider() -> dict[str, Any]:
    """Provide request context to aiocop callbacks."""
    return {
        "request_id": request_id_var.get(),
    }


def log_slow_task(event: aiocop.SlowTaskEvent) -> None:
    if event.exceeded_threshold:
        request_id = event.context.get("request_id", "unknown")
        print(f"[{request_id}] Slow task: {event.elapsed_ms:.1f}ms")


# Setup
aiocop.patch_audit_functions()
aiocop.start_blocking_io_detection()
aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=log_slow_task)
aiocop.register_context_provider(request_context_provider)

app = FastAPI()
app.add_middleware(RequestIdMiddleware)
```

## Starlette

```python
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse

import aiocop


def setup_aiocop() -> None:
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection()
    aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=log_slow_task)


def log_slow_task(event: aiocop.SlowTaskEvent) -> None:
    if event.exceeded_threshold:
        print(f"Blocking detected: {event.elapsed_ms:.1f}ms")


@asynccontextmanager
async def lifespan(app):
    aiocop.activate()
    yield
    aiocop.deactivate()


async def homepage(request):
    return JSONResponse({"hello": "world"})


setup_aiocop()

app = Starlette(
    routes=[Route("/", homepage)],
    lifespan=lifespan,
)
```

## aiohttp

```python
from aiohttp import web

import aiocop


def setup_aiocop() -> None:
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection()
    aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=log_slow_task)


def log_slow_task(event: aiocop.SlowTaskEvent) -> None:
    if event.exceeded_threshold:
        print(f"Blocking: {event.elapsed_ms:.1f}ms - {event.reason}")


async def on_startup(app):
    aiocop.activate()


async def on_cleanup(app):
    aiocop.deactivate()


async def handle(request):
    return web.json_response({"message": "Hello"})


setup_aiocop()

app = web.Application()
app.router.add_get("/", handle)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == "__main__":
    web.run_app(app)
```

## Datadog

### APM Integration

Capture aiocop events as Datadog span tags:

```python
from typing import Any

from ddtrace import tracer

import aiocop


def datadog_context_provider() -> dict[str, Any]:
    """Capture the current Datadog span."""
    return {"dd_span": tracer.current_span()}


def send_to_datadog(event: aiocop.SlowTaskEvent) -> None:
    """Tag the Datadog span with slow task info."""
    if not event.exceeded_threshold:
        return

    span = event.context.get("dd_span")
    if span is None:
        return

    # Tag the span
    span.set_tag("aiocop.slow_task", True)
    span.set_tag("aiocop.severity_level", event.severity_level)
    span.set_tag("aiocop.reason", event.reason)

    # Add metrics
    span.set_metric("aiocop.elapsed_ms", event.elapsed_ms)
    span.set_metric("aiocop.severity_score", event.severity_score)
    span.set_metric("aiocop.blocking_events_count", len(event.blocking_events))

    # Add blocking event details
    if event.blocking_events:
        events_summary = "; ".join(e["event"] for e in event.blocking_events[:5])
        span.set_tag("aiocop.blocking_events", events_summary)


# Setup
aiocop.patch_audit_functions()
aiocop.start_blocking_io_detection()
aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=send_to_datadog)
aiocop.register_context_provider(datadog_context_provider)
aiocop.activate()
```

### StatsD Metrics

```python
from datadog import statsd

import aiocop


def send_metrics(event: aiocop.SlowTaskEvent) -> None:
    """Send metrics to Datadog StatsD."""
    tags = [
        f"severity:{event.severity_level}",
        f"reason:{event.reason}",
        f"exceeded_threshold:{event.exceeded_threshold}",
    ]

    # Always send elapsed time
    statsd.histogram("aiocop.task.elapsed_ms", event.elapsed_ms, tags=tags)

    # Count slow tasks
    if event.exceeded_threshold:
        statsd.increment("aiocop.slow_task.count", tags=tags)
        statsd.histogram("aiocop.slow_task.severity_score", event.severity_score, tags=tags)


aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=send_metrics)
```

## Prometheus

```python
from prometheus_client import Counter, Histogram

import aiocop

# Define metrics
SLOW_TASK_COUNT = Counter(
    "aiocop_slow_tasks_total",
    "Total number of slow tasks detected",
    ["severity_level", "reason"],
)

TASK_DURATION = Histogram(
    "aiocop_task_duration_milliseconds",
    "Task duration in milliseconds",
    ["exceeded_threshold"],
    buckets=[10, 25, 50, 100, 250, 500, 1000],
)

SEVERITY_SCORE = Histogram(
    "aiocop_severity_score",
    "Severity score of blocking events",
    buckets=[1, 10, 25, 50, 100, 200],
)


def prometheus_callback(event: aiocop.SlowTaskEvent) -> None:
    """Record metrics in Prometheus."""
    # Record duration for all tasks
    TASK_DURATION.labels(
        exceeded_threshold=str(event.exceeded_threshold).lower()
    ).observe(event.elapsed_ms)

    # Record slow tasks
    if event.exceeded_threshold:
        SLOW_TASK_COUNT.labels(
            severity_level=event.severity_level,
            reason=event.reason,
        ).inc()

    # Record severity score
    if event.severity_score > 0:
        SEVERITY_SCORE.observe(event.severity_score)


aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=prometheus_callback)
```

## Structured Logging

### With structlog

```python
import structlog

import aiocop

logger = structlog.get_logger()


def structured_log_callback(event: aiocop.SlowTaskEvent) -> None:
    """Log slow tasks with structured logging."""
    if not event.exceeded_threshold:
        return

    log = logger.bind(
        elapsed_ms=event.elapsed_ms,
        threshold_ms=event.threshold_ms,
        severity_score=event.severity_score,
        severity_level=event.severity_level,
        reason=event.reason,
        blocking_events_count=len(event.blocking_events),
        request_id=event.context.get("request_id"),
    )

    if event.severity_level == "high":
        log.error("High severity blocking I/O detected")
    elif event.severity_level == "medium":
        log.warning("Medium severity blocking I/O detected")
    else:
        log.info("Low severity blocking I/O detected")

    # Log individual blocking events
    for evt in event.blocking_events:
        log.debug(
            "Blocking event",
            event=evt["event"],
            entry_point=evt["entry_point"],
            severity=evt["severity"],
        )


aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=structured_log_callback)
```

### With Python logging (JSON)

```python
import json
import logging

import aiocop

logger = logging.getLogger("aiocop")


def json_log_callback(event: aiocop.SlowTaskEvent) -> None:
    """Log slow tasks as JSON."""
    if not event.exceeded_threshold:
        return

    log_data = {
        "message": "Slow task detected",
        "elapsed_ms": event.elapsed_ms,
        "threshold_ms": event.threshold_ms,
        "severity_score": event.severity_score,
        "severity_level": event.severity_level,
        "reason": event.reason,
        "blocking_events": [
            {"event": e["event"], "entry_point": e["entry_point"]}
            for e in event.blocking_events
        ],
        "context": event.context,
    }

    if event.severity_level == "high":
        logger.error(json.dumps(log_data))
    else:
        logger.warning(json.dumps(log_data))


aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=json_log_callback)
```

## Sentry

```python
import sentry_sdk

import aiocop


def sentry_callback(event: aiocop.SlowTaskEvent) -> None:
    """Report high-severity blocking to Sentry."""
    if event.severity_level != "high":
        return

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("aiocop.severity_level", event.severity_level)
        scope.set_tag("aiocop.reason", event.reason)
        scope.set_extra("elapsed_ms", event.elapsed_ms)
        scope.set_extra("threshold_ms", event.threshold_ms)
        scope.set_extra("severity_score", event.severity_score)
        scope.set_extra("blocking_events", event.blocking_events)
        scope.set_extra("context", event.context)

        # Create a breadcrumb for each blocking event
        for evt in event.blocking_events:
            sentry_sdk.add_breadcrumb(
                category="aiocop",
                message=evt["event"],
                data={"trace": evt["trace"], "severity": evt["severity"]},
                level="warning",
            )

        sentry_sdk.capture_message(
            f"High severity blocking I/O: {event.elapsed_ms:.1f}ms",
            level="warning",
        )


aiocop.detect_slow_tasks(threshold_ms=30, on_slow_task=sentry_callback)
```

## Combining Multiple Integrations

```python
import aiocop


def combined_callback(event: aiocop.SlowTaskEvent) -> None:
    """Route events to multiple systems."""
    # Always send metrics
    send_to_prometheus(event)

    if event.exceeded_threshold:
        # Log all slow tasks
        log_slow_task(event)

        # Send high severity to alerting
        if event.severity_level == "high":
            send_to_sentry(event)
            send_to_pagerduty(event)


# Or register multiple callbacks
aiocop.register_slow_task_callback(prometheus_callback)
aiocop.register_slow_task_callback(structured_log_callback)
aiocop.register_slow_task_callback(datadog_callback)
```

## Gradual Rollout

Roll out aiocop monitoring gradually:

```python
import os
import random

import aiocop

# Configuration
AIOCOP_ENABLED = os.getenv("AIOCOP_ENABLED", "true").lower() == "true"
AIOCOP_SAMPLE_RATE = float(os.getenv("AIOCOP_SAMPLE_RATE", "1.0"))


def maybe_activate():
    """Activate monitoring based on sample rate."""
    if not AIOCOP_ENABLED:
        return

    if random.random() < AIOCOP_SAMPLE_RATE:
        aiocop.activate()
    else:
        aiocop.deactivate()


# In your request middleware
class AiocopMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            maybe_activate()
        await self.app(scope, receive, send)
```
