import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from Core.gui_main import ExamModeLaunchCandidate, SelectionDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_selection_dialog_arrow_navigation_and_enter_accepts():
    _app()
    candidates = [
        ExamModeLaunchCandidate(item={}, paper_resources={}, label="Candidate A", year="2024", series="MJ", paper_num="2", variant="1"),
        ExamModeLaunchCandidate(item={}, paper_resources={}, label="Candidate B", year="2025", series="ON", paper_num="4", variant="2"),
    ]
    dialog = SelectionDialog(candidates)
    dialog.show()

    QTest.keyClick(dialog, Qt.Key.Key_Down)
    assert dialog.selected_candidate() is candidates[0]

    QTest.keyClick(dialog, Qt.Key.Key_Down)
    assert dialog.selected_candidate() is candidates[1]

    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted

    dialog.close()
