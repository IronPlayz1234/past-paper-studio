import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from Core.exam_mode import ExamModeWindow


class _DummyQuestionnaire:
    def __init__(self):
        self.last_payload = None

    def highlight_results(self, payload):
        self.last_payload = payload


class _DummyResultsPanel:
    def __init__(self):
        self.summary = ""
        self.visible = False

    def update_summary(self, text):
        self.summary = str(text)

    def show(self):
        self.visible = True


class _DummyTimer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _base_results() -> dict:
    return {
        "mode": "WRITTEN_ONLY",
        "earned_marks": 63.0,
        "total_marks": 80.0,
        "percentage": 78.75,
        "auto_graded_marks": 63.0,
        "auto_graded_total_marks": 80.0,
        "pending_manual_marks": 0.0,
        "pending_manual_count": 0,
        "final_confirmed_marks": 63.0,
        "question_results": {},
        "grading_errors": [],
    }


def _base_window() -> ExamModeWindow:
    window = ExamModeWindow.__new__(ExamModeWindow)
    window.questionnaire = _DummyQuestionnaire()
    window.results_panel = _DummyResultsPanel()
    window.timer = _DummyTimer()
    window.paper_mode = "WRITTEN_ONLY"
    return window


def test_apply_grading_results_keeps_existing_summary_and_appends_threshold_block():
    window = _base_window()
    results = _base_results()
    results["threshold_interpretation"] = {
        "available": True,
        "candidate_score": 63,
        "max_raw_mark": 80,
        "threshold_rows": [
            {"grade": "A*", "mark": 67},
            {"grade": "A", "mark": 59},
            {"grade": "B", "mark": 51},
            {"grade": "C", "mark": 44},
        ],
        "estimated_grade": "A",
        "next_grade_label": "A*",
        "marks_to_next": 4,
    }

    window._apply_grading_results(results, SimpleNamespace(coverage=0.935), "loaded/downloaded mark scheme")
    summary = window.results_panel.summary

    assert "Mode: WRITTEN_ONLY | Key source: loaded/downloaded mark scheme" in summary
    assert "Auto-graded: 63.0/80.0 (78.8%)" in summary
    assert "Mapping coverage: 93.5% (loaded/downloaded mark scheme)" in summary
    assert "Grade Thresholds" in summary
    assert "Estimated Grade: A" in summary
    assert "Marks to A*: 4" in summary
    assert window.results_panel.visible is True
    assert window.timer.stopped is True


def test_apply_grading_results_without_threshold_payload_keeps_summary_clean():
    window = _base_window()
    results = _base_results()

    window._apply_grading_results(results, SimpleNamespace(coverage=0.9), "mark scheme")
    summary = window.results_panel.summary

    assert "Auto-graded: 63.0/80.0 (78.8%)" in summary
    assert "Mapping coverage: 90.0% (mark scheme)" in summary
    assert "Grade Thresholds" not in summary


def test_apply_grading_results_handles_unavailable_threshold_payload():
    window = _base_window()
    results = _base_results()
    results["pending_manual_count"] = 2
    results["threshold_interpretation"] = {
        "available": False,
        "candidate_score": 63,
        "total_mark": 80,
        "message": "Grade threshold data unavailable for this paper/session: Exact component row was not found in threshold table.",
    }

    window._apply_grading_results(results, SimpleNamespace(coverage=0.9), "mark scheme")
    summary = window.results_panel.summary

    assert "Grade Thresholds" in summary
    assert "Grade threshold data unavailable for this paper/session" in summary
