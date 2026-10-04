import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import Core.gui_main as gui_main
from Core.gui_main import PastPaperFinderGUI


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_open_papers_prefers_direct_url_over_wrapper(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    opened = []

    monkeypatch.setattr(gui_main.webbrowser, "open", lambda url: opened.append(str(url)))

    gui.open_papers(
        [
            {
                "direct_url": "https://example.com/paper.pdf",
                "download_url": "https://example.com/download.php?paper=1",
                "open_url": "https://example.com/viewer/paper",
                "url": "https://example.com/fallback",
            }
        ]
    )

    assert opened == ["https://example.com/paper.pdf"]
    gui.close()

