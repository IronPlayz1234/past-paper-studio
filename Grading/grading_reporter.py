"""Grading report writer for per-run Markdown exports."""

from __future__ import annotations

from datetime import datetime
from Core.atomic_storage import atomic_write_text
from Core.download_service import safe_filename
import os
import re
from pathlib import Path
from typing import Any, Dict

from Utils.question_id_mapper import format_question_display, parse_question_id


def _safe_name_component(text: str, fallback: str = "unknown") -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return fallback
    value = value.replace("/", "-").replace("\\", "-")
    value = value.replace("\x00", "")
    value = re.sub(r"[<>\"|?*]", "", value)
    value = value.strip(" .")
    return value or fallback


def _format_threshold_mark(value: Any) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except Exception:
        return "-"
    if not (numeric == numeric):
        return "-"
    return f"{int(round(numeric))}"


def _question_sort_key(raw_qid: Any) -> tuple[int, str, str]:
    text = str(raw_qid or "").strip()
    parsed = parse_question_id(text)
    if parsed.valid and parsed.main is not None:
        return (int(parsed.main), parsed.part or "", parsed.subpart or "")
    return (10_000, text, text)


def write_grading_report(
    *,
    project_root: str,
    subject_code: str,
    paper_number: str,
    year: str,
    results: Dict[str, Any],
    source_label: str,
    subject_name: str = "",
    past_paper_code: str = "",
) -> str:
    now = datetime.now()
    stamp_display = now.strftime("%Y-%m-%d %H-%M-%S-%f")
    subject_label = _safe_name_component(subject_name or subject_code, fallback=str(subject_code or "Unknown Subject"))
    default_paper_code = f"{subject_code}_p{paper_number}_{year}".strip("_")
    paper_code_label = _safe_name_component(past_paper_code or default_paper_code, fallback=default_paper_code or "paper")
    filename = f"{subject_label} {paper_code_label} Done {stamp_display}.md"
    filename = _safe_name_component(filename, fallback=f"grading_report_{now.strftime('%Y%m%d_%H%M%S')}.md")
    if not filename.lower().endswith(".md"):
        filename = f"{filename}.md"
    path = Path(str(project_root)).resolve() / safe_filename(filename)

    total_marks = float(results.get("total_marks", 0.0) or 0.0)
    earned_marks = float(results.get("earned_marks", 0.0) or 0.0)
    percentage = float(results.get("percentage", 0.0) or 0.0)
    auto_marks = float(results.get("auto_graded_marks", earned_marks) or 0.0)
    auto_total = float(results.get("auto_graded_total_marks", total_marks) or 0.0)
    pending_manual = float(results.get("pending_manual_marks", 0.0) or 0.0)
    pending_count = int(results.get("pending_manual_count", 0) or 0)

    lines: list[str] = []
    lines.append("# Auto-Grade Report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- Subject Name: {subject_name or subject_code}")
    lines.append(f"- Subject Code: {subject_code}")
    lines.append(f"- Paper Number: {paper_number}")
    lines.append(f"- Year: {year}")
    lines.append(f"- Past Paper Code: {past_paper_code or default_paper_code}")
    lines.append(f"- Source Label: {source_label}")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Earned Marks: {earned_marks:g}")
    lines.append(f"- Total Marks: {total_marks:g}")
    lines.append(f"- Percentage: {percentage:.1f}%")
    lines.append(f"- Auto-Graded: {auto_marks:g} / {auto_total:g}")
    lines.append(f"- Pending Manual: {pending_manual:g} across {pending_count} question(s)")
    lines.append("")

    threshold_interpretation = results.get("threshold_interpretation")
    if isinstance(threshold_interpretation, dict):
        lines.append("## Grade Thresholds")
        lines.append("")
        try:
            candidate_score = float(
                threshold_interpretation.get(
                    "candidate_score",
                    results.get("final_confirmed_marks", earned_marks),
                )
                or 0.0
            )
        except Exception:
            candidate_score = 0.0
        display_total = threshold_interpretation.get("max_raw_mark")
        if display_total is None:
            display_total = threshold_interpretation.get("total_mark", total_marks)
        try:
            display_total_value = float(display_total or 0.0)
        except Exception:
            display_total_value = 0.0

        lines.append(f"- Candidate Score: {candidate_score:g} / {display_total_value:g}")

        available = bool(threshold_interpretation.get("available", False))
        if not available:
            message = str(threshold_interpretation.get("message", "") or "").strip()
            if not message:
                message = "Grade threshold data unavailable for this paper/session"
            lines.append(f"- {message}")
        else:
            rows = threshold_interpretation.get("threshold_rows", [])
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    grade = str(row.get("grade", "") or "").strip()
                    if not grade:
                        continue
                    lines.append(f"- {grade}: {_format_threshold_mark(row.get('mark'))}")

            provisional = bool(threshold_interpretation.get("provisional", False))
            estimated_grade = str(threshold_interpretation.get("estimated_grade", "") or "").strip()
            if estimated_grade:
                estimated_label = "Estimated Grade (Provisional)" if provisional else "Estimated Grade"
                lines.append(f"- {estimated_label}: {estimated_grade}")

            next_grade_label = str(threshold_interpretation.get("next_grade_label", "") or "").strip()
            marks_to_next = threshold_interpretation.get("marks_to_next")
            if next_grade_label and marks_to_next is not None:
                try:
                    marks_value = max(0, int(marks_to_next))
                except Exception:
                    marks_value = 0
                lines.append(f"- Marks to {next_grade_label}: {marks_value}")
        lines.append("")

    errors = list(results.get("grading_errors", []) or [])
    if errors:
        lines.append("## Warnings")
        lines.append("")
        for error in errors:
            lines.append(f"- {str(error)}")
        lines.append("")

    lines.append("## Per-Question Results")
    lines.append("")

    question_results = dict(results.get("question_results", {}) or {})
    sorted_ids = sorted(question_results.keys(), key=_question_sort_key)
    for qid in sorted_ids:
        row = dict(question_results.get(qid, {}) or {})
        display_qid = str(row.get("question_id", qid) or qid)
        lines.append(f"### Q{format_question_display(display_qid)}")
        lines.append("")
        lines.append(f"- Grading Source: {row.get('grading_source', '')}")
        awarded_marks = float(row.get("awarded_marks", row.get("earned_marks", 0.0)) or 0.0)
        max_marks = float(row.get("max_marks", row.get("total_marks", 0.0)) or 0.0)
        lines.append(f"- Marks: {awarded_marks:g} / {max_marks:g}")
        lines.append(f"- Manual Review Required: {bool(row.get('manual_review_required', False))}")
        lines.append(f"- Manual Review Status: {row.get('manual_review_status', '')}")
        lines.append(f"- Parse Status: {row.get('parse_status', '')}")
        lines.append(f"- Model: {row.get('model_used', '')}")
        lines.append(f"- AI Error: {row.get('ai_error', '')}")
        if row.get("max_marks_source"):
            lines.append(f"- Max Marks Source: {row.get('max_marks_source', '')}")
        if row.get("mark_scheme_source"):
            lines.append(f"- Mark Scheme Source: {row.get('mark_scheme_source', '')}")
        if row.get("mapping_strategy"):
            lines.append(f"- Mapping Strategy: {row.get('mapping_strategy', '')}")
        if row.get("fallback_used") is not None:
            lines.append(f"- Fallback Used: {bool(row.get('fallback_used', False))}")
        if row.get("manual_review_reason"):
            lines.append(f"- Manual Review Reason: {row.get('manual_review_reason', '')}")
        warnings = row.get("warnings", [])
        if isinstance(warnings, list) and warnings:
            lines.append(f"- Warnings: {', '.join(str(w) for w in warnings)}")
        question_text = str(row.get("question_text", "") or "").strip()
        if question_text:
            lines.append(f"- Question Text: {question_text}")

        lines.append("")
        lines.append("#### Student Answer")
        lines.append("")
        lines.append("```")
        lines.append(str(row.get("student_answer", "") or ""))
        lines.append("```")
        lines.append("")

        lines.append("#### Mark Scheme Text")
        lines.append("")
        lines.append("```")
        lines.append(str(row.get("mark_scheme_text", "") or ""))
        lines.append("```")
        lines.append("")

        lines.append("#### Explanation")
        lines.append("")
        lines.append(str(row.get("explanation", row.get("feedback", "")) or ""))
        lines.append("")

        lines.append("#### Raw AI Response")
        lines.append("")
        lines.append("```")
        lines.append(str(row.get("raw_response", "") or ""))
        lines.append("```")
        lines.append("")

    atomic_write_text(path, "\n".join(lines).rstrip() + "\n")
    return str(path)


__all__ = ["write_grading_report"]
