import pytest

pytest.importorskip("PySide6")

from Core.exam_mode import GradingJobInput, GradingWorker
import Core.exam_mode as exam_mode


def test_english_optional_choice_unselected_is_excluded(monkeypatch):
    def _fake_load_key(self):
        return (
            {
                "1": {"answer": "[See Mark Scheme]", "marks": 40},
                "2": {"answer": "[See Mark Scheme]", "marks": 40},
            },
            "loaded/downloaded mark scheme",
        )

    def _fake_grade(**kwargs):
        # Only selected active qids should reach this call.
        qids = set(kwargs.get("answer_key", {}).keys())
        assert qids == {"1"}
        return {
            "total_questions": 1,
            "correct_count": 0,
            "total_marks": 40.0,
            "earned_marks": 0.0,
            "percentage": 0.0,
            "question_results": {
                "1": {
                    "student_answer": "A descriptive writing response",
                    "correct_answer": "[See Mark Scheme]",
                    "is_correct": False,
                    "total_marks": 40.0,
                    "earned_marks": 0.0,
                    "grading_source": "baseline",
                    "ai_error": "",
                }
            },
            "grading_errors": [],
            "ai_used": False,
            "ai_applied_count": 0,
            "baseline_fallback_count": 1,
            "ai_failed_count": 0,
            "ai_quota_exhausted": False,
        }

    monkeypatch.setattr(GradingWorker, "_load_candidate_answer_key", _fake_load_key)
    monkeypatch.setattr(exam_mode, "check_math_paper_answer", _fake_grade)

    job = GradingJobInput(
        answers={
            "1": {"type": "text", "value": "A descriptive writing response"},
            "2": {"type": "text", "value": ""},
        },
        question_ids=["1", "2"],
        question_texts={
            "1": "Choose one of the following writing tasks and write your answer.",
            "2": "Choose one of the following writing tasks and write your answer.",
        },
        question_marks={"1": 40.0, "2": 40.0},
        question_response_types={"1": "text", "2": "text"},
        question_section_types={"1": "written", "2": "written"},
        subject_code="0500",
        paper_num=2,
        year="2025",
        use_ai=False,
    )

    worker = GradingWorker(job)
    captured = []
    worker.finished_payload.connect(lambda payload: captured.append(payload))
    worker.run()

    assert len(captured) == 1
    results = captured[0].results

    assert results["question_results"]["2"]["optional_unselected"] is True
    assert results["question_results"]["2"]["total_marks"] == 0.0
    assert results["pending_manual_count"] == 1
    assert results["pending_manual_marks"] == 40.0
    assert results["auto_graded_total_marks"] == 0.0
    assert results["question_results"]["1"]["manual_review_required"] is True


def test_explicit_optional_selector_overrides_blank_heuristic(monkeypatch):
    def _fake_load_key(self):
        return (
            {
                "1": {"answer": "[See Mark Scheme]", "marks": 40},
                "2": {"answer": "[See Mark Scheme]", "marks": 40},
            },
            "loaded/downloaded mark scheme",
        )

    def _fake_grade(**kwargs):
        qids = set(kwargs.get("answer_key", {}).keys())
        assert qids == {"2"}
        return {
            "total_questions": 1,
            "correct_count": 0,
            "total_marks": 40.0,
            "earned_marks": 0.0,
            "percentage": 0.0,
            "question_results": {
                "2": {
                    "student_answer": "A narrative response",
                    "correct_answer": "[See Mark Scheme]",
                    "is_correct": False,
                    "total_marks": 40.0,
                    "earned_marks": 0.0,
                    "grading_source": "baseline",
                    "ai_error": "",
                }
            },
            "grading_errors": [],
            "ai_used": False,
            "ai_applied_count": 0,
            "baseline_fallback_count": 1,
            "ai_failed_count": 0,
            "ai_quota_exhausted": False,
        }

    monkeypatch.setattr(GradingWorker, "_load_candidate_answer_key", _fake_load_key)
    monkeypatch.setattr(exam_mode, "check_math_paper_answer", _fake_grade)

    job = GradingJobInput(
        answers={
            "1": {"type": "text", "value": "This should be skipped by selector"},
            "2": {"type": "text", "value": "A narrative response"},
        },
        question_ids=["1", "2"],
        question_texts={
            "1": "Choose one of the following writing tasks and write your answer.",
            "2": "Choose one of the following writing tasks and write your answer.",
        },
        question_marks={"1": 40.0, "2": 40.0},
        question_response_types={"1": "text", "2": "text"},
        question_section_types={"1": "written", "2": "written"},
        subject_code="0500",
        paper_num=2,
        year="2025",
        optional_selection={"1|2": ["2"]},
        use_ai=False,
    )

    worker = GradingWorker(job)
    captured = []
    worker.finished_payload.connect(lambda payload: captured.append(payload))
    worker.run()

    assert len(captured) == 1
    results = captured[0].results
    assert results["question_results"]["1"]["optional_unselected"] is True
    assert results["question_results"]["1"]["total_marks"] == 0.0
