"""Year-aware Cambridge subject and paper structure metadata."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Optional

from Data.alevel_profiles import (
    get_alevel_definition_map,
    get_alevel_subject_map,
    resolve_alevel_subject_code,
)
from Data.igcse_components_registry import (
    get_rows_by_subject,
    get_subject_map,
    normalize_paper_number,
)


ASSESSMENT_MODES = {
    "MCQ_ONLY",
    "WRITTEN_ONLY",
    "MIXED",
    "VIEWER_ONLY",
}


@dataclass(frozen=True, slots=True)
class YearRange:
    start: int
    end: int

    def includes(self, year: int) -> bool:
        return self.start <= year <= self.end


@dataclass(frozen=True, slots=True)
class PaperSpec:
    paper_number: str
    assessment_type: str
    mode: str
    gradable: bool
    has_mcq: bool
    has_written: bool
    viewer_only_reason: str = ""
    ai_profile: str = ""
    supports_drawing_manual_review: bool = True
    duration_minutes: Optional[int] = None
    total_marks: Optional[int] = None
    weight_percent: Optional[float] = None
    calculator_policy: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.mode not in ASSESSMENT_MODES:
            raise ValueError(f"Unsupported mode '{self.mode}'")


@dataclass(frozen=True, slots=True)
class SubjectSpec:
    code: str
    name: str
    papers: Dict[str, PaperSpec]
    year_range: YearRange
    notes: str = ""


def _mk_paper(
    paper_number: str,
    assessment_type: str,
    mode: str,
    gradable: bool,
    has_mcq: bool,
    has_written: bool,
    viewer_only_reason: str = "",
    ai_profile: str = "",
    supports_drawing_manual_review: bool = True,
    duration_minutes: Optional[int] = None,
    total_marks: Optional[int] = None,
    weight_percent: Optional[float] = None,
    calculator_policy: str = "",
    notes: str = "",
) -> PaperSpec:
    return PaperSpec(
        paper_number=str(paper_number),
        assessment_type=assessment_type,
        mode=mode,
        gradable=gradable,
        has_mcq=has_mcq,
        has_written=has_written,
        viewer_only_reason=viewer_only_reason,
        ai_profile=ai_profile,
        supports_drawing_manual_review=supports_drawing_manual_review,
        duration_minutes=duration_minutes,
        total_marks=total_marks,
        weight_percent=weight_percent,
        calculator_policy=calculator_policy,
        notes=notes,
    )


def infer_exam_year(series_code: Optional[str], fallback_year: int = 2026) -> int:
    """Infer full year from year/series strings."""
    raw = str(series_code or "").strip()
    if not raw:
        return int(fallback_year)

    match4 = re.search(r"(20\d{2})", raw)
    if match4:
        return int(match4.group(1))

    match2 = re.search(r"(?<!\d)(\d{2})(?!\d)", raw)
    if match2:
        yy = int(match2.group(1))
        return 2000 + yy

    return int(fallback_year)


def _infer_ai_profile(subject_name: str, category: str) -> str:
    text = f"{subject_name} {category}".lower()
    if "mathematics" in text:
        return "mathematics"
    if "chemistry" in text:
        return "chemistry"
    if "biology" in text:
        return "biology"
    if "physics" in text:
        return "physics"
    if "ict" in text or "information and communication technology" in text:
        return "ict"
    if "english" in text and "literature" in text:
        return "english_literature"
    if "english" in text:
        return "english_writing"
    return ""


def _viewer_reason(row: Dict[str, object]) -> str:
    flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
    if not isinstance(flags, dict):
        flags = {}
    if bool(flags.get("is_speaking_or_oral")):
        return "Speaking/oral component is not auto-gradable from PDF."
    if bool(flags.get("is_coursework")):
        return "Coursework component is internally assessed and viewer-only."
    if bool(flags.get("is_internal_practical")):
        return "Internal practical component requires school-based assessment."
    if str(flags.get("assessment_type", "")).strip().lower() == "practical":
        return "Practical exam component is viewer-only."
    return "This component is not auto-gradable."


def _build_subject_structures() -> Dict[str, List[SubjectSpec]]:
    subject_map = get_subject_map()
    rows_by_subject = get_rows_by_subject()
    out: Dict[str, List[SubjectSpec]] = {}

    for code in sorted(subject_map.keys()):
        rows = rows_by_subject.get(code, [])
        if not rows:
            continue

        papers: Dict[str, PaperSpec] = {}
        subject_name = str(subject_map.get(code, code))
        for row in rows:
            paper_num = normalize_paper_number(row.get("paper_number"), component_label=str(row.get("component_label", "")))
            if not paper_num:
                continue
            flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
            if not isinstance(flags, dict):
                flags = {}

            mode = str(flags.get("routing_mode", "WRITTEN_ONLY")).strip().upper()
            if mode not in ASSESSMENT_MODES:
                mode = "WRITTEN_ONLY"

            assessment_type = str(flags.get("assessment_type", "written")).strip().lower() or "written"
            gradable = mode != "VIEWER_ONLY"
            has_mcq = mode in {"MCQ_ONLY", "MIXED"}
            has_written = mode in {"WRITTEN_ONLY", "MIXED"}
            viewer_only_reason = _viewer_reason(row) if mode == "VIEWER_ONLY" else ""

            notes_parts = [
                str(row.get("component_label", "")).strip(),
                str(row.get("type", "")).strip(),
                str(row.get("notes", "")).strip(),
            ]
            notes = " | ".join(part for part in notes_parts if part)

            paper_spec = _mk_paper(
                paper_number=paper_num,
                assessment_type=assessment_type,
                mode=mode,
                gradable=gradable,
                has_mcq=has_mcq,
                has_written=has_written,
                viewer_only_reason=viewer_only_reason,
                ai_profile=_infer_ai_profile(subject_name, str(row.get("category", ""))),
                supports_drawing_manual_review=True,
                duration_minutes=row.get("duration_minutes") if isinstance(row.get("duration_minutes"), int) else None,
                total_marks=row.get("marks") if isinstance(row.get("marks"), int) else None,
                weight_percent=float(row.get("weight_percent")) if isinstance(row.get("weight_percent"), (int, float)) else None,
                calculator_policy=str(flags.get("calculator_policy", "")).strip(),
                notes=notes,
            )

            papers[paper_num] = paper_spec

        if not papers:
            continue

        out[code] = [
            SubjectSpec(
                code=code,
                name=subject_name,
                papers=papers,
                year_range=YearRange(2020, 2035),
                notes="Built from canonical IGCSE master components registry.",
            )
        ]

    alevel_subjects = get_alevel_subject_map()
    alevel_definitions = get_alevel_definition_map()
    for code, subject_name in alevel_subjects.items():
        resolved = resolve_alevel_subject_code(code)
        raw_papers = alevel_definitions.get(str(code), alevel_definitions.get(str(resolved), {}))
        if not isinstance(raw_papers, dict):
            continue
        papers: Dict[str, PaperSpec] = {}
        for paper_num, meta in raw_papers.items():
            if not isinstance(meta, dict):
                continue
            paper = str(paper_num or "").strip()
            if not paper:
                continue
            mode = str(meta.get("mode", "WRITTEN_ONLY")).strip().upper()
            if mode not in ASSESSMENT_MODES:
                mode = "WRITTEN_ONLY"
            assessment_type = str(meta.get("assessment_type", "written")).strip().lower() or "written"
            gradable = mode != "VIEWER_ONLY"
            has_mcq = mode in {"MCQ_ONLY", "MIXED"}
            has_written = mode in {"WRITTEN_ONLY", "MIXED"}
            papers[paper] = _mk_paper(
                paper_number=paper,
                assessment_type=assessment_type,
                mode=mode,
                gradable=gradable,
                has_mcq=has_mcq,
                has_written=has_written,
                viewer_only_reason=str(meta.get("viewer_only_reason", "")).strip(),
                ai_profile=_infer_ai_profile(str(subject_name), "A Level"),
                supports_drawing_manual_review=True,
                duration_minutes=int(meta.get("duration_minutes")) if isinstance(meta.get("duration_minutes"), int) else None,
                total_marks=int(meta.get("total_marks")) if isinstance(meta.get("total_marks"), int) else None,
                weight_percent=float(meta.get("weight_percent")) if isinstance(meta.get("weight_percent"), (int, float)) else None,
                calculator_policy=str(meta.get("calculator_policy", "")).strip(),
                notes=str(meta.get("notes", "")).strip() or str(meta.get("name", "")).strip(),
            )
        if not papers:
            continue
        note = "Built from curated AS/A Level metadata."
        if str(resolved) != str(code):
            note += f" Legacy alias of {resolved}."
        out[str(code)] = [
            SubjectSpec(
                code=str(code),
                name=str(subject_name),
                papers=papers,
                year_range=YearRange(2020, 2035),
                notes=note,
            )
        ]
    return out


SUBJECT_STRUCTURES: Dict[str, List[SubjectSpec]] = _build_subject_structures()


def get_subject_spec(subject_code: str, exam_year: int = 2026) -> Optional[SubjectSpec]:
    code = str(subject_code or "").strip()
    spec_versions = SUBJECT_STRUCTURES.get(code, [])
    if not spec_versions:
        return None
    for version in spec_versions:
        if version.year_range.includes(exam_year):
            return version
    return spec_versions[-1]


def get_paper_spec(subject_code: str, paper_number: str, exam_year: int = 2026) -> Optional[PaperSpec]:
    spec = get_subject_spec(subject_code, exam_year=exam_year)
    if not spec:
        return None

    raw = str(paper_number or "").strip()
    base = normalize_paper_number(raw)
    return spec.papers.get(base) or spec.papers.get(raw)


def list_supported_subjects() -> Dict[str, str]:
    listing: Dict[str, str] = {}
    for code, versions in SUBJECT_STRUCTURES.items():
        if versions:
            listing[code] = versions[0].name
    return listing


def get_supported_year_ranges(subject_code: str) -> List[YearRange]:
    code = str(subject_code or "").strip()
    return [spec.year_range for spec in SUBJECT_STRUCTURES.get(code, [])]
