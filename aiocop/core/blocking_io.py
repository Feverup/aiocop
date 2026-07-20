"""Blocking IO detection via Python audit hook."""

import logging
import sys
import threading
import time
from types import FrameType

from aiocop.core.audit_patcher import FUNCTIONS_TO_PATCH_DICT
from aiocop.core.state import _get_thread_local, raise_on_violations
from aiocop.types.events import BlockingEventInfo, RawBlockingEvent
from aiocop.types.severity import WEIGHT_HEAVY, WEIGHT_LIGHT, WEIGHT_MODERATE

logger = logging.getLogger(__name__)

_main_thread_id: int | None = None
_trace_depth: int = 20
_start_blocking_io_detection_configured = False

MAX_EVENTS_PER_TASK = 50

BLOCKING_EVENTS_DICT: dict[str, int] = {
    # --- Sleep ---
    "time.sleep": WEIGHT_HEAVY,
    # --- Network Operations (Socket Level) ---
    "socket.getaddrinfo": WEIGHT_HEAVY,
    "socket.getnameinfo": WEIGHT_HEAVY,
    "socket.gethostbyname": WEIGHT_HEAVY,
    "socket.gethostbyaddr": WEIGHT_HEAVY,
    # --- File System: Opening & Creating ---
    "open": WEIGHT_MODERATE,
    "tempfile.mkdtemp": WEIGHT_MODERATE,
    "tempfile.mkstemp": WEIGHT_MODERATE,
    # --- File System: Scanning & Traversal ---
    "os.listdir": WEIGHT_MODERATE,
    "os.scandir": WEIGHT_MODERATE,
    "os.walk": WEIGHT_HEAVY,
    "os.fwalk": WEIGHT_HEAVY,
    "glob.glob": WEIGHT_HEAVY,
    "pathlib.Path.glob": WEIGHT_HEAVY,
    "pathlib.Path.rglob": WEIGHT_HEAVY,
    # --- File System: Mutation (Writes/Moves/Deletes) ---
    "os.mkdir": WEIGHT_MODERATE,
    "os.rmdir": WEIGHT_MODERATE,
    "os.remove": WEIGHT_MODERATE,
    "os.rename": WEIGHT_MODERATE,
    "os.replace": WEIGHT_MODERATE,
    "os.link": WEIGHT_MODERATE,
    "os.symlink": WEIGHT_MODERATE,
    "os.truncate": WEIGHT_MODERATE,
    "shutil.copyfile": WEIGHT_MODERATE,
    "shutil.copymode": WEIGHT_MODERATE,
    "shutil.copystat": WEIGHT_MODERATE,
    "shutil.move": WEIGHT_MODERATE,
    # --- File System: Heavy Recursion ---
    "shutil.copytree": WEIGHT_HEAVY,
    "shutil.rmtree": WEIGHT_HEAVY,
    # --- File System: Locking ---
    "fcntl.flock": WEIGHT_LIGHT,
    "fcntl.lockf": WEIGHT_LIGHT,
    # --- High-Level Network Libraries ---
    "http.client.connect": WEIGHT_HEAVY,
    "urllib.Request": WEIGHT_HEAVY,
    "ftplib.connect": WEIGHT_HEAVY,
    "smtplib.connect": WEIGHT_HEAVY,
    "poplib.connect": WEIGHT_HEAVY,
    "imaplib.open": WEIGHT_HEAVY,
    "nntplib.connect": WEIGHT_HEAVY,
    # --- System & Subprocess ---
    "os.system": WEIGHT_HEAVY,
    "os.spawn": WEIGHT_HEAVY,
    "os.posix_spawn": WEIGHT_HEAVY,
    "os.exec": WEIGHT_HEAVY,
    "os.fork": WEIGHT_HEAVY,
    "subprocess.Popen": WEIGHT_HEAVY,
    "os.kill": WEIGHT_LIGHT,
    # --- Database ---
    "sqlite3.connect": WEIGHT_MODERATE,
    # --- Miscellaneous I/O ---
    "builtins.input": WEIGHT_HEAVY,
    "import": WEIGHT_HEAVY,
    "syslog.syslog": WEIGHT_LIGHT,
    "syslog.openlog": WEIGHT_LIGHT,
} | FUNCTIONS_TO_PATCH_DICT

BLOCKING_EVENTS = set(BLOCKING_EVENTS_DICT.keys())


