import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import Core.exam_mode as exam_mode
from Core.exam_mode import GradingJobInput, GradingWorker


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _build_drawing_job(image_path: str, *, question_marks: float = 4.0, official_total_marks: float | None = None) -> GradingJobInput:
    return GradingJobInput(
        answers={"1": {"type": "drawing", "image_path": image_path, "notes": "diagram notes"}},
        question_ids=["1"],
        question_texts={"1": "Draw and label an animal cell."},
        question_marks={"1": float(question_marks)},
        question_response_types={"1": "drawing"},
        question_section_types={"1": "written"},
        subject_code="0610",
        paper_num=4,
        year="2025",
        use_ai=True,
        official_total_marks=official_total_marks,
    )


def _stub_answer_key():
    return (
        {
            "1": {
                "answer": "mark scheme",
                "mark_scheme_text": "cell membrane labelled\nnucleus labelled",
                "marks": 3.0,
            }
        },
        "unit-test-source",
    )


def test_drawing_desktop_temp_copy_is_deleted_after_success(monkeypatch, tmp_path: Path):
    _app()
    home = tmp_path / "home"
    desktop = home / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    source_image = tmp_path / "source.png"
    source_image.write_bytes(b"source-image")

    monkeypatch.setattr(exam_mode.GradingWorker, "_load_candidate_answer_key", lambda self: _stub_answer_key())
    monkeypatch.setattr(exam_mode, "write_grading_report", lambda **kwargs: str(tmp_path / "report.md"))

    observed_temp_paths = []

    def _fake_grade_drawing_question(**kwargs):
        temp_path = str(kwargs.get("image_path", ""))
        observed_temp_paths.append(temp_path)
        assert os.path.exists(temp_path)
        return {
            "manual_review_required": False,
            "status": "graded",
            "marks": 3.0,
            "feedback": "Matched three points.",
            "error": "",
            "raw_response": "Reasoning...\nFINAL MARK: 3",
            "parse_status": "final_mark_line",
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        }

    monkeypatch.setattr(exam_mode, "grade_drawing_question", _fake_grade_drawing_question)

    worker = GradingWorker(_build_drawing_job(str(source_image)))
    captured = []
    worker.finished_payload.connect(lambda payload: captured.append(payload))
    worker.run()

    assert captured
    payload = captured[0]
    assert payload.results.get("grading_report_path") == str(tmp_path / "report.md")
    assert observed_temp_paths
    from Core.download_service import temp_directory
    assert Path(observed_temp_paths[0]).parent == Path(temp_directory())
    assert not Path(observed_temp_paths[0]).exists()
    assert source_image.exists()
    assert list(desktop.glob("ppf_drawing_grade_*.png")) == []


def test_drawing_desktop_temp_copy_is_deleted_when_vision_grading_raises(monkeypatch, tmp_path: Path):
    _app()
    home = tmp_path / "home"
    desktop = home / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    source_image = tmp_path / "source.png"
    source_image.write_bytes(b"source-image")

    monkeypatch.setattr(exam_mode.GradingWorker, "_load_candidate_answer_key", lambda self: _stub_answer_key())
    monkeypatch.setattr(exam_mode, "write_grading_report", lambda **kwargs: str(tmp_path / "report.md"))

    observed_temp_paths = []

    def _failing_grade_drawing_question(**kwargs):
        temp_path = str(kwargs.get("image_path", ""))
        observed_temp_paths.append(temp_path)
        assert os.path.exists(temp_path)
        raise RuntimeError("vision service unavailable")

    monkeypatch.setattr(exam_mode, "grade_drawing_question", _failing_grade_drawing_question)

    worker = GradingWorker(_build_drawing_job(str(source_image)))
    captured = []
    worker.finished_payload.connect(lambda payload: captured.append(payload))
    worker.run()

    assert captured
    row = captured[0].results["question_results"]["1"]
    assert row["manual_review_required"] is True
    assert row["manual_review_status"] == "grading_failed_pending_review"
    assert "drawing_ai_error" in row.get("warnings", [])
    assert float(row.get("earned_marks", 0.0)) == 0.0
    assert observed_temp_paths
    assert list(desktop.glob("ppf_drawing_grade_*.png")) == []


def test_drawing_question_uses_reconciled_max_marks(monkeypatch, tmp_path: Path):
    _app()
    source_image = tmp_path / "source.png"
    source_image.write_bytes(b"source-image")

    monkeypatch.setattr(exam_mode.GradingWorker, "_load_candidate_answer_key", lambda self: _stub_answer_key())
    monkeypatch.setattr(exam_mode, "write_grading_report", lambda **kwargs: str(tmp_path / "report.md"))

    def _fake_grade_drawing_question(**kwargs):
        assert float(kwargs.get("max_marks", 0.0)) == pytest.approx(3.0, abs=1e-6)
        return {
            "manual_review_required": False,
            "status": "graded",
            "marks": 2.0,
            "feedback": "Two points credited.",
            "error": "",
            "raw_response": "FINAL MARK: 2",
            "parse_status": "final_mark_line",
            "model": "test-model",
        }

    monkeypatch.setattr(exam_mode, "grade_drawing_question", _fake_grade_drawing_question)

    worker = GradingWorker(
        _build_drawing_job(
            str(source_image),
            question_marks=1.0,
            official_total_marks=3.0,
        )
    )
    captured = []
    worker.finished_payload.connect(lambda payload: captured.append(payload))
    worker.run()

    assert captured
    row = captured[0].results["question_results"]["1"]
    assert float(row["total_marks"]) == pytest.approx(3.0, abs=1e-6)
    assert float(row["earned_marks"]) == pytest.approx(2.0, abs=1e-6)
