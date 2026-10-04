"""Curated Cambridge AS/A Level metadata used for search/routing parity."""

from __future__ import annotations

from typing import Dict, Mapping, Optional

from Data.igcse_components_registry import normalize_paper_number
from Data.subject_catalog import ALEVEL_SUBJECTS






def _paper(
    name: str,
    *,
    mode: str,
    assessment_type: str,
    duration_minutes: Optional[int] = None,
    total_marks: Optional[int] = None,
    weight_percent: Optional[float] = None,
    calculator_policy: str = "",
    viewer_only_reason: str = "",
    notes: str = "",
) -> Dict[str, object]:
    return {
        "name": str(name),
        "mode": str(mode),
        "assessment_type": str(assessment_type),
        "duration_minutes": int(duration_minutes) if isinstance(duration_minutes, int) and duration_minutes > 0 else None,
        "total_marks": int(total_marks) if isinstance(total_marks, int) and total_marks > 0 else None,
        "weight_percent": float(weight_percent) if isinstance(weight_percent, (int, float)) else None,
        "calculator_policy": str(calculator_policy),
        "viewer_only_reason": str(viewer_only_reason),
        "notes": str(notes),
    }


# Durations below are used as sane defaults and may be overridden at runtime by
# first-page PDF parsing when available.
ALEVEL_PAPER_DEFINITIONS = {
    "9700": {
        "1": _paper("Paper 1 (Multiple Choice)", mode="MCQ_ONLY", assessment_type="mcq", duration_minutes=60),
        "2": _paper("Paper 2 (AS Level Structured)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "3": _paper("Paper 3 (Advanced Practical Skills)", mode="VIEWER_ONLY", assessment_type="practical", duration_minutes=120,
                    viewer_only_reason="Laboratory practical skills cannot be reliably graded from a PDF answer alone."),
        "4": _paper("Paper 4 (A Level Structured)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "5": _paper("Paper 5 (Planning, Analysis and Evaluation)", mode="WRITTEN_ONLY", assessment_type="practical", duration_minutes=75),
    },
    "9701": {
        "1": _paper("Paper 1 (Multiple Choice)", mode="MCQ_ONLY", assessment_type="mcq", duration_minutes=60),
        "2": _paper("Paper 2 (AS Level Structured)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "3": _paper("Paper 3 (Advanced Practical Skills)", mode="VIEWER_ONLY", assessment_type="practical", duration_minutes=120,
                    viewer_only_reason="Laboratory practical skills cannot be reliably graded from a PDF answer alone."),
        "4": _paper("Paper 4 (A Level Structured)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "5": _paper("Paper 5 (Planning, Analysis and Evaluation)", mode="WRITTEN_ONLY", assessment_type="practical", duration_minutes=75),
    },
    "9702": {
        "1": _paper("Paper 1 (Multiple Choice)", mode="MCQ_ONLY", assessment_type="mcq", duration_minutes=60),
        "2": _paper("Paper 2 (AS Level Structured)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "3": _paper("Paper 3 (Advanced Practical Skills)", mode="VIEWER_ONLY", assessment_type="practical", duration_minutes=120,
                    viewer_only_reason="Laboratory practical skills cannot be reliably graded from a PDF answer alone."),
        "4": _paper("Paper 4 (A Level Structured)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "5": _paper("Paper 5 (Planning, Analysis and Evaluation)", mode="WRITTEN_ONLY", assessment_type="practical", duration_minutes=75),
    },
    "9609": {
        "1": _paper("Paper 1", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "2": _paper("Paper 2", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "3": _paper("Paper 3", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "4": _paper("Paper 4", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
    },
    "9618": {
        "1": _paper("Paper 1 (Theory Fundamentals)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
        "2": _paper("Paper 2 (Fundamental Problem-solving and Programming Skills)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "3": _paper("Paper 3 (Advanced Theory)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
        "4": _paper("Paper 4 (Further Problem-solving and Programming Skills)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
    },
    "9708": {
        "1": _paper("Paper 1 (Multiple Choice)", mode="MCQ_ONLY", assessment_type="mcq", duration_minutes=75),
        "2": _paper("Paper 2 (AS Level Data Response and Essays)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
        "3": _paper("Paper 3 (A Level Data Response and Essays)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=180),
        "4": _paper("Paper 4 (A Level Data Response and Essays)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=150),
    },
    "9709": {
        "1": _paper("Paper 1 (Pure Mathematics 1)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=110),
        "2": _paper("Paper 2 (Pure Mathematics 2)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "3": _paper("Paper 3 (Pure Mathematics 3)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=110),
        "4": _paper("Paper 4 (Mechanics)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "5": _paper("Paper 5 (Probability & Statistics 1)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
        "6": _paper("Paper 6 (Probability & Statistics 2)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=75),
    },
    "9231": {
        "1": _paper("Paper 1 (Further Pure Mathematics 1)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "2": _paper("Paper 2 (Further Pure Mathematics 2)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "3": _paper("Paper 3", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
        "4": _paper("Paper 4", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120),
    },
    "9990": {
        "1": _paper("Paper 1", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
        "2": _paper("Paper 2", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
        "3": _paper("Paper 3", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
        "4": _paper("Paper 4", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=90),
    },
    "9093": {
        "1": _paper("Paper 1 (Reading)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=135, total_marks=50),
        "2": _paper("Paper 2 (Writing)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120, total_marks=50),
        "3": _paper("Paper 3 (Language Analysis)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=135, total_marks=50),
        "4": _paper("Paper 4 (Language Topics)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=135, total_marks=50),
    },
    "9695": {
        "1": _paper("Paper 1 (Drama and Poetry)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120, total_marks=50),
        "2": _paper("Paper 2 (Prose and Unseen)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120, total_marks=50),
        "3": _paper("Paper 3 (Shakespeare and Drama)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120, total_marks=50),
        "4": _paper("Paper 4 (Pre- and Post-1900 Poetry and Prose)", mode="WRITTEN_ONLY", assessment_type="written", duration_minutes=120, total_marks=50),
    },
}


def resolve_alevel_subject_code(subject_code: object) -> str:
    code = str(subject_code or "").strip()
    if not code:
        return ""
    return code


def get_alevel_subject_map() -> Dict[str, str]:
    return {str(code): str(name) for code, name in ALEVEL_SUBJECTS.items()}


def get_alevel_papers(subject_code: str) -> Dict[str, Dict[str, object]]:
    resolved = resolve_alevel_subject_code(subject_code)
    rows = ALEVEL_PAPER_DEFINITIONS.get(resolved, {})
    return {str(paper): dict(meta) for paper, meta in rows.items()}


def get_alevel_paper(subject_code: str, paper_number: object) -> Optional[Dict[str, object]]:
    resolved = resolve_alevel_subject_code(subject_code)
    papers = ALEVEL_PAPER_DEFINITIONS.get(resolved, {})
    if not papers:
        return None
    raw = str(paper_number or "").strip()
    base = normalize_paper_number(raw)
    if base in papers:
        return dict(papers[base])
    if raw in papers:
        return dict(papers[raw])
    return None


def has_alevel_subject(code: object) -> bool:
    return str(code or "").strip() in ALEVEL_SUBJECTS


def get_alevel_definition_map() -> Mapping[str, Dict[str, Dict[str, object]]]:
    out: Dict[str, Dict[str, Dict[str, object]]] = {}
    for code in ALEVEL_SUBJECTS.keys():
        resolved = resolve_alevel_subject_code(code)
        base_rows = ALEVEL_PAPER_DEFINITIONS.get(resolved, {})
        out[str(code)] = {str(paper): dict(meta) for paper, meta in base_rows.items()}
    return out