def start_blocking_io_detection(trace_depth: int = 20) -> None:
    """
    Register the audit hook to capture blocking IO events.

    Args:
        trace_depth: Number of stack frames to capture per event (default: 20)

    Should be called after patch_audit_functions() and before detect_slow_tasks().
    """
    global _main_thread_id, _trace_depth, _start_blocking_io_detection_configured

    if _start_blocking_io_detection_configured is True:
        logger.warning("start_blocking_io_detection called more than once, ignoring")
        return

    _main_thread_id = threading.main_thread().ident
    _trace_depth = trace_depth

    try:
        sys.addaudithook(_audit_hook)
        logger.info("Blocking I/O detection hook registered via sys.audit")
        _start_blocking_io_detection_configured = True
    except Exception as e:
        logger.error("Failed to register blocking I/O detection hook: %s", e)


def reset_blocking_events() -> None:
    """Clear all captured blocking events for the current task."""
    thread_local = _get_thread_local()
    events = getattr(thread_local, "blocking_events", None)

    if events is not None:
        events.clear()


def _audit_hook(event: str, args: tuple) -> None:
    """Internal audit hook that captures blocking IO events."""
    if event not in BLOCKING_EVENTS:
        return

    if threading.get_ident() != _main_thread_id:
        return

    thread_local = _get_thread_local()

    if getattr(thread_local, "_in_hook", False) is True:
        return

    events_list = getattr(thread_local, "blocking_events", None)

    if events_list is None:
        return

    try:
        thread_local._in_hook = True

        if len(events_list) >= MAX_EVENTS_PER_TASK:
            return

        if raise_on_violations.get() is True:
            thread_local.should_raise_for_this_handle = True

        if len(events_list) == 0 and getattr(thread_local, "blocking_context", None) is None:
            from aiocop.core.callbacks import _capture_context

            thread_local.blocking_context = _capture_context()

        raw_stack = _capture_raw_stack_frames(limit=_trace_depth)
        severity = BLOCKING_EVENTS_DICT.get(event)

        event_info: RawBlockingEvent = {
            "event_name": event,
            "raw_args": args,
            "raw_stack": raw_stack,
            "timestamp": time.time(),
            "severity": severity,
        }

        events_list.append(event_info)
    finally:
        thread_local._in_hook = False


def _capture_raw_stack_frames(limit: int) -> list[tuple[str, int, str]]:
    """Fast, lightweight stack capture using sys._getframe."""
    frame: FrameType | None

    try:
        frame = sys._getframe(1)
    except ValueError:
        return []

    captured_frames = []

    while frame is not None:
        filename = frame.f_code.co_filename
        if "aiocop" not in filename:
            captured_frames.append((filename, frame.f_lineno, frame.f_code.co_name))

            if len(captured_frames) >= limit:
                break

        frame = frame.f_back

    return captured_frames


def format_blocking_event(raw_event: RawBlockingEvent) -> BlockingEventInfo:
    """
    Format a raw blocking event into a user-friendly structure.

    Args:
        raw_event: The raw event captured by the audit hook

    Returns:
        Formatted event info with readable trace and entry point
    """
    args = raw_event["raw_args"]

    display_args = args
    if len(args) == 2 and isinstance(args[0], tuple) and isinstance(args[1], dict):
        display_args = args[0]

    try:
        parts = []
        for a in display_args:
            s = str(a)
            parts.append(s[:100] if len(s) > 100 else s)
        formatted_args = ", ".join(parts)
    except Exception:
        formatted_args = "error_formatting_args"

    event_str = f"{raw_event['event_name']}({formatted_args})"

    formatted_frames = []
    for filename, lineno, func_name in raw_event["raw_stack"]:
        short_path = filename
        if "/src/" in filename:
            short_path = filename.split("/src/", 1)[1]
        elif "/site-packages/" in filename:
            short_path = filename.split("/site-packages/", 1)[1]
        elif "/lib/python" in filename:
            path_parts = filename.split("/")
            if len(path_parts) > 0:
                short_path = path_parts[-1]

        formatted_frames.append(f"{short_path}:{lineno}:{func_name}")

    trace_str = " <- ".join(formatted_frames)
    entry_point = formatted_frames[0] if len(formatted_frames) > 0 else "unknown"

    return {"event": event_str, "trace": trace_str, "entry_point": entry_point, "severity": raw_event["severity"]}


def get_blocking_events_dict() -> dict[str, int]:
    """Return a copy of the blocking events dictionary with their severity weights."""
    return BLOCKING_EVENTS_DICT.copy()
