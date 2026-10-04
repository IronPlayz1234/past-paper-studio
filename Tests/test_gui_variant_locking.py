import os
import pytest
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from Core.gui_main import PastPaperFinderGUI
from Utils.gui_utils import SearchThread


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_update_variant_lock_ui_note_visibility_and_text():
    _app()
    gui = PastPaperFinderGUI()

    gui.update_variant_lock_ui(["FM"], "2")
    assert not gui.variant_lock_note.isHidden()
    assert "locked to 2" in gui.variant_lock_note.text().lower()

    gui.update_variant_lock_ui(["MJ"], None)
    assert gui.variant_lock_note.isHidden()

    gui.close()


def test_apply_variant_to_components_rewrites_and_dedupes():
    _app()
    gui = PastPaperFinderGUI()

    rewritten = gui._apply_variant_to_components(["11", "12", "13", "42", "6"], "2")
    assert rewritten == ["12", "42", "6"]

    gui.close()


def test_on_search_defers_fm_variant_locking_to_background_worker(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()

    gui.subject_code = "0620"
    gui.subject_name = "Chemistry"
    gui.component_entry.setText("21")
    gui.year_entry.setText("24")

    for key, cb in gui.series_vars.items():
        cb.setChecked(key in {"MJ", "ON", "FM"})

    monkeypatch.setattr(PastPaperFinderGUI, "perform_search", lambda self: None)

    gui.on_search()

    series_map = gui.search_params["series_component_map"]
    assert series_map["MJ"] == ["21"]
    assert series_map["ON"] == ["21"]
    assert series_map["FM"] == ["21"]
    assert "fm_locked_variant" not in gui.search_params
    assert not gui.variant_lock_note.isHidden()

    gui.close()


def test_search_thread_emits_progress_and_partial_signals():
    _app()

    progress_events = []
    partial_events = []
    finished_events = []

    def fake_search(**kwargs):
        progress_callback = kwargs.get("progress_callback")
        partial_callback = kwargs.get("partial_callback")
        cancel_check = kwargs.get("cancel_check")
        if callable(cancel_check):
            assert cancel_check() is False
        if callable(progress_callback):
            progress_callback("Trying BestExamHelp...", {"source": "bestexamhelp"})
        if callable(partial_callback):
            partial_callback(["stage-a"], False)
        return ["final"]

    thread = SearchThread(fake_search)
    thread.progress_update.connect(lambda message, metrics: progress_events.append((message, dict(metrics or {}))))
    thread.partial_results.connect(lambda groups, is_final: partial_events.append((groups, bool(is_final))))
    thread.results_ready.connect(lambda payload: finished_events.append(payload))
    thread.start()

    deadline = time.time() + 3.0
    while thread.isRunning() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    thread.wait(1000)
    QApplication.processEvents()

    assert progress_events
    assert "Trying BestExamHelp" in progress_events[0][0]
    assert progress_events[0][1]["source"] == "bestexamhelp"
    assert partial_events == [(["stage-a"], False)]
    assert finished_events == [["final"]]
