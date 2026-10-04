"""Post-grading Cambridge grade-threshold interpretation service."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

try:
    from Core import pdf_service as fitz  # PyMuPDF
except Exception:  # pragma: no cover - runtime optional dependency
    fitz = None  # type: ignore[assignment]


_SERIES_TO_CODE: Dict[str, str] = {
    "MJ": "s",
    "ON": "w",
    "FM": "m",
    "SP": "y",
}
_CODE_TO_SERIES: Dict[str, str] = {v: k for k, v in _SERIES_TO_CODE.items()}
_GRADE_LABEL_RE = re.compile(r"^(A\*|A|B|C|D|E|F|G|U)$", re.IGNORECASE)
_COMPONENT_ROW_RE = re.compile(r"^component\s+(\d{1,2})\b", re.IGNORECASE)
_PAPER_CODE_RE = re.compile(
    r"(?P<subject>\d{4})_(?P<series>[a-z])(?P<yy>\d{2})_(?P<kind>[a-z]{2,3})(?:_(?P<component>\d{1,2}))?",
    re.IGNORECASE,
)
_COMPONENT_GRADE_ORDER: List[str] = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"]


def _normalize_subject_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:4] if len(digits) >= 4 else ""


def _normalize_year(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 2:
        year_int = int(digits)
        return f"20{year_int:02d}" if year_int <= 79 else f"19{year_int:02d}"
    if len(digits) >= 4:
        return digits[:4]
    return ""


def _normalize_series(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text in _SERIES_TO_CODE:
        return text
    aliases = {
        "MAY/JUNE": "MJ",
        "MAY JUNE": "MJ",
        "JUNE": "MJ",
        "OCT/NOV": "ON",
        "OCT NOV": "ON",
        "NOVEMBER": "ON",
        "MARCH": "FM",
        "FEB/MAR": "FM",
        "FEB MAR": "FM",
        "FEBRUARY/MARCH": "FM",
        "FEBRUARY MARCH": "FM",
    }
    return aliases.get(text, "")


def _normalize_component(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 1:
        return f"0{digits}"
    return digits[:2]


def _parse_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return max(0.0, score)


def _series_from_month_line(text: str) -> str:
    cleaned = str(text or "").strip().upper()
    if "JUNE" in cleaned:
        return "MJ"
    if "NOV" in cleaned or "OCT" in cleaned:
        return "ON"
    if "MARCH" in cleaned or "FEB" in cleaned:
        return "FM"
    return ""


def _extract_paper_stub(value: str) -> Dict[str, str]:
    target = str(value or "").strip()
    if not target:
        return {}
    path = urlparse(target).path
    stem = re.sub(r"\.pdf$", "", str(path or target).split("/")[-1], flags=re.IGNORECASE)
    match = _PAPER_CODE_RE.search(stem)
    if not match:
        return {}
    subject = _normalize_subject_code(match.group("subject"))
    year = _normalize_year(match.group("yy"))
    series_code = str(match.group("series") or "").strip().lower()
    series = _CODE_TO_SERIES.get(series_code, "")
    component = _normalize_component(match.group("component") or "")
    kind = str(match.group("kind") or "").strip().lower()
    return {
        "subject_code": subject,
        "year": year,
        "series": series,
        "component": component,
        "kind": kind,
        "series_code": series_code,
    }


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _safe_int(text: str) -> Optional[int]:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw in {"-", "–", "—"}:
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return None
    try:
        return int(round(float(raw)))
    except Exception:
        return None


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if fitz is None:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""
    try:
        parts: List[str] = []
        for page in doc:
            try:
                parts.append(str(page.get_text("text") or ""))
            except Exception:
                continue
        return "\n".join(parts)
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _download_threshold_text(url: str, timeout_seconds: float = 18.0) -> Tuple[str, str]:
    from Core.download_service import fetch_bytes
    target = str(url or "").strip()
    if not target:
        return "", "Grade threshold URL is missing."
    try:
        content = fetch_bytes(target)
        extracted = _extract_pdf_text(content)
    except Exception as exc:
        return "", f"Could not load grade threshold file: {exc}"
    if not str(extracted or "").strip():
        return "", "Could not parse grade threshold PDF text."
    return extracted, ""


def _derive_canonical_gt_url(
    *,
    subject_code: str,
    year: str,
    series: str,
) -> str:
    year_code = year[-2:] if len(year) >= 2 else ""
    series_code = _SERIES_TO_CODE.get(series, "")
    if not (subject_code and year_code and series_code):
        return ""
    return (
        "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/"
        f"{subject_code}_{series_code}{year_code}_gt.pdf"
    )


def _coerce_metadata(
    *,
    subject_code: Any,
    year: Any,
    series: Any,
    component: Any,
    grade_threshold_url: str,
    question_url: str,
    mark_scheme_url: str,
    past_paper_code: str,
) -> Tuple[Dict[str, str], str]:
    subject = _normalize_subject_code(subject_code)
    year_norm = _normalize_year(year)
    series_norm = _normalize_series(series)
    component_norm = _normalize_component(component)

    urls = [grade_threshold_url, question_url, mark_scheme_url, past_paper_code]
    stubs = [_extract_paper_stub(item) for item in urls if str(item or "").strip()]
    stubs = [stub for stub in stubs if stub]

    for stub in stubs:
        if not subject and stub.get("subject_code"):
            subject = stub["subject_code"]
        if not year_norm and stub.get("year"):
            year_norm = stub["year"]
        if not series_norm and stub.get("series"):
            series_norm = stub["series"]
        if not component_norm and stub.get("component"):
            component_norm = stub["component"]

    mismatches: List[str] = []
    for stub in stubs:
        stub_subject = str(stub.get("subject_code") or "")
        stub_year = str(stub.get("year") or "")
        stub_series = str(stub.get("series") or "")
        stub_component = str(stub.get("component") or "")
        kind = str(stub.get("kind") or "")
        if subject and stub_subject and subject != stub_subject:
            mismatches.append("syllabus")
        if year_norm and stub_year and year_norm != stub_year:
            mismatches.append("year")
        if series_norm and stub_series and series_norm != stub_series:
            mismatches.append("series")
        if component_norm and stub_component and kind in {"qp", "ms", "sf", "in", "er"} and component_norm != stub_component:
            mismatches.append("component")

    if mismatches:
        mismatch_text = ", ".join(sorted(set(mismatches)))
        return {}, f"Metadata mismatch detected ({mismatch_text})."

    if not subject:
        return {}, "Missing syllabus code for threshold lookup."
    if not year_norm:
        return {}, "Missing exam year for threshold lookup."
    if not series_norm:
        return {}, "Missing exact exam series for threshold lookup."
    if not component_norm:
        return {}, "Missing exact component code for threshold lookup."

    return {
        "subject_code": subject,
        "year": year_norm,
        "series": series_norm,
        "component": component_norm,
    }, ""


def _parse_grade_headers(lines: List[str], first_component_index: int) -> List[str]:
    lower_lines = [line.lower() for line in lines]
    anchor = -1
    for idx in range(max(0, first_component_index - 40), first_component_index):
        if lower_lines[idx] == "available":
            anchor = idx
    start = anchor + 1 if anchor >= 0 else max(0, first_component_index - 20)
    labels: List[str] = []
    for idx in range(start, first_component_index):
        token = str(lines[idx] or "").strip().upper()
        if not _GRADE_LABEL_RE.match(token):
            continue
        normalized = "A*" if token == "A*" else token
        if normalized not in labels:
            labels.append(normalized)
    if not labels:
        return []
    # Keep deterministic descending order while preserving only present labels.
    ordered = [label for label in _COMPONENT_GRADE_ORDER if label in labels]
    return ordered or labels


def _parse_component_row(
    lines: List[str],
    *,
    component: str,
    grade_headers: List[str],
) -> Tuple[Optional[int], Dict[str, Optional[int]], str]:
    if not grade_headers:
        return None, {}, "Grade header row was not found in threshold table."

    target_component_int = int(component)
    target_idx = -1
    for idx, line in enumerate(lines):
        match = _COMPONENT_ROW_RE.match(str(line or ""))
        if not match:
            continue
        try:
            comp_int = int(match.group(1))
        except Exception:
            continue
        if comp_int == target_component_int:
            target_idx = idx
            break
    if target_idx < 0:
        return None, {}, "Exact component row was not found in threshold table."

    cells: List[str] = []
    for idx in range(target_idx + 1, len(lines)):
        line = str(lines[idx] or "").strip()
        if not line:
            continue
        if _COMPONENT_ROW_RE.match(line):
            break
        low = line.lower()
        if low.startswith("option") or low.startswith("grade thresholds continued"):
            break
        if re.fullmatch(r"\d+(?:\.\d+)?", line) or line in {"-", "–", "—"}:
            cells.append(line)
        if len(cells) >= 1 + len(grade_headers):
            break

    if len(cells) < 1 + len(grade_headers):
        return None, {}, "Component threshold row was incomplete."

    max_raw_mark = _safe_int(cells[0])
    thresholds: Dict[str, Optional[int]] = {}
    for idx, grade in enumerate(grade_headers):
        thresholds[grade] = _safe_int(cells[idx + 1])
    return max_raw_mark, thresholds, ""


def _estimate_grade(
    *,
    candidate_score: float,
    thresholds: Dict[str, Optional[int]],
    grade_headers: List[str],
) -> Tuple[str, str, int]:
    usable: List[Tuple[str, int]] = []
    for grade in grade_headers:
        value = thresholds.get(grade)
        if value is None:
            continue
        usable.append((grade, int(value)))
    if not usable:
        return "", "", 0

    estimated_grade = ""
    matched_index = -1
    for idx, (grade, boundary) in enumerate(usable):
        if candidate_score >= float(boundary):
            estimated_grade = grade
            matched_index = idx
            break

    if estimated_grade:
        if matched_index <= 0:
            return estimated_grade, "", 0
        next_grade, next_boundary = usable[matched_index - 1]
        return estimated_grade, next_grade, max(0, int(math.ceil(float(next_boundary) - candidate_score)))

    lowest_grade, lowest_boundary = usable[-1]
    return f"Below {lowest_grade}", lowest_grade, max(0, int(math.ceil(float(lowest_boundary) - candidate_score)))


def interpret_grade_thresholds(
    *,
    subject_code: Any,
    year: Any,
    series: Any,
    component: Any,
    candidate_score: Any,
    total_mark: Any,
    grade_threshold_url: str = "",
    question_url: str = "",
    mark_scheme_url: str = "",
    past_paper_code: str = "",
    timeout_seconds: float = 18.0,
) -> Dict[str, Any]:
    score = _parse_score(candidate_score)
    total = _parse_score(total_mark)
    base_output: Dict[str, Any] = {
        "available": False,
        "message": "Grade threshold data unavailable for this paper/session.",
        "metadata": {},
        "candidate_score": score,
        "total_mark": total,
        "max_raw_mark": None,
        "thresholds": {},
        "threshold_rows": [],
        "estimated_grade": "",
        "next_grade_label": "",
        "marks_to_next": None,
    }

    meta, meta_error = _coerce_metadata(
        subject_code=subject_code,
        year=year,
        series=series,
        component=component,
        grade_threshold_url=str(grade_threshold_url or ""),
        question_url=str(question_url or ""),
        mark_scheme_url=str(mark_scheme_url or ""),
        past_paper_code=str(past_paper_code or ""),
    )
    if not meta:
        base_output["message"] = f"Grade threshold data unavailable for this paper/session: {meta_error}"
        return base_output

    target_url = str(grade_threshold_url or "").strip()
    if target_url:
        gt_stub = _extract_paper_stub(target_url)
        if gt_stub:
            if gt_stub.get("subject_code") and gt_stub["subject_code"] != meta["subject_code"]:
                base_output["metadata"] = dict(meta)
                base_output["message"] = "Grade threshold data unavailable for this paper/session: Syllabus mismatch."
                return base_output
            if gt_stub.get("year") and gt_stub["year"] != meta["year"]:
                base_output["metadata"] = dict(meta)
                base_output["message"] = "Grade threshold data unavailable for this paper/session: Year mismatch."
                return base_output
            if gt_stub.get("series") and gt_stub["series"] != meta["series"]:
                base_output["metadata"] = dict(meta)
                base_output["message"] = "Grade threshold data unavailable for this paper/session: Series mismatch."
                return base_output
    else:
        target_url = _derive_canonical_gt_url(
            subject_code=meta["subject_code"],
            year=meta["year"],
            series=meta["series"],
        )

    if not target_url:
        base_output["metadata"] = dict(meta)
        base_output["message"] = "Grade threshold data unavailable for this paper/session: Missing exact GT URL."
        return base_output

    gt_text, gt_error = _download_threshold_text(target_url, timeout_seconds=timeout_seconds)
    if not gt_text:
        base_output["metadata"] = dict(meta)
        base_output["metadata"]["grade_threshold_url"] = target_url
        base_output["message"] = f"Grade threshold data unavailable for this paper/session: {gt_error}"
        return base_output

    lines = [_normalize_line(line) for line in str(gt_text or "").splitlines()]
    lines = [line for line in lines if line]

    header_year = ""
    header_series = ""
    header_subject = ""
    for line in lines[:80]:
        low = line.lower()
        if "grade thresholds" in low:
            year_match = re.search(r"(19|20)\d{2}", line)
            if year_match:
                header_year = _normalize_year(year_match.group(0))
            header_series = _series_from_month_line(line)
        if "syllabus" in low:
            match = re.search(r"syllabus\s+(\d{4})", line, flags=re.IGNORECASE)
            if match:
                header_subject = _normalize_subject_code(match.group(1))

    if header_subject and header_subject != meta["subject_code"]:
        base_output["metadata"] = dict(meta)
        base_output["metadata"]["grade_threshold_url"] = target_url
        base_output["message"] = "Grade threshold data unavailable for this paper/session: Syllabus mismatch in GT file."
        return base_output
    if header_year and header_year != meta["year"]:
        base_output["metadata"] = dict(meta)
        base_output["metadata"]["grade_threshold_url"] = target_url
        base_output["message"] = "Grade threshold data unavailable for this paper/session: Year mismatch in GT file."
        return base_output
    if header_series and header_series != meta["series"]:
        base_output["metadata"] = dict(meta)
        base_output["metadata"]["grade_threshold_url"] = target_url
        base_output["message"] = "Grade threshold data unavailable for this paper/session: Series mismatch in GT file."
        return base_output

    first_component_index = -1
    for idx, line in enumerate(lines):
        if _COMPONENT_ROW_RE.match(line):
            first_component_index = idx
            break
    if first_component_index < 0:
        base_output["metadata"] = dict(meta)
        base_output["metadata"]["grade_threshold_url"] = target_url
        base_output["message"] = "Grade threshold data unavailable for this paper/session: Component table not found."
        return base_output

    grade_headers = _parse_grade_headers(lines, first_component_index)
    max_raw_mark, threshold_map, row_error = _parse_component_row(
        lines,
        component=meta["component"],
        grade_headers=grade_headers,
    )
    if row_error:
        base_output["metadata"] = dict(meta)
        base_output["metadata"]["grade_threshold_url"] = target_url
        base_output["message"] = f"Grade threshold data unavailable for this paper/session: {row_error}"
        return base_output

    estimated_grade, next_grade_label, marks_to_next = _estimate_grade(
        candidate_score=score,
        thresholds=threshold_map,
        grade_headers=grade_headers,
    )

    threshold_rows = [{"grade": grade, "mark": threshold_map.get(grade)} for grade in grade_headers]
    output: Dict[str, Any] = dict(base_output)
    output.update(
        {
            "available": True,
            "message": "",
            "metadata": {
                **meta,
                "grade_threshold_url": target_url,
            },
            "max_raw_mark": max_raw_mark,
            "thresholds": dict(threshold_map),
            "threshold_rows": threshold_rows,
            "estimated_grade": estimated_grade,
            "next_grade_label": next_grade_label,
            "marks_to_next": int(marks_to_next),
        }
    )
    return output


__all__ = ["interpret_grade_thresholds"]
