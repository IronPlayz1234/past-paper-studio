import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Core.exam_mode import MCQQuestionnaire, WrittenQuestionnaire


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_written_questionnaire_arrow_navigation_between_inputs():
    _app()
    widget = WrittenQuestionnaire(num_questions=3)

    first = widget.answers[1]
    second = widget.answers[2]
    third = widget.answers[3]

    first.setFocus()
    assert widget.focusWidget() is first

    QTest.keyClick(first, Qt.Key.Key_Down)
    assert widget.focusWidget() is second

    QTest.keyClick(second, Qt.Key.Key_Down)
    assert widget.focusWidget() is third

    QTest.keyClick(third, Qt.Key.Key_Down)
    assert widget.focusWidget() is third

    QTest.keyClick(third, Qt.Key.Key_Up)
    assert widget.focusWidget() is second


def test_mcq_questionnaire_arrow_navigation_and_enter_selects():
    _app()
    widget = MCQQuestionnaire(num_questions=3)

    first_a = widget.radio_buttons[1]["A"]
    first_a.setFocus()
    assert widget.focusWidget() is first_a

    QTest.keyClick(first_a, Qt.Key.Key_Right)
    first_b = widget.radio_buttons[1]["B"]
    assert widget.focusWidget() is first_b

    QTest.keyClick(first_b, Qt.Key.Key_Down)
    second_b = widget.radio_buttons[2]["B"]
    assert widget.focusWidget() is second_b

    QTest.keyClick(second_b, Qt.Key.Key_Return)
    assert widget.answers[2] == "B"


def test_written_questionnaire_set_answer_inputs_enabled_toggles_read_only():
    _app()
    widget = WrittenQuestionnaire(num_questions=2)

    first = widget.answers[1]
    assert first.isReadOnly() is False

    widget.set_answer_inputs_enabled(False)
    assert first.isReadOnly() is True

    widget.set_answer_inputs_enabled(True)
    assert first.isReadOnly() is False


def test_mcq_questionnaire_set_answer_inputs_enabled_toggles_option_buttons():
    _app()
    widget = MCQQuestionnaire(num_questions=1)
    option_a = widget.radio_buttons[1]["A"]

    assert option_a.isEnabled() is True
    widget.set_answer_inputs_enabled(False)
    assert option_a.isEnabled() is False
    widget.set_answer_inputs_enabled(True)
    assert option_a.isEnabled() is True
