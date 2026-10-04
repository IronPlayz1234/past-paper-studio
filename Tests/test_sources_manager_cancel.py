import pytest

pytest.importorskip("PySide6")

from Utils.sources_manager import PaperSourceManager


def test_search_multi_source_honors_cancel_callback(monkeypatch):
    calls = {"count": 0}

    def fake_search_from_source(cls, source_name, subject_code, year_text, series, component_text, doc_types):
        calls["count"] += 1
        return []

    monkeypatch.setattr(
        PaperSourceManager,
        "_search_from_source",
        classmethod(fake_search_from_source),
    )

    def cancel_check() -> bool:
        return calls["count"] >= 1

    results = PaperSourceManager.search_papers_multi_source(
        subject_code="0580",
        series_list=["MJ", "ON"],
        components=["11", "21"],
        years=["24", "23"],
        doc_types=["QP"],
        cancel_check=cancel_check,
    )

    assert results == []
    assert calls["count"] == 1
