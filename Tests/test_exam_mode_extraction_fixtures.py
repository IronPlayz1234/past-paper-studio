import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("PySide6")

from Core.exam_mode import QuestionTextExtractor, normalize_question_id


MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "pdf_extraction" / "manifest.json"


def _load_rows() -> List[Dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return []
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("fixtures", [])
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _resolve_pdf_path(raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if not candidate.is_absolute():
        repo_root = Path(__file__).resolve().parents[1]
        candidate = (repo_root / candidate).resolve()
    return candidate


def _valid_rows() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in _load_rows():
        pdf_path = _resolve_pdf_path(str(row.get("pdf_path", "")))
        if not pdf_path.exists():
            continue
        record = dict(row)
        record["resolved_pdf_path"] = str(pdf_path)
        out.append(record)
    return out


FIXTURES = _valid_rows()
if not FIXTURES:
    pytestmark = pytest.mark.skip(reason="No local PDF extraction fixtures found.")


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda row: str(row.get("name", "fixture")))
def test_extraction_fixtures_quality(fixture: Dict[str, Any]) -> None:
    extractor = QuestionTextExtractor()
    result = extractor.extract_with_structure(str(fixture["resolved_pdf_path"]))

    expected_min = int(fixture.get("expected_min_leaf_count", 0) or 0)
    assert len(result.question_ids_leaf) >= expected_min

    expected_subset = [
        normalize_question_id(str(item))
        for item in list(fixture.get("expected_ids_subset", []) or [])
        if normalize_question_id(str(item))
    ]
    actual = {normalize_question_id(qid) for qid in result.question_ids_leaf if normalize_question_id(qid)}
    for qid in expected_subset:
        assert qid in actual

    confidence = dict(getattr(result, "confidence_summary", {}) or {})
    marker_acceptance = float(confidence.get("marker_acceptance", 0.0) or 0.0)
    assert marker_acceptance >= 0.3
