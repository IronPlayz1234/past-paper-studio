"""Atomic, UTF-8 persistence shared by configuration, history and caches."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile


def atomic_write_text(path, text: str, *, private: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix=target.name + '.', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if private:
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def atomic_write_json(path, payload) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + '\n')


def atomic_write_bytes(path, payload: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent,
                                         prefix=target.name + '.', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
