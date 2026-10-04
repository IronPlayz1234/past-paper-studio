import pytest

from Core.paper_mode_router import resolve_mode
from Utils.gui_utils import ComponentsDatabase, SubjectDatabase, get_subject_folder
from Utils.sources_manager import PaperNotFoundError, PaperSourceManager


def test_searchable_scope_has_exactly_requested_subjects():
    from Data.subject_catalog import IGCSE_SUBJECTS, ALEVEL_SUBJECTS
    assert SubjectDatabase.get_searchable_subjects("IGCSE") == IGCSE_SUBJECTS
    assert SubjectDatabase.get_searchable_subjects("AS/A Level") == ALEVEL_SUBJECTS
    assert SubjectDatabase.get_searchable_subjects("O Level") == {}
    assert len(SubjectDatabase.get_searchable_subjects()) == 22


def test_exam_level_and_track_resolution():
    assert SubjectDatabase.get_exam_level("0620") == "IGCSE"
    assert SubjectDatabase.get_exam_level("9709") == "A Level"
    assert SubjectDatabase.get_exam_level("7707") == ""
    assert SubjectDatabase.get_bestexamhelp_track("7707") == ""
    assert SubjectDatabase.get_bestexamhelp_track("9709") == "cambridge-international-a-level"
    assert "/cambridge-igcse/" in PaperSourceManager._bestexamhelp_url_for_component("0620", "MJ", "24", "21")
    assert get_subject_folder("0607") == "international-mathematics-0607"


def test_source_order_prefers_bestexamhelp_but_keeps_other_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"bestexamhelp": {"priority": 1}, "s2": {"priority": 2}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0620": ["s2", "bestexamhelp"]},
    )
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    PaperSourceManager._search_cache_loaded = False
    PaperSourceManager._search_cache_dirty = False
    PaperSourceManager._search_cache = {}
    PaperSourceManager._search_cache_l1 = {}
    PaperSourceManager._active_queries = {}

    calls = []

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        calls.append(source_name)
        return []

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    with pytest.raises(PaperNotFoundError):
        PaperSourceManager.search_papers_multi_source(
            subject_code="0620",
            series_list=["MJ"],
            components=["21"],
            years=["24"],
            doc_types=["QP"],
        )

    assert calls
    assert calls[0] == "bestexamhelp"
    assert set(calls) == {"bestexamhelp", "s2"}


def test_er_removed_from_active_doc_type_normalization():
    normalized = PaperSourceManager._normalize_requested_doc_types(["qp", "ER", "MS", "GT"])
    assert normalized == ["QP", "MS", "GT"]


def test_retired_subjects_are_viewer_only_and_not_validated():
    for code in ("7707", "5090", "4024", "0980", "9707"):
        assert ComponentsDatabase.validate_component(code, "11") is False
        assert resolve_mode(code, "1", 2026).mode == "VIEWER_ONLY"
        assert not resolve_mode(code, "1", 2026).gradable


def test_retired_subject_codes_are_not_searchable():
    for code in ("0520", "0549", "0493", "0980", "9707", "4024"):
        assert not SubjectDatabase.is_searchable_subject(code)
        assert SubjectDatabase.find_subject_code(code) is None


def test_find_subject_code_rejects_removed_code():
    assert SubjectDatabase.find_subject_code("0493", "IGCSE") is None
    assert SubjectDatabase.find_subject_code("islamiyat", "IGCSE") is None


def test_dynamic_removed_subject_stays_blocked(monkeypatch):
    monkeypatch.setattr(SubjectDatabase, "DYNAMIC_IGCSE_SUBJECTS", {"8984": "Future Subject"}, raising=False)
    monkeypatch.setattr(SubjectDatabase, "_dynamic_cache_loaded", True, raising=False)

    assert SubjectDatabase.is_searchable_subject("8984") is False
    assert "8984" not in SubjectDatabase.get_searchable_subjects("IGCSE")
