"""IGCSE exam metadata helpers backed by canonical subject structures."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Dict, Optional

from Data.igcse_components_registry import (
    get_rows_by_subject,
    get_subject_map,
    normalize_paper_number,
)
from Data.alevel_profiles import get_alevel_subject_map
from Data.subjects_structure import get_paper_spec


# Kept for backward compatibility; the registry now stores canonical values.
SYLLABUS_CHANGE_YEAR = 2025
EXAM_DURATIONS_OLD: Dict[str, Dict[str, int]] = {}
EXAM_DURATIONS_NEW: Dict[str, Dict[str, int]] = {}


MCQ_KEYWORDS = [
    "multiple choice",
    "mcq",
    "written exam (mcq)",
]

MCQ_QUESTION_COUNT_OVERRIDES = {}

TIME_WARNINGS = [15, 5]


def _mcq_question_count_override(subject_code: object, paper_number: object) -> Optional[int]:
    code = str(subject_code or "").strip()
    paper = _paper_base(paper_number)
    if not code or not paper:
        return None
    subject_overrides = MCQ_QUESTION_COUNT_OVERRIDES.get(code, {})
    value = subject_overrides.get(paper)
    if isinstance(value, int) and value > 0:
        return int(value)
    return None


def parse_duration_minutes_from_front_page_text(text: str) -> Optional[int]:
    """Extract likely exam duration (minutes) from paper front-page text."""
    raw = str(text or "")
    if not raw.strip():
        return None

    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines() if str(line).strip()]
    if not lines:
        return None

    hour_pattern = re.compile(
        r"(?<!\d)(\d{1,2})\s*(?:hours?|hrs?|hr|h)\b(?:\s*(\d{1,2})\s*(?:minutes?|mins?|min|m)\b)?",
        re.IGNORECASE,
    )
    minute_pattern = re.compile(r"(?<!\d)(\d{2,3})\s*(?:minutes?|mins?|min)\b", re.IGNORECASE)
    negative_hints = (
        "spend about",
        "per question",
        "for each",
        "section",
        "example",
        "sample",
        "candidate number",
    )

    candidates: list[tuple[int, int]] = []
    for line in lines[:120]:
        lowered = line.lower()
        if not any(token in lowered for token in ("hour", "hr", "min", "minute")):
            continue

        penalty = -4 if any(hint in lowered for hint in negative_hints) else 0
        score_base = 0
        if any(token in lowered for token in ("time", "duration", "allowed", "given")):
            score_base += 4
        if "hour" in lowered or "hr" in lowered:
            score_base += 2

        for match in hour_pattern.finditer(line):
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            total = (hours * 60) + minutes
            if 20 <= total <= 360:
                score = score_base + 4 + penalty
                candidates.append((score, total))

        for match in minute_pattern.finditer(line):
            total = int(match.group(1) or 0)
            if 20 <= total <= 360:
                score = score_base + 1 + penalty
                candidates.append((score, total))

    if not candidates:
        body = re.sub(r"\s+", " ", raw)[:2500]
        for match in hour_pattern.finditer(body):
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            total = (hours * 60) + minutes
            if 20 <= total <= 360:
                candidates.append((1, total))
        for match in minute_pattern.finditer(body):
            total = int(match.group(1) or 0)
            if 20 <= total <= 360:
                candidates.append((0, total))

    if not candidates:
        return None

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = candidates[0][1]
    return int(best) if best > 0 else None


def parse_total_marks_from_front_page_text(text: str) -> Optional[int]:
    """Extract official total marks from front-page text with strict patterns."""
    raw = str(text or "")
    if not raw.strip():
        return None

    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines() if str(line).strip()]
    if not lines:
        return None

    patterns = [
        re.compile(r"\bmaximum\s+marks?\s*[:\-]?\s*(\d{2,3})\b", re.IGNORECASE),
        re.compile(r"\bmax(?:imum)?\s+raw\s+marks?\s*[:\-]?\s*(\d{2,3})\b", re.IGNORECASE),
    ]

    candidates: list[tuple[int, int]] = []
    for idx, line in enumerate(lines[:120]):
        lowered = line.lower()
        if "mark" not in lowered or ("maximum" not in lowered and "max" not in lowered):
            continue

        line_score = 0
        if "maximum" in lowered:
            line_score += 3
        if "raw" in lowered:
            line_score += 1
        if idx <= 6:
            line_score += 2

        for pattern in patterns:
            for match in pattern.finditer(line):
                total = int(match.group(1) or 0)
                if 20 <= total <= 200:
                    candidates.append((line_score, total))

    if not candidates:
        body = re.sub(r"\s+", " ", raw)[:2500]
        for pattern in patterns:
            for match in pattern.finditer(body):
                total = int(match.group(1) or 0)
                if 20 <= total <= 200:
                    candidates.append((0, total))

    if not candidates:
        return None

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = candidates[0][1]
    return int(best) if best > 0 else None


def _coerce_year(year: object) -> int:
    raw = str(year or "").strip()
    if not raw:
        return datetime.now().year
    if len(raw) == 2 and raw.isdigit():
        return 2000 + int(raw)
    try:
        return int(raw)
    except Exception:
        return datetime.now().year


def _paper_base(paper_number: object) -> str:
    return normalize_paper_number(paper_number)


def _row_mode(subject_code: str, paper_number: object) -> str:
    spec = get_paper_spec(subject_code, str(paper_number), exam_year=_coerce_year(None))
    if spec:
        return str(spec.mode or "").strip().upper()
    return "WRITTEN_ONLY"


def _row_assessment_type(subject_code: str, paper_number: object) -> str:
    spec = get_paper_spec(subject_code, str(paper_number), exam_year=_coerce_year(None))
    if spec:
        return str(spec.assessment_type or "").strip().lower()
    return "written"


def _build_paper_structure() -> Dict[str, Dict[str, Dict[str, object]]]:
    out: Dict[str, Dict[str, Dict[str, object]]] = {}
    for code, rows in get_rows_by_subject().items():
        subject_struct: Dict[str, Dict[str, object]] = {}
        for row in rows:
            paper = _paper_base(row.get("paper_number"))
            if not paper:
                continue
            flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
            if not isinstance(flags, dict):
                flags = {}
            mode = str(flags.get("routing_mode", "WRITTEN_ONLY")).upper()
            assessment = str(flags.get("assessment_type", "written")).lower()
            marks = row.get("marks") if isinstance(row.get("marks"), int) else None

            if mode == "MCQ_ONLY":
                override = _mcq_question_count_override(code, paper)
                q_count = override if isinstance(override, int) and override > 0 else (
                    marks if isinstance(marks, int) and marks > 0 else 40
                )
                q_type = "mcq"
            elif assessment == "practical":
                q_count = 3
                q_type = "practical"
            else:
                q_count = 10
                q_type = "written"

            subject_struct[paper] = {
                "questions": int(q_count),
                "subsections": 0,
                "type": q_type,
            }
        if subject_struct:
            out[code] = subject_struct

    out["default"] = {"questions": 10, "subsections": 0, "type": "written"}
    return out


PAPER_STRUCTURE = _build_paper_structure()


def get_paper_structure(subject_code, paper_number):
    """Get fallback paper structure metadata for a specific subject/paper."""
    code = str(subject_code or "").strip()
    base = _paper_base(paper_number)
    subject_structure = PAPER_STRUCTURE.get(code, {})

    if base in subject_structure:
        return dict(subject_structure[base])

    raw = str(paper_number or "").strip()
    if raw in subject_structure:
        return dict(subject_structure[raw])

    default = PAPER_STRUCTURE.get("default", {"questions": 10, "subsections": 0, "type": "written"})
    return dict(default)


def get_question_count(subject_code, paper_number):
    structure = get_paper_structure(subject_code, paper_number)
    return int(structure.get("questions", 10) or 10)


_MATH_SUBJECT_HINTS = ("mathematics", "statistics")
MATH_SUBJECTS = sorted(
    {
        str(code)
        for code, name in {
            **get_subject_map(),
            **get_alevel_subject_map(),
        }.items()
        if any(hint in str(name or "").lower() for hint in _MATH_SUBJECT_HINTS)
    }
)


def is_math_paper(subject_code):
    return str(subject_code or "").strip() in set(MATH_SUBJECTS)


def get_exam_duration(subject_code, paper_number, year=None):
    """Return duration in minutes from canonical paper metadata."""
    code = str(subject_code or "").strip()
    exam_year = _coerce_year(year)
    spec = get_paper_spec(code, str(paper_number), exam_year=exam_year)
    if spec and isinstance(spec.duration_minutes, int) and spec.duration_minutes > 0:
        return int(spec.duration_minutes)
    return 60


def get_paper_type(subject_code, paper_number):
    """Determine if paper is MCQ, Practical, or Written."""
    mode = _row_mode(str(subject_code or "").strip(), paper_number)
    assessment = _row_assessment_type(str(subject_code or "").strip(), paper_number)
    if mode == "MCQ_ONLY":
        return "MCQ"
    if assessment == "practical":
        return "Practical"
    return "Written"


def is_mcq_paper(subject_code, paper_number):
    return _row_mode(str(subject_code or "").strip(), paper_number) == "MCQ_ONLY"


def is_multiple_choice_by_name(subject_name):
    if not subject_name:
        return False
    name_lower = str(subject_name).lower()
    return any(keyword in name_lower for keyword in MCQ_KEYWORDS)


def get_paper_type_from_subject(subject_name, subject_code, paper_number):
    if is_mcq_paper(subject_code, paper_number):
        return "MCQ"
    if is_multiple_choice_by_name(subject_name):
        return "MCQ"
    return get_paper_type(subject_code, paper_number)


def is_multiple_choice_paper(subject_name, subject_code, paper_number):
    return get_paper_type_from_subject(subject_name, subject_code, paper_number) == "MCQ"


def is_multiple_choice_by_paper_suffix(subject_code, paper_number):
    return is_mcq_paper(subject_code, paper_number)


def _build_mcq_question_counts() -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {"default": {"Paper 1": 40, "Paper 2": 40}}
    for code, rows in get_rows_by_subject().items():
        counts: Dict[str, int] = {}
        for row in rows:
            flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
            if not isinstance(flags, dict):
                flags = {}
            if str(flags.get("routing_mode", "")).strip().upper() != "MCQ_ONLY":
                continue
            paper = _paper_base(row.get("paper_number"))
            if not paper:
                continue
            override = _mcq_question_count_override(code, paper)
            marks = row.get("marks") if isinstance(row.get("marks"), int) else None
            counts[f"Paper {paper}"] = (
                int(override) if isinstance(override, int) and override > 0
                else int(marks) if isinstance(marks, int) and marks > 0
                else 40
            )
        if counts:
            out[code] = counts
    return out


MCQ_QUESTION_COUNTS = _build_mcq_question_counts()
MCQ_PAPERS = {
    code: sorted(
        int(key.split(" ", 1)[1])
        for key in counts.keys()
        if key.startswith("Paper ") and key.split(" ", 1)[1].isdigit()
    )
    for code, counts in MCQ_QUESTION_COUNTS.items()
    if code != "default"
}


def get_mcq_count(subject_code, paper_number):
    if not is_mcq_paper(subject_code, paper_number):
        return 0
    override = _mcq_question_count_override(subject_code, paper_number)
    if isinstance(override, int) and override > 0:
        return int(override)
    paper = f"Paper {_paper_base(paper_number)}"
    code = str(subject_code or "").strip()
    counts = MCQ_QUESTION_COUNTS.get(code, MCQ_QUESTION_COUNTS["default"])
    return int(counts.get(paper, 40))
