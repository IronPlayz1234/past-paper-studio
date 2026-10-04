from __future__ import annotations

import sys
from pathlib import Path


# Ensure package imports resolve when pytest picks Tests/ as rootdir.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Tests must never read/write the real application's settings, attempts or API key.
import os
import tempfile
import atexit
_TEST_STORAGE = tempfile.TemporaryDirectory(prefix='ppf-test-storage-')
os.environ['PAST_PAPER_FINDER_DATA_DIR'] = str(Path(_TEST_STORAGE.name) / 'data')
os.environ['PAST_PAPER_FINDER_CACHE_DIR'] = str(Path(_TEST_STORAGE.name) / 'cache')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
atexit.register(_TEST_STORAGE.cleanup)

# Exam layout preferences use QSettings separately from JSON persistence.
from PySide6.QtCore import QSettings
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  str(Path(_TEST_STORAGE.name) / 'qt-settings'))

import pytest

@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    import requests
    def blocked(*args, **kwargs):
        raise requests.ConnectionError('Live network is disabled in automated tests')
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)
