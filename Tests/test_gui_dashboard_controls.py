import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from Core.gui_main import PastPaperFinderGUI
from Utils.gui_utils import ConfigManager
from Utils.sources_manager import PaperGroup, PaperResource


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_group_with_audio() -> PaperGroup:
    qp = PaperResource(
        kind="QP",
        filename="0625_s24_qp_41.pdf",
        url="https://example.com/0625_s24_qp_41.pdf",
        source="test",
        extension="pdf",
    )
    au = PaperResource(
        kind="AU",
        filename="0625_s24_sf_41.mp3",
        url="https://example.com/0625_s24_sf_41.mp3",
        source="test",
        extension="mp3",
    )
    return PaperGroup(
        subject_code="0625",
        subject_name="Physics",
        session="MJ",
        year="24",
        component="41",
        source="test",
        primary_docs={"QP": qp},
        resources={"AU": au},
    )


def test_sidebar_collapses_to_rail_and_restores():
    _app()
    gui = PastPaperFinderGUI()
    assert hasattr(gui, "sidebar_toggle_btn")
    assert gui.search_panel.minimumWidth() >= 280

    gui._set_sidebar_collapsed(True, animate=False, persist=False)
    assert gui.search_panel.minimumWidth() == gui._sidebar_collapsed_width
    assert gui.control_center_content.isHidden() is True
    assert gui.sidebar_toggle_btn.text() == "▶"

    gui._set_sidebar_collapsed(False, animate=False, persist=False)
    assert gui.search_panel.minimumWidth() >= 280
    assert gui.control_center_content.isHidden() is False
    assert gui.sidebar_toggle_btn.text() == "◀"
    gui.close()


def test_subject_selection_and_clear_flow():
    _app()
    gui = PastPaperFinderGUI()
    gui.subjects_set_from_text("0625 - Physics")

    assert gui.subject_code == "0625"
    assert "0625 - Physics" == gui.subject_entry.text()

    gui._clear_subject_selection()
    assert gui.subject_code == ""
    assert gui.subject_entry.text() == ""
    gui.close()


def test_subject_selection_uses_single_entry_display():
    _app()
    gui = PastPaperFinderGUI()
    gui.subject_entry.setText("0625 - Physics")
    gui.subjects_set_from_text(gui.subject_entry.text())

    assert gui.subject_entry.text() == "0625 - Physics"
    assert not hasattr(gui, "subject_pill")
    assert not hasattr(gui, "subject_info")
    gui.close()


def test_sidebar_collapse_state_persists():
    _app()
    previous = ConfigManager.get_dashboard_sidebar_collapsed()
    try:
        ConfigManager.set_dashboard_sidebar_collapsed(True)
        gui = PastPaperFinderGUI()
        assert gui._sidebar_is_collapsed is True
        assert gui.search_panel.minimumWidth() == gui._sidebar_collapsed_width
        gui.close()

        ConfigManager.set_dashboard_sidebar_collapsed(False)
        gui2 = PastPaperFinderGUI()
        assert gui2._sidebar_is_collapsed is False
        assert gui2.search_panel.minimumWidth() >= 280
        gui2.close()
    finally:
        ConfigManager.set_dashboard_sidebar_collapsed(previous)


def test_results_view_mode_defaults_and_persists():
    _app()
    previous = ConfigManager.get_dashboard_results_view()
    try:
        ConfigManager.set_dashboard_results_view("list")
        gui = PastPaperFinderGUI()
        assert gui._results_view_mode == "list"
        gui._set_results_view_mode("grid")
        assert ConfigManager.get_dashboard_results_view() == "grid"
        gui.close()

        gui2 = PastPaperFinderGUI()
        assert gui2._results_view_mode == "grid"
        gui2.close()
    finally:
        ConfigManager.set_dashboard_results_view(previous)


def test_exam_answer_panel_position_defaults_and_persists():
    previous = ConfigManager.get_exam_answer_panel_position()
    try:
        ConfigManager.set_exam_answer_panel_position("left")
        assert ConfigManager.get_exam_answer_panel_position() == "left"
        ConfigManager.set_exam_answer_panel_position("right")
        assert ConfigManager.get_exam_answer_panel_position() == "right"
        ConfigManager.set_exam_answer_panel_position("invalid-value")
        assert ConfigManager.get_exam_answer_panel_position() == "bottom"
    finally:
        ConfigManager.set_exam_answer_panel_position(previous)


def test_results_view_mode_updates_visual_state_before_deferred_rerender(monkeypatch):
    app = _app()
    gui = PastPaperFinderGUI()
    gui.search_results = [_sample_group_with_audio()]
    calls: list[tuple[bool, bool]] = []

    def _fake_display(*_args, **_kwargs):
        calls.append((gui.results_view_list_btn.isChecked(), gui.results_view_grid_btn.isChecked()))

    monkeypatch.setattr(gui, "display_results", _fake_display)

    gui._set_results_view_mode("grid", persist=False, rerender=True)
    assert gui.results_view_grid_btn.isChecked() is True
    assert gui.results_view_list_btn.isChecked() is False
    assert calls == []

    app.processEvents()
    assert calls
    assert calls[0] == (False, True)
    gui.close()


def test_empty_state_is_rendered_for_no_results():
    _app()
    gui = PastPaperFinderGUI()
    gui.display_results([], record_history=False)

    labels = [lbl.text() for lbl in gui.results_container.findChildren(QLabel)]
    assert any("No Results" in text for text in labels)
    gui.close()


def test_quick_look_button_is_disabled_for_unsupported_audio_resource():
    _app()
    gui = PastPaperFinderGUI()
    group = _sample_group_with_audio()
    audio_resource = group.resources["AU"]
    card = gui.create_result_item(group, audio_resource, compact=True)

    quick_look_buttons = [btn for btn in card.findChildren(QPushButton) if btn.text() == "Quick Look"]
    assert quick_look_buttons
    assert quick_look_buttons[0].isEnabled() is False
    gui.close()
