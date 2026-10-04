import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from Core import gui_main
from Core.gui_main import PastPaperFinderGUI
from Utils.sources_manager import PaperGroup, PaperResource, PaperSourceManager


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


def _sample_group() -> PaperGroup:
    qp = PaperResource(
        kind="QP",
        filename="0620_s24_qp_21",
        url="https://example.com/0620_s24_qp_21.pdf",
        source="test",
    )
    return PaperGroup(
        subject_code="0620",
        subject_name="Chemistry",
        session="MJ",
        year="24",
        component="21",
        source="test",
        primary_docs={"QP": qp},
    )


def _search_params() -> dict:
    return {
        "subject_code": "0620",
        "subject_name": "Chemistry",
        "series": ["MJ"],
        "components": ["21"],
        "series_component_map": {"MJ": ["21"]},
        "years": ["24"],
        "doc_types": ["QP"],
    }


def test_instant_completion_hides_skeleton_and_resets_busy_state(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    gui.search_params = _search_params()

    def fake_search(cls, *args, **kwargs):
        return [_sample_group()]

    monkeypatch.setattr(PaperSourceManager, "search_papers_multi_source", classmethod(fake_search))

    gui.perform_search()
    assert gui._results_skeleton_active is True
    _pump_events(0.35)

    assert gui._results_skeleton_active is False
    assert gui.search_button.isEnabled() is True
    assert gui.search_button.text() == "Search Papers"
    gui.close()


def test_partial_results_hide_skeleton_before_final(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    gui.search_params = _search_params()

    def fake_search(cls, *args, **kwargs):
        partial_callback = kwargs.get("partial_callback")
        if callable(partial_callback):
            partial_callback([_sample_group()], False)
        time.sleep(0.35)
        return [_sample_group()]

    monkeypatch.setattr(PaperSourceManager, "search_papers_multi_source", classmethod(fake_search))

    gui.perform_search()
    _pump_events(0.15)

    assert gui._results_skeleton_active is False
    assert gui.search_button.isEnabled() is True
    assert gui.search_button.text() == "Search Papers"

    _pump_events(0.4)
    assert gui.search_button.isEnabled() is True
    gui.close()


def test_error_path_hides_skeleton_and_resets_busy_state(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    gui.search_params = _search_params()

    def fake_search(cls, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(PaperSourceManager, "search_papers_multi_source", classmethod(fake_search))
    monkeypatch.setattr(gui_main, "show_error", lambda *args, **kwargs: None)

    gui.perform_search()
    assert gui._results_skeleton_active is True
    _pump_events(0.35)

    assert gui._results_skeleton_active is False
    assert gui.search_button.isEnabled() is True
    assert gui.search_button.text() == "Search Papers"
    gui.close()


def test_busy_state_recovers_when_completion_signal_path_is_missed(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    gui.search_params = _search_params()

    def fake_search(cls, *args, **kwargs):
        time.sleep(0.2)
        return [_sample_group()]

    monkeypatch.setattr(PaperSourceManager, "search_papers_multi_source", classmethod(fake_search))

    gui.perform_search()
    assert gui.search_button.text() == "Searching..."
    thread = gui.search_thread
    assert thread is not None
    try:
        thread.results_ready.disconnect(gui.on_search_complete)
    except Exception:
        pass
    try:
        thread.error.disconnect(gui.on_search_error)
    except Exception:
        pass
    try:
        thread.cancelled.disconnect(gui.on_search_cancelled)
    except Exception:
        pass

    _pump_events(0.7)

    assert gui.search_button.isEnabled() is True
    assert gui.search_button.text() == "Search Papers"
    gui.close()


def test_three_consecutive_search_updates_do_not_leave_button_stuck(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()

    def fake_search(cls, subject_code, series, components, years, doc_types, **kwargs):
        partial_callback = kwargs.get("partial_callback")
        cancel_check = kwargs.get("cancel_check")
        if callable(partial_callback):
            partial_callback([_sample_group()], False)
        deadline = time.time() + 0.75
        while time.time() < deadline:
            if callable(cancel_check) and bool(cancel_check()):
                return [_sample_group()]
            time.sleep(0.02)
        return [_sample_group()]

    monkeypatch.setattr(PaperSourceManager, "search_papers_multi_source", classmethod(fake_search))

    for component in ("21", "22", "23"):
        gui.search_params = {
            "subject_code": "0620",
            "subject_name": "Chemistry",
            "series": ["MJ"],
            "components": [component],
            "series_component_map": {"MJ": [component]},
            "years": ["24"],
            "doc_types": ["QP"],
        }
        gui.perform_search()
        _pump_events(0.2)
        assert gui.search_button.isEnabled() is True
        assert gui.search_button.text() == "Search Papers"

    _pump_events(1.0)
    assert gui.search_button.isEnabled() is True
    assert gui.search_button.text() == "Search Papers"
    gui.close()
