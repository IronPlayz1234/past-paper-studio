import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Core.exam_mode import MathQuestionnaire, SuperscriptTextEdit, TableAnswerWidget, WrittenQuestionnaire
from Utils.question_id_mapper import QuestionLeaf


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _char_alignment(editor: SuperscriptTextEdit, index: int) -> QTextCharFormat.VerticalAlignment:
    cursor = QTextCursor(editor.document())
    cursor.setPosition(index)
    cursor.setPosition(index + 1, QTextCursor.MoveMode.KeepAnchor)
    return cursor.charFormat().verticalAlignment()


def test_editor_typing_keeps_literal_caret_text():
    _app()
    editor = SuperscriptTextEdit()
    editor.setFocus()

    QTest.keyClicks(editor, "a^10")

    assert editor.toPlainText() == "a^10"
    assert editor.to_caret_text() == "a^10"
    assert _char_alignment(editor, 1) == QTextCharFormat.VerticalAlignment.AlignNormal


def test_editor_context_formatting_supports_super_sub_and_normal_reset():
    _app()
    editor = SuperscriptTextEdit()
    editor.setPlainText("x10 y2")

    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor._set_script_mode("super")
    assert editor.to_caret_text() == "x^{10} y2"

    cursor = editor.textCursor()
    cursor.setPosition(5)
    cursor.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor._set_script_mode("sub")
    assert editor.to_caret_text() == "x^{10} y_{2}"

    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor._set_script_mode("normal")
    assert editor.to_caret_text() == "x10 y_{2}"


def test_written_questionnaire_down_arrow_navigation_between_inputs():
    _app()
    widget = WrittenQuestionnaire(num_questions=2)
    first = widget.answers[1]
    second = widget.answers[2]

    first.setFocus()
    QTest.keyClick(first, Qt.Key.Key_Down)
    assert widget.focusWidget() is second


def test_math_questionnaire_text_answers_preserve_script_notation_on_save_restore():
    _app()
    question = QuestionLeaf(
        canonical_id="1",
        display_id="1",
        main=1,
        text="State the value of x.",
        response_type="text",
        section_type="written",
    )
    widget = MathQuestionnaire(question_items=[question])
    entry = widget.answers["1"]
    entry.set_caret_text("x^{10} + y_{2}")

    saved = widget.get_answers()
    assert saved["1"]["type"] == "text"
    assert saved["1"]["value"] == "x^{10} + y_{2}"

    widget.apply_saved_answers(saved)
    assert widget.answers["1"].to_caret_text() == "x^{10} + y_{2}"


def test_math_questionnaire_drawing_notes_preserve_script_notation_on_save_restore():
    _app()
    question = QuestionLeaf(
        canonical_id="1",
        display_id="1",
        main=1,
        text="Draw and label apparatus.",
        response_type="drawing",
        section_type="written",
    )
    widget = MathQuestionnaire(question_items=[question])

    widget.apply_saved_answers(
        {
            "1": {
                "type": "drawing",
                "image_path": "",
                "notes": "t^{2} + c_{p}",
            }
        }
    )

    answers = widget.get_answers()
    assert answers["1"]["type"] == "drawing"
    assert answers["1"]["notes"] == "t^{2} + c_{p}"
    assert widget.drawing_note_inputs["1"].to_caret_text() == "t^2 + c_{p}"


def test_table_tick_inputs_serialize_as_check_and_no_check():
    _app()
    widget = TableAnswerWidget(
        table_spec={
            "rows": 1,
            "cols": 2,
            "cells": [
                {"row": 0, "col": 0, "text": "", "missing": False, "is_answer": True, "input_kind": "tick"},
                {"row": 0, "col": 1, "text": "", "missing": False, "is_answer": True, "input_kind": "tick"},
            ],
        }
    )

    defaults = widget.get_cell_answers()
    assert defaults == {"0,0": "No Check", "0,1": "No Check"}

    widget.tick_inputs[(0, 0)].setChecked(True)
    payload = widget.get_cell_answers()
    assert payload["0,0"] == "Check"
    assert payload["0,1"] == "No Check"

    serialized = widget.to_serialized_answer()
    assert "R1C1=Check" in serialized
    assert "R1C2=No Check" in serialized

    widget.set_cell_answers({"0,0": "No Check", "0,1": "Check"})
    assert widget.tick_inputs[(0, 0)].isChecked() is False
    assert widget.tick_inputs[(0, 1)].isChecked() is True
