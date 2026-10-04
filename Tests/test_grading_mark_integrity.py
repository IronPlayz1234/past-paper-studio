import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import Core.exam_mode as exam_mode
from Core.exam_mode import GradingJobInput, GradingWorker


def test_badge_source_label_distinguishes_non_baseline_sources():
    assert exam_mode.MathQuestionnaire._badge_source_label({"grading_source": "ai"}) == "AI"
    assert exam_mode.MathQuestionnaire._badge_source_label({"grading_source": "ai_drawing"}) == "AI-DRAW"
    assert exam_mode.MathQuestionnaire._badge_source_label({"grading_source": "rule_engine_math"}) == "RULE"
    assert exam_mode.MathQuestionnaire._badge_source_label({"grading_source": "optional_skipped"}) == "SKIP"
    assert exam_mode.MathQuestionnaire._badge_source_label({"grading_source": "blank_response"}) == "BLANK"
    assert exam_mode.MathQuestionnaire._badge_source_label({"grading_source": "baseline"}) == "BASE"
    assert (
        exam_mode.MathQuestionnaire._badge_source_label(
            {"grading_source": "ai_drawing", "manual_review_required": True}
        )
        == "AI->MANUAL"
    )


def test_worker_keeps_leaf_max_marks_when_official_total_mismatches(monkeypatch):
    def _fake_load_key(self):
        return (
            {
                "1": {"answer": "A", "marks": 1.0},
                "2": {"answer": "B", "marks": 1.0},
            },
            "unit-test-source",
        )

    def _fake_grade(**kwargs):
        answer_key = kwargs.get("answer_key", {})
        question_results = {}
        total_marks = 0.0
        for qid, info in answer_key.items():
            marks = float(info.get("marks", 0.0) or 0.0)
            total_marks += marks
            question_results[qid] = {
                "student_answer": "",
                "correct_answer": str(info.get("answer", "")),
                "is_correct": False,
                "total_marks": marks,
                "earned_marks": 0.0,
                "grading_source": "baseline",
                "ai_error": "",
            }
        return {
            "total_questions": len(question_results),
            "correct_count": 0,
            "total_marks": total_marks,
            "earned_marks": 0.0,
            "percentage": 0.0,
            "question_results": question_results,
            "grading_errors": [],
            "ai_used": False,
            "ai_applied_count": 0,
            "baseline_fallback_count": len(question_results),
            "ai_failed_count": 0,
            "ai_quota_exhausted": False,
        }

    monkeypatch.setattr(GradingWorker, "_load_candidate_answer_key", _fake_load_key)
    monkeypatch.setattr(exam_mode, "check_math_paper_answer", _fake_grade)
    monkeypatch.setattr(exam_mode, "write_grading_report", lambda **kwargs: "")

    job = GradingJobInput(
        answers={
            "1": {"type": "text", "value": "some answer"},
            "2": {"type": "text", "value": ""},
        },
        question_ids=["1", "2"],
        question_texts={"1": "Question 1", "2": "Question 2"},
        question_marks={"1": 1.0, "2": 1.0},
        question_response_types={"1": "text", "2": "text"},
        question_section_types={"1": "written", "2": "written"},
        subject_code="0620",
        paper_num=4,
        year="2025",
        use_ai=False,
        official_total_marks=80.0,
    )

    worker = GradingWorker(job)
    captured = []
    worker.finished_payload.connect(lambda payload: captured.append(payload))
    worker.run()

    assert captured
    results = captured[0].results
    assert float(results["total_marks"]) == pytest.approx(2.0, abs=1e-6)
    row2 = results["question_results"]["2"]
    assert float(row2["total_marks"]) == pytest.approx(1.0, abs=1e-6)
    assert float(row2["earned_marks"]) == 0.0
    assert any("kept leaf max marks unchanged" in str(msg) for msg in results.get("grading_errors", []))
