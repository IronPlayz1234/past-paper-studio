"""Centralized routing for subject/paper exam modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from Data.subjects_structure import get_paper_spec
from Data.subject_catalog import SUPPORTED_SUBJECTS


@dataclass(frozen=True, slots=True)
class PaperModeDecision:
    subject_code: str
    paper_number: str
    exam_year: int
    mode: str
    gradable: bool
    has_mcq: bool
    has_written: bool
    assessment_type: str
    viewer_only_reason: str = ""
    ai_profile: str = ""
    supports_drawing_manual_review: bool = True
    duration_minutes: Optional[int] = None
    total_marks: Optional[int] = None
    weight_percent: Optional[float] = None
    calculator_policy: str = ""
    notes: str = ""


def resolve_mode(subject_code: str, paper_number: str, exam_year: int = 2026) -> PaperModeDecision:
    """Resolve paper mode using year-aware official subject metadata.

    Unknown subjects and components are viewer-only, without automatic grading.
    """
    if str(subject_code).strip() not in SUPPORTED_SUBJECTS:
        return PaperModeDecision(str(subject_code), str(paper_number), int(exam_year),
            "VIEWER_ONLY", False, False, False, "unsupported",
            viewer_only_reason="This subject is outside the Alpha 7.5 catalog. Saved data is retained for viewing.")
    spec = get_paper_spec(subject_code, paper_number, exam_year=exam_year)
    if spec:
        return PaperModeDecision(
            subject_code=str(subject_code),
            paper_number=str(paper_number),
            exam_year=int(exam_year),
            mode=spec.mode,
            gradable=spec.gradable,
            has_mcq=spec.has_mcq,
            has_written=spec.has_written,
            assessment_type=spec.assessment_type,
            viewer_only_reason=spec.viewer_only_reason,
            ai_profile=spec.ai_profile,
            supports_drawing_manual_review=spec.supports_drawing_manual_review,
            duration_minutes=spec.duration_minutes,
            total_marks=spec.total_marks,
            weight_percent=spec.weight_percent,
            calculator_policy=spec.calculator_policy,
            notes=spec.notes,
        )

    return PaperModeDecision(
        subject_code=str(subject_code), paper_number=str(paper_number), exam_year=int(exam_year),
        mode="VIEWER_ONLY", gradable=False, has_mcq=False, has_written=False,
        assessment_type="unknown",
        viewer_only_reason="No supported component metadata is available. This paper can be viewed without automatic grading.",
    )


def should_enable_auto_grading(decision: PaperModeDecision) -> bool:
    return bool(decision.gradable and decision.mode in {"MCQ_ONLY", "WRITTEN_ONLY", "MIXED"})


def should_enable_ai_grading(decision: PaperModeDecision) -> bool:
    if not decision.gradable:
        return False
    return decision.mode in {"WRITTEN_ONLY", "MIXED"}


def is_viewer_only(decision: Optional[PaperModeDecision]) -> bool:
    return bool(decision and decision.mode == "VIEWER_ONLY")
