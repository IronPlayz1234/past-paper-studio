import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from Core.gui_main import PastPaperFinderGUI
from Utils.sources_manager import PaperSourceManager


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pump_events(seconds: float = 0.25) -> None:
    deadline = time.time() + max(0.0, float(seconds))
    app = _app()
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_cancel_active_search_resets_results_without_modal(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()

    gui.search_params = {
        "subject_code": "0620",
        "subject_name": "Chemistry",
        "series": ["MJ"],
        "components": ["21"],
        "series_component_map": {"MJ": ["21"]},
        "years": ["24"],
        "doc_types": ["QP", "MS"],
    }

    def fake_search(cls, *args, **kwargs):
        cancel_check = kwargs.get("cancel_check")
        deadline = time.time() + 1.5
        while time.time() < deadline:
            if callable(cancel_check) and cancel_check():
                return []
            time.sleep(0.01)
        return []

    monkeypatch.setattr(PaperSourceManager, "search_papers_multi_source", classmethod(fake_search))

    gui.perform_search()
    _pump_events(0.12)
    assert gui._results_skeleton_active is True

    gui._cancel_active_search()
    _pump_events(0.35)

    assert gui._results_skeleton_active is False
    assert gui.search_button.isEnabled() is True
    assert gui.search_button.text() == "Search Papers"
    assert gui.search_thread is None
    assert gui.results_count.text() == "(0 found)"
    assert gui.open_all_button.isEnabled() is False
    assert gui.download_all_button.isEnabled() is False

    gui.close()


def test_history_click_preempts_running_search_and_uses_latest_selection(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()

    calls = []

    def fake_on_search():
        calls.append(
            {
                "subject_code": gui.subject_code,
                "component": gui.component_entry.text().strip(),
                "year": gui.year_entry.text().strip(),
                "series": [s for s, cb in gui.series_vars.items() if cb.isChecked()],
            }
        )

    monkeypatch.setattr(gui, "on_search", fake_on_search)

    class _Signal:
        def disconnect(self, *args):
            pass
    class _RunningThread:
        results_ready = error = progress_update = partial_results = cancelled = _Signal()
        running = True
        def isRunning(self):
            return self.running
        def request_cancel(self):
            self.running = False
        def deleteLater(self):
            pass

    gui.search_thread = _RunningThread()  # type: ignore[assignment]

    first = QListWidgetItem("first")
    first.setData(
        Qt.ItemDataRole.UserRole,
        {
            "entry_type": "search_history",
            "search_history": {
                "subject_code": "0620",
                "subject_name": "Chemistry",
                "series": "MJ",
                "component": "21",
                "year": "24",
            },
        },
    )
    second = QListWidgetItem("second")
    second.setData(
        Qt.ItemDataRole.UserRole,
        {
            "entry_type": "search_history",
            "search_history": {
                "subject_code": "0580",
                "subject_name": "Mathematics",
                "series": "ON",
                "component": "41",
                "year": "23",
            },
        },
    )

    gui.on_history_clicked(first)
    gui.on_history_clicked(second)
    _pump_events(0.2)

    assert len(calls) == 1
    assert calls[0]["subject_code"] == "0580"
    assert calls[0]["component"] == "41"
    assert calls[0]["year"] == "23"
    assert calls[0]["series"] == ["ON"]

    gui.close()
