"""Math-focused question and mark-scheme extraction helpers."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

try:
    from Core import pdf_service as fitz  # type: ignore
    PDF_AVAILABLE = True
except Exception:  # pragma: no cover - optional runtime dependency
    PDF_AVAILABLE = False


MATH_SUBJECT_CODES: set[str] = {
    "0580",
    "0607",
    "9709",
    "9231",
}


def is_math_subject_code(subject_code: object, subject_name: object = "") -> bool:
    code = str(subject_code or "").strip()
    if code in MATH_SUBJECT_CODES:
        return True
    return "math" in str(subject_name or "").strip().lower()


def _normalize_math_text(text: object) -> str:
    value = str(text or "")
    value = value.replace("×", "*").replace("÷", "/")
    value = value.replace("−", "-").replace("–", "-").replace("—", "-")
    value = value.replace("√", "sqrt")
    value = value.replace("²", "^2").replace("³", "^3")
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def _extract_pdf_lines(pdf_path: str, max_pages: int) -> List[str]:
    if not PDF_AVAILABLE:
        return []
    if not pdf_path or not os.path.exists(pdf_path):
        return []
    lines: List[str] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []
    try:
        for page_index in range(min(len(doc), max(1, int(max_pages)))):
            try:
                text = doc[page_index].get_text("text")
            except Exception:
                text = ""
            for raw_line in str(text or "").splitlines():
                line = _normalize_math_text(raw_line)
                if line:
                    lines.append(line)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return lines


def _collect_question_blocks(lines: List[str]) -> Dict[str, List[str]]:
    blocks: Dict[str, List[str]] = {}
    current_qid: Optional[str] = None
    qid_re = re.compile(r"^\s*(?:Q\s*)?(\d{1,2})(?=\s|[\.\):]|$)", re.IGNORECASE)
    for line in lines:
        match = qid_re.match(line)
        if match:
            current_qid = str(int(match.group(1)))
            blocks.setdefault(current_qid, []).append(line)
            continue
        if current_qid is None:
            continue
        blocks.setdefault(current_qid, []).append(line)
    return blocks


def _estimate_mark_total(block_text: str) -> float:
    text = str(block_text or "")
    mark_sum = 0.0
    for raw_value in re.findall(r"\b(?:M|A|B|SC|FT)\s*(\d(?:\.\d+)?)\b", text, flags=re.IGNORECASE):
        try:
            mark_sum += float(raw_value)
        except Exception:
            continue
    bracket_max = 0.0
    for raw_value in re.findall(r"\[(\d{1,2}(?:\.\d+)?)\]", text):
        try:
            bracket_max = max(bracket_max, float(raw_value))
        except Exception:
            continue
    if mark_sum > 0:
        return float(mark_sum)
    if bracket_max > 0:
        return float(bracket_max)
    return 1.0


def extract_math_questions(pdf_path: str, max_pages: int = 60) -> Dict[str, str]:
    lines = _extract_pdf_lines(pdf_path, max_pages=max_pages)
    if not lines:
        return {}
    blocks = _collect_question_blocks(lines)
    out: Dict[str, str] = {}
    for qid, block_lines in blocks.items():
        text = "\n".join(block_lines).strip()
        if text:
            out[qid] = text
    return out


def extract_math_mark_scheme(
    pdf_path: str,
    expected_question_ids: Optional[List[str]] = None,
    max_pages: int = 80,
) -> Dict[str, Dict[str, Any]]:
    lines = _extract_pdf_lines(pdf_path, max_pages=max_pages)
    if not lines:
        return {}
    blocks = _collect_question_blocks(lines)
    if not blocks:
        return {}

    expected_set: set[str] = set()
    expected_main: set[str] = set()
    for raw in expected_question_ids or []:
        token = str(raw or "").strip().lower()
        if not token:
            continue
        expected_set.add(token)
        match = re.match(r"^(\d{1,2})", token)
        if match:
            expected_main.add(str(int(match.group(1))))

    out: Dict[str, Dict[str, Any]] = {}
    for qid, block_lines in blocks.items():
        if expected_main and qid not in expected_main:
            continue
        block_text = "\n".join(block_lines).strip()
        if not block_text:
            continue
        marks = _estimate_mark_total(block_text)
        rule_tokens: List[Dict[str, Any]] = []
        try:
            from Grading.cambridge_rule_engine import parse_math_mark_scheme

            rule_spec = parse_math_mark_scheme(block_text)
            for token in list(getattr(rule_spec, "tokens", []) or []):
                rule_tokens.append(
                    {
                        "kind": str(getattr(token, "kind", "") or ""),
                        "marks": float(getattr(token, "marks", 0.0) or 0.0),
                        "dep": bool(getattr(token, "dep", False)),
                        "ft": bool(getattr(token, "ft", False)),
                        "sc": bool(getattr(token, "sc", False)),
                        "qualifiers": list(getattr(token, "qualifiers", []) or []),
                        "raw": str(getattr(token, "raw", "") or ""),
                    }
                )
        except Exception:
            rule_tokens = []
        out[qid] = {
            "answer": block_text,
            "mark_scheme_text": block_text,
            "marks": float(max(0.0, marks)),
            "is_generated": False,
            "is_math_extracted": True,
            "rule_tokens": rule_tokens,
        }
    return out
