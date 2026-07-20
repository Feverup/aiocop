"""Patches Python stdlib functions to emit audit events for blocking IO detection."""

import importlib
import logging
import sys
from functools import wraps
from typing import Any

from aiocop.types.severity import WEIGHT_HEAVY, WEIGHT_LIGHT, WEIGHT_MODERATE, WEIGHT_TRIVIAL

logger = logging.getLogger(__name__)

FUNCTIONS_TO_PATCH_DICT: dict[str, int] = {
    # --- Path & Metadata (Fast / Cached) ---
    "os.getcwd": WEIGHT_TRIVIAL,
    "os.path.abspath": WEIGHT_TRIVIAL,
    "os.path.islink": WEIGHT_TRIVIAL,
    "os.path.ismount": WEIGHT_LIGHT,
    "os.readlink": WEIGHT_LIGHT,
    "os.access": WEIGHT_LIGHT,
    "os.stat": WEIGHT_LIGHT,
    "os.statvfs": WEIGHT_LIGHT,
    "os.path.samestat": WEIGHT_LIGHT,
    "os.path.sameopenfile": WEIGHT_LIGHT,
    # --- Data Transfer (Syscall Level) ---
    "os.sendfile": WEIGHT_MODERATE,
    # --- Socket Connection ---
    "socket.socket.connect": WEIGHT_HEAVY,
    "socket.socket.connect_ex": WEIGHT_HEAVY,
    "socket.socket.accept": WEIGHT_HEAVY,
    "socket.socket.bind": WEIGHT_TRIVIAL,
    # --- Socket Data Transfer ---
    "socket.socket.send": WEIGHT_MODERATE,
    "socket.socket.sendto": WEIGHT_MODERATE,
    "socket.socket.sendmsg": WEIGHT_MODERATE,
    "socket.socket.sendall": WEIGHT_MODERATE,
    "socket.socket.recv": WEIGHT_MODERATE,
    "socket.socket.recv_into": WEIGHT_MODERATE,
    "socket.socket.recvfrom": WEIGHT_MODERATE,
    "socket.socket.recvfrom_into": WEIGHT_MODERATE,
    "socket.socket.recvmsg": WEIGHT_MODERATE,
    # --- SSL Data Transfer ---
    "ssl.SSLSocket.write": WEIGHT_MODERATE,
    "ssl.SSLSocket.send": WEIGHT_MODERATE,
    "ssl.SSLSocket.read": WEIGHT_MODERATE,
    "ssl.SSLSocket.recv": WEIGHT_MODERATE,
}

if sys.version_info < (3, 13):
    # time.sleep only gained its own native sys.audit event in Python 3.13
    # (https://docs.python.org/3/library/time.html#time.sleep). On older
    # versions there is no native event, so it still needs to be patched here;
    # on 3.13+ it's recognized directly via BLOCKING_EVENTS_DICT instead.
    FUNCTIONS_TO_PATCH_DICT["time.sleep"] = WEIGHT_HEAVY

FUNCTIONS_TO_PATCH = list(FUNCTIONS_TO_PATCH_DICT.keys())

patched_functions: list[str] = []

_patch_audit_functions_configured = False


def _get_target(path: str) -> tuple[Any | None, str | None]:
    """
    Helper to resolve a dot-notation string into parent_object, attribute_name.
    """
    parts = path.split(".")
    module_name = parts[0]

    try:
        obj: Any = importlib.import_module(module_name)
    except ImportError:
        return None, None

    for part in parts[1:-1]:
        obj = getattr(obj, part, None)
        if obj is None:
            return None, None

    return obj, parts[-1]


def patch_audit_functions() -> None:
    """
    Patch Python stdlib functions to emit audit events for blocking IO detection.

    This patches functions that don't have native audit events (like socket operations,
    or time.sleep on Python < 3.13) to emit custom audit events that can be captured by
    the audit hook.

    Should be called early in application startup, before start_blocking_io_detection().
    """
    global _patch_audit_functions_configured

    if _patch_audit_functions_configured is True:
        logger.warning("patch_audit_functions called more than once, ignoring")
        return

    patched_functions.clear()

    for func_path in FUNCTIONS_TO_PATCH:
        parent, method_name = _get_target(func_path)

        if parent is None or method_name is None or not hasattr(parent, method_name):
            logger.warning("Could not patch %s: target not found", func_path)
            continue

        original_func = getattr(parent, method_name)

        def create_wrapper(original: Any, event_name: str) -> Any:
            @wraps(original)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                should_audit = True

                # Socket operations with timeout=0.0 are non-blocking and add noise when audited
                if len(args) > 0:
                    sock = args[0]
                    if hasattr(sock, "gettimeout"):
                        if sock.gettimeout() == 0.0:
                            should_audit = False

                if should_audit is True:
                    sys.audit(event_name, args, kwargs)

                return original(*args, **kwargs)

            return wrapper

        patched_func = create_wrapper(original_func, func_path)
        setattr(parent, method_name, patched_func)

        patched_functions.append(func_path)

    logger.info("Patched functions for audit: %s", patched_functions)

    _patch_audit_functions_configured = True


def get_patched_functions() -> list[str]:
    """Return a copy of the list of functions that have been patched."""
    return patched_functions.copy()
