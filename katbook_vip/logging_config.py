"""
logging_config.py — structured JSON logging for the whole system.

Every log line is a single JSON object with a stable set of fields plus whatever
context is bound at the time (``request_id`` on the API, ``video_id`` / ``stage``
in the worker). This replaces the POC's ad-hoc ``print`` in ``utils.log`` while
keeping that call site working (``utils.log`` now delegates here).

Usage:
    from katbook_vip.logging_config import configure_logging, bind, get_logger
    configure_logging()                       # once, at process start
    bind(video_id="ab12", stage="visual")     # context for subsequent logs
    get_logger(__name__).info("frames extracted", extra={"count": 12})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any

# Per-task/request context, merged into every record emitted on this thread/task.
_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)

_T0 = time.time()

# Record attributes that are part of every LogRecord and therefore NOT payload.
_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord (plus bound context and ``extra=`` fields) as one JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "elapsed_s": round(record.created - _T0, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = _CONTEXT.get() or {}
        if ctx:
            payload.update(ctx)
        # any extra={...} keys passed to the logging call
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload.setdefault(key, val)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    """Human-friendly single line — used when KVIP_LOG_FORMAT=plain (local dev)."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = _CONTEXT.get() or {}
        tail = " ".join(f"{k}={v}" for k, v in ctx.items()) if ctx else ""
        el = record.created - _T0
        return f"[{el:8.1f}s][{record.levelname:5s}] {record.getMessage()}" + (
            f"  ({tail})" if tail else ""
        )


_CONFIGURED = False


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Install the formatter on the root logger. Idempotent."""
    global _CONFIGURED
    level = (level or os.environ.get("KVIP_LOG_LEVEL", "INFO")).upper()
    fmt = (fmt or os.environ.get("KVIP_LOG_FORMAT", "json")).lower()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else PlainFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # third-party libraries stay at WARNING unless the level is DEBUG
    for noisy in ("urllib3", "httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if level == "DEBUG" else logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str = "katbook_vip") -> logging.Logger:
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)


def bind(**fields: Any) -> None:
    """Merge fields into the current logging context (e.g. video_id, stage)."""
    ctx = dict(_CONTEXT.get() or {})
    ctx.update({k: v for k, v in fields.items() if v is not None})
    _CONTEXT.set(ctx)


def clear_context() -> None:
    _CONTEXT.set({})


def get_context() -> dict[str, Any]:
    return dict(_CONTEXT.get() or {})
