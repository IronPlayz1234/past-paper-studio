"""Canonical IGCSE components registry backed by the master DOCX extract."""

from __future__ import annotations

from Data.subject_catalog import IGCSE_SUBJECTS

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional


MASTER_DATA_PATH = os.path.join(os.path.dirname(__file__), "igcse_components_master.json")


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _to_int(value: object) -> Optional[int]:
    if value in (None, "", "-", "N/A", "n/a", "Optional", "optional"):
        return None
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _to_float(value: object) -> Optional[float]:
    if value in (None, "", "-", "N/A", "n/a", "Optional", "optional"):
        return None
    try:
        return float(str(value).strip())
    except Exception:
        return None


def normalize_paper_number(value: object, component_label: str = "") -> str:
    text = _clean_text(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        label_digits = re.findall(r"\d+", _clean_text(component_label))
        if label_digits:
            digits = str(label_digits[0])
    if not digits:
        return ""
    if len(digits) == 1:
        return digits
    if digits[0] == "0":
        return digits[1]
    return digits[0]


def _looks_like_mcq(type_text: str, label_text: str, notes_text: str) -> bool:
    haystack = f"{type_text} {label_text} {notes_text}".lower()
    return bool(
        "multiple choice" in haystack
        or " mcq" in f" {haystack}"
        or "mcq " in f"{haystack} "
        or "(mcq)" in haystack
        or "objective" in haystack
    )


def _looks_like_written_content(type_text: str, label_text: str, notes_text: str) -> bool:
    haystack = f"{type_text} {label_text} {notes_text}".lower()
    written_hints = (
        "short-answer",
        "short answer",
        "structured",
        "extended response",
        "essay",
        "composition",
        "theory",
    )
    return any(hint in haystack for hint in written_hints)


def _looks_like_listening(type_text: str, label_text: str) -> bool:
    scope = f"{type_text} {label_text}".lower()
    if "listening" in scope:
        return True
    # Some language papers are labelled as "Written Exam (Aural)".
    return ("aural" in scope) and ("oral/" not in scope) and ("speaking" not in scope)


def _looks_like_speaking_or_oral(type_text: str, label_text: str) -> bool:
    scope = f"{type_text} {label_text}".lower()
    return bool(
        "speaking" in scope
        or "oral" in scope
        or "oral/" in scope
        or "viva" in scope
    )


def _looks_like_coursework(type_text: str, label_text: str) -> bool:
    scope = f"{type_text} {label_text}".lower()
    return "coursework" in scope or "portfolio" in scope


def _looks_like_internal_practical(type_text: str, label_text: str, notes_text: str) -> bool:
    scope = f"{type_text} {label_text} {notes_text}".lower()
    return ("practical" in scope) and ("internal" in scope)


def _looks_like_practical_exam_only(type_text: str, label_text: str, notes_text: str) -> bool:
    scope = f"{type_text} {label_text} {notes_text}".lower()
    if "alternative to practical" in scope:
        return False
    if "practical exam" in scope:
        return True
    if "written/practical" in scope:
        return False
    # Practical papers that are not explicitly written-only are treated as viewer-only.
    return ("practical" in scope) and ("written exam" not in scope)


def _infer_calculator_policy(
    raw_flags: Dict[str, Any],
    type_text: str,
    label_text: str,
    notes_text: str,
) -> str:
    policy = _clean_text(raw_flags.get("calculator_policy")).lower()
    if policy in {"required", "not_allowed"}:
        return policy

    haystack = f"{type_text} {label_text} {notes_text}".lower()
    if "non-calculator" in haystack or "no calculator" in haystack:
        return "not_allowed"
    if "calculator" in haystack:
        return "required"
    return ""


def _build_flags(row: Dict[str, Any]) -> Dict[str, Any]:
    type_text = _clean_text(row.get("type"))
    label_text = _clean_text(row.get("component_label"))
    notes_text = _clean_text(row.get("notes"))
    raw_flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
    if not isinstance(raw_flags, dict):
        raw_flags = {}

    is_mcq_like = _looks_like_mcq(type_text, label_text, notes_text)
    has_written_signals = _looks_like_written_content(type_text, label_text, notes_text)
    is_listening = _looks_like_listening(type_text, label_text)
    is_speaking_or_oral = _looks_like_speaking_or_oral(type_text, label_text)
    is_coursework = _looks_like_coursework(type_text, label_text)
    is_internal_practical = _looks_like_internal_practical(type_text, label_text, notes_text)
    is_practical_exam_only = _looks_like_practical_exam_only(type_text, label_text, notes_text)
    calculator_policy = _infer_calculator_policy(raw_flags, type_text, label_text, notes_text)

    # Speaking/oral/coursework/practical should remain viewer-only even when
    # labels contain "listening" (e.g., speaking & listening endorsements).
    if is_speaking_or_oral or is_coursework or is_internal_practical or is_practical_exam_only:
        routing_mode = "VIEWER_ONLY"
        if is_coursework:
            assessment_type = "coursework"
        elif is_speaking_or_oral:
            assessment_type = "speaking"
        else:
            assessment_type = "practical"
    elif is_listening:
        routing_mode = "MCQ_ONLY"
        assessment_type = "listening"
    elif is_mcq_like and has_written_signals:
        routing_mode = "MIXED"
        assessment_type = "mixed"
    elif is_mcq_like:
        routing_mode = "MCQ_ONLY"
        assessment_type = "mcq"
    else:
        routing_mode = "WRITTEN_ONLY"
        assessment_type = "written"

    return {
        "is_mcq_like": bool(is_mcq_like),
        "is_listening": bool(is_listening),
        "is_speaking_or_oral": bool(is_speaking_or_oral),
        "is_coursework": bool(is_coursework),
        "is_internal_practical": bool(is_internal_practical),
        "calculator_policy": calculator_policy,
        "routing_mode": routing_mode,
        "assessment_type": assessment_type,
    }


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    subject_code = _clean_text(row.get("subject_code"))
    subject_name = _clean_text(row.get("subject_name"))
    component_label = _clean_text(row.get("component_label"))
    paper_number = normalize_paper_number(row.get("paper_number"), component_label=component_label)

    normalized: Dict[str, Any] = {
        "subject_code": subject_code,
        "subject_name": subject_name,
        "category": _clean_text(row.get("category")),
        "subject_heading": _clean_text(row.get("subject_heading")),
        "component_label": component_label,
        "paper_number": paper_number,
        "type": _clean_text(row.get("type")),
        "duration_text": _clean_text(row.get("duration_text")),
        "duration_minutes": _to_int(row.get("duration_minutes")),
        "marks_text": _clean_text(row.get("marks_text")),
        "marks": _to_int(row.get("marks")),
        "weighting_text": _clean_text(row.get("weighting_text")),
        "weight_percent": _to_float(row.get("weight_percent")),
        "notes": _clean_text(row.get("notes")),
        "flags": {},
    }
    normalized["flags"] = _build_flags(normalized)
    return normalized


@lru_cache(maxsize=1)
def load_master_payload() -> Dict[str, Any]:
    if not os.path.exists(MASTER_DATA_PATH):
        return {"subjects": [], "rows": [], "subject_count": 0, "row_count": 0}
    try:
        with open(MASTER_DATA_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"subjects": [], "rows": [], "subject_count": 0, "row_count": 0}


@lru_cache(maxsize=1)
def get_all_rows() -> List[Dict[str, Any]]:
    payload = load_master_payload()
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        norm = _normalize_row(row)
        if not norm["subject_code"] or not norm["paper_number"]:
            continue
        normalized.append(norm)

    normalized.sort(
        key=lambda item: (
            item["subject_code"],
            int(item["paper_number"]) if str(item["paper_number"]).isdigit() else 99,
        )
    )
    return normalized


@lru_cache(maxsize=1)
def get_subject_map() -> Dict[str, str]:
    rows = get_all_rows()
    out: Dict[str, str] = {}
    for row in rows:
        code = str(row.get("subject_code", "")).strip()
        name = str(row.get("subject_name", "")).strip()
        if code in IGCSE_SUBJECTS and name and code not in out:
            out[code] = name
    return out


@lru_cache(maxsize=1)
def get_rows_by_subject() -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in get_all_rows():
        grouped.setdefault(str(row["subject_code"]), []).append(dict(row))
    return grouped


def get_subject_rows(subject_code: str) -> List[Dict[str, Any]]:
    code = _clean_text(subject_code)
    return [dict(item) for item in get_rows_by_subject().get(code, [])]


def get_subject_row(subject_code: str, paper_number: object) -> Optional[Dict[str, Any]]:
    code = _clean_text(subject_code)
    paper = normalize_paper_number(paper_number)
    if not code or not paper:
        return None
    for row in get_rows_by_subject().get(code, []):
        if str(row.get("paper_number", "")) == paper:
            return dict(row)
    return None


def list_subject_codes() -> List[str]:
    return sorted(get_subject_map().keys())


def component_aliases_for_paper(
    paper_number: object,
    *,
    include_legacy_variants: bool = True,
) -> List[str]:
    paper = normalize_paper_number(paper_number)
    if not paper:
        return []

    out: List[str] = []
    seen: set[str] = set()

    def _add(value: object) -> None:
        text = _clean_text(value)
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    _add(paper)
    _add(f"0{paper}")
    _add(f"{paper}{paper}")
    if include_legacy_variants:
        for variant in ("1", "2", "3"):
            _add(f"{paper}{variant}")
    return out


def component_matches_paper(component: object, paper_number: object) -> bool:
    return normalize_paper_number(component) == normalize_paper_number(paper_number)


__all__ = [
    "MASTER_DATA_PATH",
    "component_aliases_for_paper",
    "component_matches_paper",
    "get_all_rows",
    "get_subject_map",
    "get_subject_row",
    "get_subject_rows",
    "get_rows_by_subject",
    "list_subject_codes",
    "load_master_payload",
    "normalize_paper_number",
]
