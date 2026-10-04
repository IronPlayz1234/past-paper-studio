import json
import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import Utils.dev_test_attempts as dev_test_attempts
from Core.exam_mode import ExamModeWindow, MathQuestionnaire
from Utils.gui_utils import ExamAttemptManager
from Utils.question_id_mapper import QuestionLeaf


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_attempt() -> dict:
    return {
        "attempt_key": "attempt-1",
        "paper_code": "0620_s24_qp_42",
        "subject_code": "0620",
        "subject_name": "Chemistry",
        "paper_num": "4",
        "year": "2025",
        "pdf_url": "https://example.com/0620_s24_qp_42.pdf",
        "remaining_seconds": 1234,
        "answers": {"1": {"type": "text", "value": "sample"}},
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }


def test_exam_attempt_manager_recovers_from_backup_when_primary_is_corrupt(tmp_path: Path, monkeypatch):
    attempts_file = tmp_path / "unfinished_exam_attempts.json"
    backup_file = tmp_path / "unfinished_exam_attempts.backup.json"
    assets_root = tmp_path / "attempt_assets"
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPTS_FILE", str(attempts_file))
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPTS_BACKUP_FILE", str(backup_file))
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPT_ASSETS_ROOT", str(assets_root))

    entry = _sample_attempt()
    assert ExamAttemptManager.save_attempts([entry]) is True
    attempts_file.write_text("{not-valid-json", encoding="utf-8")

    recovered = ExamAttemptManager.load_attempts()
    assert recovered and recovered[0]["attempt_key"] == entry["attempt_key"]
    repaired_payload = json.loads(attempts_file.read_text(encoding="utf-8"))
    assert isinstance(repaired_payload, list) and repaired_payload


def test_filter_answers_for_resume_keeps_drawing_and_copies_asset(tmp_path: Path, monkeypatch):
    assets_root = tmp_path / "attempt_assets"
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPT_ASSETS_ROOT", str(assets_root))

    drawing_source = tmp_path / "drawing.png"
    drawing_source.write_bytes(b"fake-image")

    window = ExamModeWindow.__new__(ExamModeWindow)
    window._attempt_key = "attempt-key"

    payload = {
        "1": {
            "type": "drawing",
            "image_path": str(drawing_source),
            "notes": "label nucleus",
        }
    }
    filtered = ExamModeWindow._filter_answers_for_resume(window, payload)

    assert "1" in filtered
    assert filtered["1"]["type"] == "drawing"
    copied_path = Path(str(filtered["1"]["image_path"]))
    assert copied_path.exists()
    assert copied_path.read_bytes() == b"fake-image"
    assert str(copied_path).startswith(str(assets_root))


def test_math_questionnaire_restores_drawing_answers_from_snapshot(tmp_path: Path):
    _app()
    session_dir = tmp_path / "drawings"
    session_dir.mkdir(parents=True, exist_ok=True)
    saved_drawing = tmp_path / "saved.png"
    saved_drawing.write_bytes(b"drawing-bytes")

    question = QuestionLeaf(
        canonical_id="1",
        display_id="1",
        main=1,
        text="Draw and label an animal cell.",
        response_type="drawing",
        section_type="written",
    )
    widget = MathQuestionnaire(
        question_items=[question],
        drawing_session_dir=str(session_dir),
        drawing_file_prefix="unit_test",
    )
    widget.apply_saved_answers(
        {
            "1": {
                "type": "drawing",
                "image_path": str(saved_drawing),
                "notes": "added membrane label",
            }
        }
    )

    answers = widget.get_answers()
    assert "1" in answers
    assert answers["1"]["type"] == "drawing"
    assert answers["1"]["notes"] == "added membrane label"
    restored_path = Path(str(answers["1"]["image_path"]))
    assert restored_path.exists()
    assert restored_path.parent == session_dir


def test_dev_test_attempt_snapshot_restores_text_table_and_drawing_answers(tmp_path: Path, monkeypatch):
    _app()
    monkeypatch.setenv(dev_test_attempts.DEV_TEST_ENV, "1")
    monkeypatch.setattr(dev_test_attempts.sys, "frozen", False, raising=False)

    local_pdf = tmp_path / "0620_s22_qp_42.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 dev test")
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_LOCAL_QP_PATH", str(local_pdf))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_ASSETS_ROOT", str(tmp_path / "dev_assets"))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_SEARCH_CACHE_FILE", str(tmp_path / "paper_search_cache.json"))

    snapshot = dev_test_attempts.build_dev_test_attempt()
    assert isinstance(snapshot, dict)
    assert snapshot["answers"]["1(a)"]["value"] == "Mg"
    assert snapshot["answers"]["3(a)(iii)"]["cells"]["1,0"] == "24"
    assert snapshot["answers"]["6(c)(i)"]["notes"] == "name: but-2-ene"

    session_dir = tmp_path / "drawings"
    session_dir.mkdir(parents=True, exist_ok=True)

    text_question = QuestionLeaf(
        canonical_id="1(a)",
        display_id="1(a)",
        main=1,
        part="a",
        text="State the symbol.",
        response_type="text",
        section_type="written",
    )
    table_question = QuestionLeaf(
        canonical_id="3(a)(iii)",
        display_id="3(a)(iii)",
        main=3,
        part="a",
        subpart="iii",
        text="Complete the table.",
        response_type="table",
        section_type="written",
        table_spec={
            "rows": 2,
            "cols": 3,
            "cells": [
                {"row": 0, "col": 0, "text": "protons", "missing": False, "is_answer": False},
                {"row": 0, "col": 1, "text": "neutrons", "missing": False, "is_answer": False},
                {"row": 0, "col": 2, "text": "electrons", "missing": False, "is_answer": False},
                {"row": 1, "col": 0, "text": "", "missing": False, "is_answer": True, "input_kind": "text"},
                {"row": 1, "col": 1, "text": "", "missing": False, "is_answer": True, "input_kind": "text"},
                {"row": 1, "col": 2, "text": "", "missing": False, "is_answer": True, "input_kind": "text"},
            ],
            "answer_cell_count": 3,
        },
    )
    drawing_question = QuestionLeaf(
        canonical_id="6(c)(i)",
        display_id="6(c)(i)",
        main=6,
        part="c",
        subpart="i",
        text="Draw and name the structure of the monomer.",
        response_type="drawing",
        section_type="written",
    )

    widget = MathQuestionnaire(
        question_items=[text_question, table_question, drawing_question],
        drawing_session_dir=str(session_dir),
        drawing_file_prefix="dev_test",
    )
    widget.apply_saved_answers(snapshot["answers"])

    answers = widget.get_answers()
    assert answers["1(a)"]["value"] == "Mg"
    assert answers["3(a)(iii)"]["cells"]["1,0"] == "24"
    assert answers["3(a)(iii)"]["cells"]["1,1"] == "28"
    assert answers["3(a)(iii)"]["cells"]["1,2"] == "24"
    assert answers["6(c)(i)"]["notes"] == "name: but-2-ene"
    restored_path = Path(str(answers["6(c)(i)"]["image_path"]))
    assert restored_path.exists()
    assert restored_path.parent == session_dir
