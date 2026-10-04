"""Unified question extraction across MCQ, written, and mixed paper modes."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from Core import pdf_service as fitz  # type: ignore
    PDF_AVAILABLE = True
except Exception:
    PDF_AVAILABLE = False

from Utils.question_id_mapper import QuestionLeaf, parse_question_id, format_question_display, normalize_question_id_canonical


MIXED_OBJECTIVE_HINTS = [
    "multiple choice",
    "choose the correct",
    "tick",
    "select one",
    "choisissez",
    "cocher",
    "entoure",
]


def detect_section_type(question_text: str, mode: str = "WRITTEN_ONLY") -> str:
    """Detect whether a question row is objective or written."""
    if mode == "MCQ_ONLY":
        return "objective"

    text = (question_text or "").strip()
    if not text:
        return "written"

    low = text.lower()
    if any(h in low for h in MIXED_OBJECTIVE_HINTS):
        return "objective"

    # Option-marker density: e.g. (A) ... (B) ...
    option_markers = len(re.findall(r"\(([A-D])\)", text))
    option_markers += len(re.findall(r"\b[A-D]\.", text))
    if option_markers >= 2:
        return "objective"

    return "written"


@dataclass(slots=True)
class UnifiedExtractionResult:
    question_items: List[QuestionLeaf]
    question_ids: List[str]
    question_texts: Dict[str, str]
    question_marks: Dict[str, float]
    question_mark_hints: Dict[str, float]
    question_pages: Dict[str, int]
    debug_events: List[str]
    confidence_summary: Dict[str, float]


class UnifiedQuestionExtractor:
    """Mode-aware extractor that reuses existing per-mode extractors when available."""

    def __init__(self, written_extractor: Any = None):
        self.written_extractor = written_extractor

    def extract_questions(
        self,
        pdf_path: Optional[str],
        subject_code: str,
        paper_number: str,
        exam_year: int,
        mode: str,
        default_marks: float = 1.0,
        expected_mcq_count: int = 40,
    ) -> UnifiedExtractionResult:
        if mode == "MCQ_ONLY":
            return self._extract_mcq_questions(
                pdf_path=pdf_path,
                expected_count=expected_mcq_count,
                default_marks=default_marks,
            )

        if not self.written_extractor:
            return UnifiedExtractionResult(
                question_items=[],
                question_ids=[],
                question_texts={},
                question_marks={},
                question_mark_hints={},
                question_pages={},
                debug_events=["No written extractor available."],
                confidence_summary={},
            )

        result = self.written_extractor.extract_with_structure(pdf_path)
        if not result:
            return UnifiedExtractionResult(
                question_items=[],
                question_ids=[],
                question_texts={},
                question_marks={},
                question_mark_hints={},
                question_pages={},
                debug_events=["No extraction result from written extractor."],
                confidence_summary={},
            )

        items: List[QuestionLeaf] = []
        q_marks: Dict[str, float] = {}
        q_mark_hints = {
            normalize_question_id_canonical(k): float(v)
            for k, v in (getattr(result, "question_mark_hints", {}) or {}).items()
            if normalize_question_id_canonical(k)
        }
        for item in result.question_items:
            qid = normalize_question_id_canonical(item.canonical_id)
            if not qid:
                continue
            section_type = detect_section_type(item.text, mode=mode)
            item.section_type = section_type
            # In mixed mode, objective rows should not default to drawing even if they contain the word "graph"
            if section_type == "objective":
                item.response_type = "text"
                item.requires_manual_review = False
                item.manual_review_reason = ""
            items.append(item)
            hinted = q_mark_hints.get(qid)
            q_marks[qid] = float(hinted) if isinstance(hinted, (int, float)) and hinted > 0 else float(default_marks)

        q_ids = [normalize_question_id_canonical(i.canonical_id) for i in items if normalize_question_id_canonical(i.canonical_id)]
        q_texts = {normalize_question_id_canonical(k): v for k, v in result.question_texts.items() if normalize_question_id_canonical(k)}
        q_pages = {normalize_question_id_canonical(k): int(v) for k, v in result.question_pages.items() if normalize_question_id_canonical(k)}

        for qid in q_ids:
            hinted = q_mark_hints.get(qid)
            if qid not in q_marks:
                q_marks[qid] = float(hinted) if isinstance(hinted, (int, float)) and hinted > 0 else float(default_marks)
            q_texts.setdefault(qid, f"Question {format_question_display(qid)}")
            q_pages.setdefault(qid, 1)

        return UnifiedExtractionResult(
            question_items=items,
            question_ids=q_ids,
            question_texts=q_texts,
            question_marks=q_marks,
            question_mark_hints=q_mark_hints,
            question_pages=q_pages,
            debug_events=list(getattr(result, "debug_events", []) or []),
            confidence_summary=dict(getattr(result, "confidence_summary", {}) or {}),
        )

    def _extract_mcq_questions(
        self,
        pdf_path: Optional[str],
        expected_count: int,
        default_marks: float,
    ) -> UnifiedExtractionResult:
        ids = [str(i) for i in range(1, max(1, expected_count) + 1)]
        texts = {qid: f"Question {qid}" for qid in ids}
        pages = {}
        debug_events: List[str] = []

        if pdf_path and PDF_AVAILABLE:
            try:
                doc = fitz.open(pdf_path)
                found: List[str] = []
                for page_index in range(min(len(doc), 30)):
                    text = doc[page_index].get_text("text")
                    for line in text.splitlines():
                        m = re.match(r"^\s*(\d{1,2})\s+[A-Da-d]", line)
                        if m:
                            qid = str(int(m.group(1)))
                            if qid not in found:
                                found.append(qid)
                                pages[qid] = page_index + 1
                    if len(found) >= expected_count:
                        break
                doc.close()
                if found:
                    ids = sorted(found, key=lambda x: int(x))
                    texts = {qid: f"Question {qid}" for qid in ids}
                    debug_events.append(f"Detected {len(found)} MCQ questions from PDF.")
            except Exception as exc:
                debug_events.append(f"MCQ PDF scan failed: {exc}")

        items: List[QuestionLeaf] = []
        for qid in ids:
            parsed = parse_question_id(qid)
            items.append(
                QuestionLeaf(
                    canonical_id=qid,
                    display_id=format_question_display(qid),
                    main=parsed.main,
                    part=parsed.part,
                    subpart=parsed.subpart,
                    page=pages.get(qid),
                    text=texts.get(qid, f"Question {qid}"),
                    parent_id=None,
                    level=0,
                    response_type="text",
                    requires_manual_review=False,
                    manual_review_reason="",
                    section_type="objective",
                )
            )

        marks = {qid: float(default_marks) for qid in ids}
        return UnifiedExtractionResult(
            question_items=items,
            question_ids=ids,
            question_texts=texts,
            question_marks=marks,
            question_mark_hints=dict(marks),
            question_pages=pages,
            debug_events=debug_events,
            confidence_summary={"overall": 1.0, "marker_acceptance": 1.0, "detected_leaf_count": float(len(ids))},
        )
