#!/usr/bin/env python3
"""Diagnostics runner for cross-level PDF extraction quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Core.exam_mode import (
    PDF_AVAILABLE,
    QuestionTextExtractor,
    normalize_question_id,
)

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None  # type: ignore[assignment]


def _resolve_path(raw: str, repo_root: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        return Path("")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = (repo_root / candidate).resolve()
    return candidate


def _load_manifest_rows(manifest_path: Path) -> List[Dict[str, Any]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        maybe_rows = data.get("fixtures", [])
        rows = maybe_rows if isinstance(maybe_rows, list) else []
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _metrics(result: Any, token_count: int) -> Dict[str, Any]:
    confidence = dict(getattr(result, "confidence_summary", {}) or {})
    return {
        "token_count": int(token_count),
        "leaf_count": int(len(getattr(result, "question_ids_leaf", []) or [])),
        "marker_acceptance": float(confidence.get("marker_acceptance", 0.0) or 0.0),
        "overall": float(confidence.get("overall", 0.0) or 0.0),
        "score": float(QuestionTextExtractor._result_quality_score(result)),
        "question_ids_leaf": list(getattr(result, "question_ids_leaf", []) or []),
    }


def _run_candidates(extractor: QuestionTextExtractor, pdf_path: Path) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    doc = fitz.open(str(pdf_path))
    try:
        candidates: List[Tuple[str, List[Dict[str, Any]]]] = [
            ("fitz_dict", extractor._collect_line_tokens(doc, max_pages=50)),
            ("fitz_words", extractor._collect_line_tokens_words(doc, max_pages=50)),
            (
                "ocr_paddle_fast",
                extractor._collect_line_tokens_ocr_raster(
                    doc,
                    max_pages=50,
                    scales=(2.0,),
                    include_autocontrast=False,
                ),
            ),
            (
                "ocr_paddle_enhanced",
                extractor._collect_line_tokens_ocr_raster(
                    doc,
                    max_pages=50,
                    scales=(2.0, 2.8),
                    include_autocontrast=True,
                ),
            ),
            ("pdfplumber", extractor._collect_line_tokens_pdfplumber(str(pdf_path), max_pages=50)),
        ]

        best_name = ""
        best_result = None
        report: Dict[str, Any] = {}
        for name, tokens in candidates:
            if not tokens:
                report[name] = {"token_count": 0, "leaf_count": 0, "score": 0.0}
                continue
            parsed = extractor._parse_tokens(tokens)
            report[name] = _metrics(parsed, len(tokens))
            if best_result is None or extractor._prefer_candidate(best_result, parsed):
                best_name = name
                best_result = parsed

        if best_result is None:
            return "", report, {"leaf_count": 0, "question_ids_leaf": [], "score": 0.0}

        return best_name, report, _metrics(best_result, 0)
    finally:
        doc.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose PDF extraction quality across fixtures.")
    parser.add_argument("--manifest", required=True, help="Fixture manifest JSON path.")
    parser.add_argument("--out", required=True, help="Output report JSON path.")
    args = parser.parse_args()

    if not PDF_AVAILABLE or fitz is None:
        raise SystemExit("PyMuPDF is not available in this environment.")

    manifest_path = Path(args.manifest).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    repo_root = Path.cwd()

    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    rows = _load_manifest_rows(manifest_path)
    report_rows: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows):
        pdf_path = _resolve_path(str(row.get("pdf_path", "")), repo_root)
        fixture_name = str(row.get("name") or f"fixture_{idx + 1}")
        expected_subset = [
            normalize_question_id(str(item))
            for item in list(row.get("expected_ids_subset", []) or [])
            if normalize_question_id(str(item))
        ]
        min_leaf = int(row.get("expected_min_leaf_count", 0) or 0)

        entry: Dict[str, Any] = {
            "name": fixture_name,
            "subject_code": str(row.get("subject_code", "") or ""),
            "level": str(row.get("level", "") or ""),
            "paper_code": str(row.get("paper_code", "") or ""),
            "pdf_path": str(pdf_path),
            "expected_min_leaf_count": min_leaf,
            "expected_ids_subset": expected_subset,
        }

        if not str(pdf_path) or not pdf_path.exists():
            entry["status"] = "missing_pdf"
            report_rows.append(entry)
            continue

        extractor = QuestionTextExtractor()
        selected_name, candidates, selected = _run_candidates(extractor, pdf_path)
        selected_ids = list(selected.get("question_ids_leaf", []) or [])
        missing_expected_ids = [qid for qid in expected_subset if qid not in selected_ids]
        entry.update(
            {
                "status": "ok",
                "selected_candidate": selected_name,
                "candidates": candidates,
                "selected": selected,
                "meets_min_leaf_count": int(selected.get("leaf_count", 0) or 0) >= min_leaf,
                "missing_expected_ids": missing_expected_ids,
            }
        )
        report_rows.append(entry)

    summary = {
        "total_fixtures": len(report_rows),
        "ok_count": sum(1 for row in report_rows if row.get("status") == "ok"),
        "missing_pdf_count": sum(1 for row in report_rows if row.get("status") == "missing_pdf"),
    }
    payload = {"manifest": str(manifest_path), "summary": summary, "fixtures": report_rows}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote extraction diagnostics report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
