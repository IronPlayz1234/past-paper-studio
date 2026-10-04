"""Runtime tuning helpers shared across app modules."""

from __future__ import annotations

import gc
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from threading import Lock
from Core.runtime_paths import cache_path

_GC_MIN_INTERVAL_SEC = 0.75
_DEFAULT_FILE_BUFFER_BYTES = 64 * 1024
_DEFAULT_AI_BATCH_SIZE = 1
_last_gc_ts = 0.0
_search_logger: logging.Logger | None = None
_search_logger_lock = Lock()
_DEFAULT_SEARCH_LOG_FILE = cache_path("logs", "search.log")
_DEFAULT_SEARCH_LOG_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_SEARCH_LOG_BACKUP_COUNT = 5


def file_buffer_size_bytes() -> int:
    raw = str(os.environ.get("PAST_PAPER_FINDER_FILE_BUFFER_BYTES", "") or "").strip()
    try:
        parsed = int(raw)
    except Exception:
        parsed = _DEFAULT_FILE_BUFFER_BYTES
    return max(4096, parsed)


def configure_error_only_logging() -> None:
    logging.basicConfig(level=logging.WARNING)


def _coerce_log_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    text = str(level or "INFO").strip().upper()
    return getattr(logging, text, logging.INFO)


def configure_search_logging(
    *,
    enabled: bool = True,
    level: str | int = "INFO",
    log_file: str | None = None,
) -> logging.Logger:
    """Configure and return the shared structured search logger."""
    global _search_logger
    with _search_logger_lock:
        logger = logging.getLogger("past_paper_finder.search")
        logger.propagate = False

        for handler in list(logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)

        if not enabled:
            logger.setLevel(logging.CRITICAL + 1)
            logger.addHandler(logging.NullHandler())
            _search_logger = logger
            return logger

        target_file = str(log_file or _DEFAULT_SEARCH_LOG_FILE).strip() or _DEFAULT_SEARCH_LOG_FILE
        parent = os.path.dirname(target_file)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception:
                # Fall back to null logger if file handler cannot be created.
                logger.setLevel(logging.CRITICAL + 1)
                logger.addHandler(logging.NullHandler())
                _search_logger = logger
                return logger

        try:
            handler = RotatingFileHandler(
                target_file,
                maxBytes=_DEFAULT_SEARCH_LOG_MAX_BYTES,
                backupCount=_DEFAULT_SEARCH_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            logger.addHandler(logging.NullHandler())
            logger.setLevel(logging.CRITICAL + 1)
            _search_logger = logger
            return logger
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(_coerce_log_level(level))
        _search_logger = logger
        return logger


def get_search_logger() -> logging.Logger:
    """Return the configured shared search logger."""
    global _search_logger
    with _search_logger_lock:
        if _search_logger is not None:
            return _search_logger
    return configure_search_logging(enabled=True, level="INFO")


def ai_grading_batch_size() -> int:
    raw = str(os.environ.get("PAST_PAPER_FINDER_AI_BATCH_SIZE", "") or "").strip()
    try:
        parsed = int(raw)
    except Exception:
        parsed = _DEFAULT_AI_BATCH_SIZE
    return max(1, parsed)


def maybe_collect_garbage(reason: str = "", *, force: bool = False) -> int:
    _ = reason
    global _last_gc_ts
    now = time.monotonic()
    if not force and (now - _last_gc_ts) < _GC_MIN_INTERVAL_SEC:
        return 0
    _last_gc_ts = now
    try:
        return int(gc.collect())
    except Exception:
        return 0
