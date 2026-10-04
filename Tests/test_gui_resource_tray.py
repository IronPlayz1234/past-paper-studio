import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

import Core.gui_main as gui_main
from Core.gui_main import ExamModeLaunchCandidate, PastPaperFinderGUI, SelectionDialog
from Utils.sources_manager import PaperGroup, PaperResource


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_group() -> PaperGroup:
    return _sample_group_with()


def _sample_group_with(
    *,
    year: str = "2024",
    session: str = "MJ",
    component: str = "11",
    qp_url: str = "https://example.com/qp.pdf",
) -> PaperGroup:
    return PaperGroup(
        subject_code="0417",
        subject_name="ICT",
        session=session,
        year=year,
        component=component,
        source="mock",
        primary_docs={
            "QP": PaperResource("QP", "0417_s24_qp_11", qp_url, "mock"),
            "MS": PaperResource("MS", "0417_s24_ms_11", "https://example.com/ms.pdf", "mock"),
        },
        resources={
            "IN": PaperResource("IN", "0417_s24_qp_11_in", "https://example.com/in.pdf", "mock"),
            "SF": PaperResource("SF", "0417_s24_qp_11_sf", "https://example.com/sf.pdf", "mock"),
        },
    )


def test_resource_tray_icons_and_flattened_items(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    group = _sample_group()

    gui.display_results([group])

    texts = [w.text() for w in gui.findChildren(QLabel)]
    assert "📎" in texts
    assert "🗂" in texts

    flattened = gui._flatten_group_items(include_resources=True)
    assert len(flattened) == 4
    assert {row["type"] for row in flattened} >= {"QP", "MS", "IN", "SF"}

    gui.close()


def test_standalone_exam_mode_prefers_qp(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    group = _sample_group()
    gui.search_results = [group]

    monkeypatch.setattr(gui_main, "EXAM_MODE_AVAILABLE", True)
    captured = {}

    def _capture(item, **kwargs):
        captured["item"] = item
        captured["kwargs"] = kwargs

    monkeypatch.setattr(gui, "launch_exam_mode_for_item", _capture)

    gui.launch_standalone_exam_mode()

    assert captured["item"]["type"] == "QP"
    assert captured["item"]["url"].endswith("qp.pdf")
    assert "paper_resources" in captured["kwargs"]
    assert "insert" in captured["kwargs"]["paper_resources"]

    gui.close()


def test_standalone_exam_mode_disambiguates_with_selection_dialog(monkeypatch):
    _app()
    gui = PastPaperFinderGUI()
    gui.search_results = [
        _sample_group_with(component="11", qp_url="https://example.com/qp11.pdf"),
        _sample_group_with(component="12", qp_url="https://example.com/qp12.pdf"),
    ]

    monkeypatch.setattr(gui_main, "EXAM_MODE_AVAILABLE", True)

    seen = {}

    def _pick_second(candidates):
        seen["count"] = len(candidates)
        return candidates[1]

    captured = {}

    def _capture(item, **kwargs):
        captured["item"] = item
        captured["kwargs"] = kwargs

    monkeypatch.setattr(gui, "_prompt_standalone_exam_selection", _pick_second)
    monkeypatch.setattr(gui, "launch_exam_mode_for_item", _capture)

    gui.launch_standalone_exam_mode()

    assert seen["count"] == 2
    assert captured["item"]["component"] == "12"
    assert captured["item"]["url"].endswith("qp12.pdf")
    assert "paper_resources" in captured["kwargs"]
    gui.close()


def test_selection_dialog_start_disabled_until_choice():
    _app()
    candidates = [
        ExamModeLaunchCandidate(
            item={
                "subject": "ICT",
                "subject_code": "0417",
                "year": "2024",
                "series": "MJ",
                "component": "11",
                "url": "https://example.com/qp11.pdf",
            },
            paper_resources={},
            label="ICT | MJ 2024 | Paper 1 | Variant 1 | Comp 11",
            year="2024",
            series="MJ",
            paper_num="1",
            variant="1",
        ),
        ExamModeLaunchCandidate(
            item={
                "subject": "ICT",
                "subject_code": "0417",
                "year": "2024",
                "series": "MJ",
                "component": "12",
                "url": "https://example.com/qp12.pdf",
            },
            paper_resources={},
            label="ICT | MJ 2024 | Paper 1 | Variant 2 | Comp 12",
            year="2024",
            series="MJ",
            paper_num="1",
            variant="2",
        ),
    ]

    dialog = SelectionDialog(candidates)
    assert not dialog.start_exam_button.isEnabled()

    dialog._option_buttons[0].click()

    assert dialog.start_exam_button.isEnabled()
    assert dialog.selected_candidate() == candidates[0]
    assert dialog._option_buttons[0].text().startswith("☑")
    assert dialog._option_buttons[1].text().startswith("☐")
    dialog.close()
