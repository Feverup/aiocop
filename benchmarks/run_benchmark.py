#!/usr/bin/env python3
"""
aiocop Benchmark Script

Measures the overhead of aiocop monitoring on async workloads.

Usage:
    python benchmarks/run_benchmark.py

Or with uv:
    uv run python benchmarks/run_benchmark.py
"""

import asyncio
import gc
import os
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Add parent directory to path for importing aiocop
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiocop


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    name: str
    num_tasks: int
    without_aiocop_ms: float
    with_aiocop_ms: float
    overhead_per_task_us: float  # microseconds per task


def format_results(results: list[BenchmarkResult]) -> str:
    """Format benchmark results."""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("aiocop Benchmark Results")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Per-Task Overhead (lower is better):")
    lines.append("")
    lines.append(f"  {'Scenario':<40} {'Overhead':<15} {'Impact on 50ms request'}")
    lines.append(f"  {'-' * 40} {'-' * 15} {'-' * 22}")

    for r in results:
        # Calculate impact on a 50ms request
        impact_percent = (r.overhead_per_task_us / 50000) * 100  # 50ms = 50000us
        lines.append(
            f"  {r.name:<40} {r.overhead_per_task_us:>8.1f} us      {impact_percent:.3f}%"
        )

    lines.append("")

    # Calculate average
    avg_overhead = statistics.mean(r.overhead_per_task_us for r in results)
    avg_impact = (avg_overhead / 50000) * 100

    lines.append(f"  Average: {avg_overhead:.1f} us per task ({avg_impact:.3f}% on 50ms request)")
    lines.append("")
    lines.append("-" * 70)
    lines.append("")
    lines.append("What this means:")
    lines.append(f"  - Each async task adds ~{avg_overhead:.0f} microseconds of overhead")
    lines.append(f"  - A typical 50ms HTTP request sees {avg_impact:.2f}% overhead")
    lines.append(f"  - A typical 100ms database query sees {avg_impact/2:.2f}% overhead")
    lines.append("")

    return "\n".join(lines)


async def run_scenario(
    name: str,
    task_fn: Callable[[], asyncio.Future],
    num_tasks: int,
    iterations: int = 5,
) -> BenchmarkResult:
    """Run a benchmark scenario with and without aiocop."""

    async def run_tasks():
        tasks = [asyncio.create_task(task_fn()) for _ in range(num_tasks)]
        await asyncio.gather(*tasks)

    # Warmup
    await run_tasks()
    gc.collect()

    # Benchmark WITHOUT aiocop
    aiocop.deactivate()
    times_without = []
    for _ in range(iterations):
        gc.collect()
        start = time.perf_counter()
        await run_tasks()
        elapsed = (time.perf_counter() - start) * 1000
        times_without.append(elapsed)

    without_ms = statistics.median(times_without)

    # Benchmark WITH aiocop
    aiocop.activate()
    times_with = []
    for _ in range(iterations):
        gc.collect()
        start = time.perf_counter()
        await run_tasks()
        elapsed = (time.perf_counter() - start) * 1000
        times_with.append(elapsed)

    with_ms = statistics.median(times_with)

    overhead_ms = with_ms - without_ms
    overhead_per_task_us = (overhead_ms * 1000) / num_tasks  # Convert to microseconds

    return BenchmarkResult(
        name=name,
        num_tasks=num_tasks,
        without_aiocop_ms=without_ms,
        with_aiocop_ms=with_ms,
        overhead_per_task_us=overhead_per_task_us,
    )


async def fast_async_task():
    """A fast async task with no blocking I/O."""
    await asyncio.sleep(0)


async def task_with_stat():
    """Task that performs os.stat (light blocking)."""
    os.stat(".")
    await asyncio.sleep(0)


async def task_with_getcwd():
    """Task with trivial blocking (os.getcwd)."""
    os.getcwd()
    await asyncio.sleep(0)


async def task_with_file_read():
    """Task that reads an existing file."""
    try:
        with open(__file__) as f:
            f.read(100)
    except Exception:
        pass
    await asyncio.sleep(0)


async def realistic_http_handler():
    """
    Simulates a realistic async HTTP handler.
    Most time is spent in async I/O, with occasional light blocking.
    """
    await asyncio.sleep(0.001)  # 1ms async work
    os.path.exists(".")
    os.getcwd()
    await asyncio.sleep(0.001)  # 1ms async work


def noop_callback(event: aiocop.SlowTaskEvent) -> None:
    """No-op callback for benchmarking."""
    pass


async def main():
    print("")
    print("aiocop Performance Benchmark")
    print("=" * 50)
    print("")
    print("Setting up aiocop...")

    # Setup aiocop with minimal trace depth for better performance
    aiocop.patch_audit_functions()
    aiocop.start_blocking_io_detection(trace_depth=5)
    aiocop.detect_slow_tasks(threshold_ms=1000, on_slow_task=noop_callback)

    print("Running benchmarks...\n")

    results = []

    # Scenario 1: Pure async (baseline - no blocking I/O to detect)
    result = await run_scenario(
        name="Pure async (no blocking)",
        task_fn=fast_async_task,
        num_tasks=10_000,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 2: Trivial blocking (os.getcwd - WEIGHT_TRIVIAL)
    result = await run_scenario(
        name="Trivial blocking (getcwd)",
        task_fn=task_with_getcwd,
        num_tasks=5_000,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 3: Light blocking (os.stat - WEIGHT_LIGHT)
    result = await run_scenario(
        name="Light blocking (stat)",
        task_fn=task_with_stat,
        num_tasks=5_000,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 4: Moderate blocking (file read - WEIGHT_MODERATE)
    result = await run_scenario(
        name="Moderate blocking (file read)",
        task_fn=task_with_file_read,
        num_tasks=2_000,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Scenario 5: Realistic HTTP handler simulation
    result = await run_scenario(
        name="Realistic HTTP handler",
        task_fn=realistic_http_handler,
        num_tasks=500,
    )
    results.append(result)
    print(f"  [done] {result.name}")

    # Print results
    print(format_results(results))

    # Print system info
    print("System Info:")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    print(f"  aiocop: {aiocop.__version__}")
    print("")


if __name__ == "__main__":
    asyncio.run(main())
