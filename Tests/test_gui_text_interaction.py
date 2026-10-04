import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from Core.gui_main import PastPaperFinderGUI
from Utils.sources_manager import PaperGroup, PaperResource


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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


def test_labels_are_selectable_for_copying():
    _app()
    gui = PastPaperFinderGUI()
    gui.display_results([_sample_group()], record_history=False)

    selectable_flags = (
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    labels = [w for w in gui.findChildren(QLabel) if str(w.text() or "").strip()]
    assert labels
    assert any((label.textInteractionFlags() & selectable_flags) == selectable_flags for label in labels)

    gui.close()
