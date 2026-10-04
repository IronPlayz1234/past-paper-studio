import pytest
import time
from concurrent.futures import ThreadPoolExecutor

pytest.importorskip("PySide6")

from Utils.gui_utils import SubjectDatabase
from Utils.sources_manager import PaperNotFoundError, PaperSourceManager


def _reset_search_runtime_state() -> None:
    PaperSourceManager._search_cache_loaded = False
    PaperSourceManager._search_cache_dirty = False
    PaperSourceManager._search_cache = {}
    PaperSourceManager._search_cache_l1 = {}
    with PaperSourceManager._active_queries_lock:
        PaperSourceManager._active_queries = {}


def test_search_aggregates_doc_types_across_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"s1": {"priority": 1}, "s2": {"priority": 2}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0620": ["s1", "s2"]},
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_search_runtime_config",
        classmethod(
            lambda cls: {
                "fast_first_target_ms": 2500,
                "max_total_ms": 10000,
                "enable_background_enrichment": True,
                "stop_on_first_source_hit": False,
            }
        ),
    )
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    _reset_search_runtime_state()

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        if source_name == "s1":
            return [
                cls._format_result(
                    subject_code=subject_code,
                    year=year,
                    series=series,
                    component=component,
                    doc_type="GT",
                    filename=f"{subject_code}_s{year}_gt",
                    url=f"https://example.com/{subject_code}_s{year}_gt.pdf",
                    source=source_name,
                )
            ]
        return [
            cls._format_result(
                subject_code=subject_code,
                year=year,
                series=series,
                component=component,
                doc_type="QP",
                filename=f"{subject_code}_s{year}_qp_{component}",
                url=f"https://example.com/{subject_code}_s{year}_qp_{component}.pdf",
                source=source_name,
            ),
            cls._format_result(
                subject_code=subject_code,
                year=year,
                series=series,
                component=component,
                doc_type="MS",
                filename=f"{subject_code}_s{year}_ms_{component}",
                url=f"https://example.com/{subject_code}_s{year}_ms_{component}.pdf",
                source=source_name,
            ),
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0620",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP", "MS", "GT"],
    )

    assert len(groups) == 1
    group = groups[0]
    assert "QP" in group.primary_docs
    assert "MS" in group.primary_docs
    assert "GT" in group.primary_docs


def test_search_uses_cache_for_repeat_queries(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"s1": {"priority": 1}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0620": ["s1"]},
    )
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    _reset_search_runtime_state()

    calls = {"count": 0}

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        calls["count"] += 1
        return [
            cls._format_result(
                subject_code=subject_code,
                year=year,
                series=series,
                component=component,
                doc_type="QP",
                filename=f"{subject_code}_s{year}_qp_{component}",
                url=f"https://example.com/{subject_code}_s{year}_qp_{component}.pdf",
                source=source_name,
            )
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    first = PaperSourceManager.search_papers_multi_source(
        subject_code="0620",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP"],
    )
    second = PaperSourceManager.search_papers_multi_source(
        subject_code="0620",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP"],
    )

    assert len(first) == 1
    assert len(second) == 1
    assert calls["count"] == 1


def test_bestexamhelp_single_digit_component_probes_variants(monkeypatch):
    def fake_exists(cls, url: str):
        lower = str(url).lower()
        return lower.endswith("_qp_21.pdf") or lower.endswith("_ms_21.pdf")

    monkeypatch.setattr(PaperSourceManager, "_url_exists", classmethod(fake_exists))

    rows = PaperSourceManager._search_bestexamhelp(
        subject_code="0580",
        year="24",
        series="MJ",
        component="2",
        doc_types=["QP", "MS", "GT"],
    )

    by_type = {str(row.get("type")): row for row in rows}
    assert "QP" in by_type
    assert "MS" in by_type
    assert by_type["QP"]["component"] == "21"
    assert by_type["MS"]["component"] == "21"


def test_component_probe_order_prefers_0x_for_unknown_style():
    PaperSourceManager._component_style_cache = {}
    order = PaperSourceManager._component_probe_order("0580", "21")
    assert order
    assert order[0] == "02"


def test_component_probe_order_uses_learned_variant_style():
    PaperSourceManager._component_style_cache = {}
    PaperSourceManager._learn_component_style("0620", "21")

    order = PaperSourceManager._component_probe_order("0620", "2")
    assert order
    assert order[0] == "21"


def test_component_style_cache_learns_zero_padded_from_success(monkeypatch):
    PaperSourceManager._component_style_cache = {}

    def fake_exists(cls, url: str):
        return str(url).lower().endswith("_qp_02.pdf")

    monkeypatch.setattr(PaperSourceManager, "_url_exists", classmethod(fake_exists))
    rows = PaperSourceManager._search_bestexamhelp(
        subject_code="0580",
        year="24",
        series="MJ",
        component="2",
        doc_types=["QP"],
    )
    assert rows
    assert rows[0]["component"] == "02"
    assert PaperSourceManager._component_style_for_paper("0580", "2") == "zero_padded"


def test_runtime_source_order_includes_papa_fallback_for_0417(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {
            "bestexamhelp": {"priority": 1},
            "pastpapersco": {"priority": 2},
            "papacambridge": {"priority": 3},
            "other": {"priority": 4},
        },
    )
    order = PaperSourceManager._runtime_source_order("0417", ["other", "bestexamhelp"])
    assert order == ["pastpapersco", "papacambridge", "bestexamhelp"]


def test_runtime_source_order_prefers_french_foreign_style_for_0620(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {
            "bestexamhelp": {"priority": 1},
            "pastpapersco": {"priority": 2},
            "other": {"priority": 3},
        },
    )
    order = PaperSourceManager._runtime_source_order("0620", ["other", "bestexamhelp", "pastpapersco"])
    assert order[0] == "pastpapersco"
    assert "bestexamhelp" in order


def test_runtime_source_order_for_non_beh_subject_moves_bestexamhelp_back(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {
            "bestexamhelp": {"priority": 1},
            "pastpapersco": {"priority": 2},
            "papacambridge": {"priority": 3},
            "gceguide": {"priority": 4},
        },
    )
    order = PaperSourceManager._runtime_source_order("0539", ["bestexamhelp", "pastpapersco", "gceguide"])
    assert order[0] == "pastpapersco"
    assert order[1] == "papacambridge"
    assert order[-1] == "bestexamhelp"


def test_runtime_source_order_adds_fallbacks_when_bestexamhelp_only(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {
            "bestexamhelp": {"priority": 1},
            "pastpapersco": {"priority": 2},
            "gceguide": {"priority": 3},
            "dynamicpapers": {"priority": 4},
            "papacambridge": {"priority": 5},
        },
    )
    order = PaperSourceManager._runtime_source_order("0607", ["bestexamhelp"])
    assert order[0] == "pastpapersco"
    assert order[1] == "papacambridge"
    assert "bestexamhelp" in order
    assert "pastpapersco" in order
    assert "gceguide" in order
    assert "dynamicpapers" in order


def test_search_skips_secondary_sources_when_primary_satisfies_doc_types(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"s1": {"priority": 1}, "s2": {"priority": 2}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0620": ["s1", "s2"]},
    )
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    _reset_search_runtime_state()

    calls = {"s1": 0, "s2": 0}

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        calls[source_name] += 1
        if source_name == "s1":
            return [
                cls._format_result(
                    subject_code=subject_code,
                    year=year,
                    series=series,
                    component=component,
                    doc_type="QP",
                    filename=f"{subject_code}_{series}{year}_qp_{component}",
                    url=f"https://example.com/{subject_code}_{series}{year}_qp_{component}.pdf",
                    source=source_name,
                ),
                cls._format_result(
                    subject_code=subject_code,
                    year=year,
                    series=series,
                    component=component,
                    doc_type="MS",
                    filename=f"{subject_code}_{series}{year}_ms_{component}",
                    url=f"https://example.com/{subject_code}_{series}{year}_ms_{component}.pdf",
                    source=source_name,
                ),
            ]
        return []

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0620",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP", "MS"],
    )

    assert len(groups) == 1
    assert calls["s1"] == 1
    assert calls["s2"] == 0


def test_search_stops_on_first_source_hit_even_if_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"s1": {"priority": 1}, "s2": {"priority": 2}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0620": ["s1", "s2"]},
    )
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))
    monkeypatch.setattr(
        PaperSourceManager,
        "_search_runtime_config",
        classmethod(
            lambda cls: {
                "fast_first_target_ms": 2500,
                "max_total_ms": 10000,
                "enable_background_enrichment": True,
                "stop_on_first_source_hit": True,
            }
        ),
    )

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    _reset_search_runtime_state()

    calls = {"s1": 0, "s2": 0}

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        calls[source_name] += 1
        if source_name == "s1":
            return [
                cls._format_result(
                    subject_code=subject_code,
                    year=year,
                    series=series,
                    component=component,
                    doc_type="QP",
                    filename=f"{subject_code}_{series}{year}_qp_{component}",
                    url=f"https://example.com/{subject_code}_{series}{year}_qp_{component}.pdf",
                    source=source_name,
                )
            ]
        return [
            cls._format_result(
                subject_code=subject_code,
                year=year,
                series=series,
                component=component,
                doc_type="MS",
                filename=f"{subject_code}_{series}{year}_ms_{component}",
                url=f"https://example.com/{subject_code}_{series}{year}_ms_{component}.pdf",
                source=source_name,
            )
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0620",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP", "MS"],
    )

    assert len(groups) == 1
    assert "QP" in groups[0].primary_docs
    assert calls["s1"] == 1
    assert calls["s2"] == 0


def test_search_short_circuits_removed_subject_without_source_calls(monkeypatch):
    calls = {"count": 0}

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        calls["count"] += 1
        return []

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0637",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP"],
    )

    assert groups == []
    assert calls["count"] == 0


def test_gceguide_search_uses_cached_catalog(monkeypatch):
    catalog_calls = {"count": 0}

    def fake_catalog(cls, source_name, subject_code):
        catalog_calls["count"] += 1
        return {
            cls._normalize_file_key("0620_s24_qp_42.pdf"): "https://example.com/0620_s24_qp_42.pdf",
            cls._normalize_file_key("0620_s24_ms_42.pdf"): "https://example.com/0620_s24_ms_42.pdf",
        }

    monkeypatch.setattr(PaperSourceManager, "_collect_source_pdf_catalog", classmethod(fake_catalog))
    monkeypatch.setattr(PaperSourceManager, "_url_exists", classmethod(lambda cls, _url: True))

    rows = PaperSourceManager._search_gceguide("0620", "24", "MJ", "42", ["QP", "MS"])
    assert len(rows) == 2
    assert catalog_calls["count"] == 1


def test_fm_variant_detection_uses_cache(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"bestexamhelp": {"priority": 1}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0580": ["bestexamhelp"]},
    )
    PaperSourceManager._fm_variant_cache = {}

    calls = {"count": 0}

    def fake_search_from_source_with_retry(
        cls,
        source_name,
        subject_code,
        year,
        series,
        component,
        doc_types,
        cancel_check=None,
    ):
        calls["count"] += 1
        if str(component).endswith("2"):
            return [
                cls._format_result(
                    subject_code=subject_code,
                    year=year,
                    series=series,
                    component=component,
                    doc_type="QP",
                    filename=f"{subject_code}_{series}{year}_qp_{component}",
                    url=f"https://example.com/{subject_code}_{series}{year}_qp_{component}.pdf",
                    source=source_name,
                )
            ]
        return []

    monkeypatch.setattr(PaperSourceManager, "_search_from_source_with_retry", classmethod(fake_search_from_source_with_retry))

    first = PaperSourceManager.detect_fm_locked_variant(
        subject_code="0580",
        paper_numbers=["2", "4"],
        years=["24"],
        doc_types=["QP"],
    )
    first_call_count = calls["count"]
    second = PaperSourceManager.detect_fm_locked_variant(
        subject_code="0580",
        paper_numbers=["2", "4"],
        years=["24"],
        doc_types=["QP"],
    )

    assert first == "2"
    assert second == "2"
    assert first_call_count > 0
    assert calls["count"] == first_call_count


def test_negative_probe_cache_entry_expires(monkeypatch):
    url = "https://example.com/missing.pdf"
    monkeypatch.setattr(PaperSourceManager, "URL_PROBE_NEGATIVE_TTL_SECONDS", 1)
    PaperSourceManager._url_pdf_probe_cache[url] = {
        "exists": False,
        "checked_at": time.time() - 10.0,
        "source_status": "test",
    }
    assert PaperSourceManager._url_probe_cache_get(url) is None
    assert url not in PaperSourceManager._url_pdf_probe_cache


def test_query_cache_status_ttl_split(monkeypatch):
    now = time.time()
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_SUCCESS_TTL_SECONDS", 3600)
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_EMPTY_TTL_SECONDS", 60)
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_ERROR_TTL_SECONDS", 30)
    PaperSourceManager._search_cache_loaded = True
    PaperSourceManager._search_cache_dirty = False
    PaperSourceManager._search_cache = {
        "success": {"timestamp": now - 300, "status": "success", "groups": []},
        "empty": {"timestamp": now - 120, "status": "empty", "groups": []},
        "error": {"timestamp": now - 90, "status": "error", "groups": []},
    }

    PaperSourceManager._prune_expired_search_cache()

    assert "success" in PaperSourceManager._search_cache
    assert "empty" not in PaperSourceManager._search_cache
    assert "error" not in PaperSourceManager._search_cache


def test_math_fallback_uses_manager_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"bestexamhelp": {"priority": 1}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0580": ["bestexamhelp"], "0607": ["bestexamhelp"]},
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_search_runtime_config",
        classmethod(
            lambda cls: {
                "fast_first_target_ms": 500,
                "max_total_ms": 1500,
                "enable_background_enrichment": False,
            }
        ),
    )

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    PaperSourceManager._search_cache_loaded = False
    PaperSourceManager._search_cache_dirty = False
    PaperSourceManager._search_cache = {}
    PaperSourceManager._search_cache_l1 = {}
    PaperSourceManager._active_queries = {}

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        if str(subject_code) == "0607":
            return [
                cls._format_result(
                    subject_code="0607",
                    year=year,
                    series=series,
                    component=component,
                    doc_type="QP",
                    filename=f"0607_{series}{year}_qp_{component}",
                    url=f"https://example.com/0607_{series}{year}_qp_{component}.pdf",
                    source=source_name,
                )
            ]
        return []

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0580",
        series_list=["MJ"],
        components=["21"],
        years=["24"],
        doc_types=["QP"],
    )

    assert len(groups) == 1
    assert groups[0].subject_code == "0607"


def test_inflight_query_dedupes_network_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))
    monkeypatch.setattr(
        PaperSourceManager,
        "SOURCES",
        {"bestexamhelp": {"priority": 1}},
    )
    monkeypatch.setattr(
        SubjectDatabase,
        "SUBJECT_SOURCE_MAP",
        {"0620": ["bestexamhelp"]},
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_search_runtime_config",
        classmethod(
            lambda cls: {
                "fast_first_target_ms": 800,
                "max_total_ms": 3000,
                "enable_background_enrichment": False,
            }
        ),
    )

    cache_file = tmp_path / "paper_search_cache.json"
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(cache_file))
    PaperSourceManager._search_cache_loaded = False
    PaperSourceManager._search_cache_dirty = False
    PaperSourceManager._search_cache = {}
    PaperSourceManager._search_cache_l1 = {}
    PaperSourceManager._active_queries = {}

    calls = {"count": 0}

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        calls["count"] += 1
        time.sleep(0.2)
        return [
            cls._format_result(
                subject_code=subject_code,
                year=year,
                series=series,
                component=component,
                doc_type="QP",
                filename=f"{subject_code}_{series}{year}_qp_{component}",
                url=f"https://example.com/{subject_code}_{series}{year}_qp_{component}.pdf",
                source=source_name,
            )
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    def run_search():
        return PaperSourceManager.search_papers_multi_source(
            subject_code="0620",
            series_list=["MJ"],
            components=["21"],
            years=["24"],
            doc_types=["QP"],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_search)
        second = executor.submit(run_search)
        result_a = first.result()
        result_b = second.result()

    assert len(result_a) == 1
    assert len(result_b) == 1
    assert calls["count"] == 1


def test_paper_not_found_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(PaperSourceManager, "SOURCES", {"s1": {"priority": 1}})
    monkeypatch.setattr(SubjectDatabase, "SUBJECT_SOURCE_MAP", {"0620": ["s1"]})
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))
    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(lambda cls, *a, **k: []))
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(tmp_path / "cache.json"))
    _reset_search_runtime_state()

    with pytest.raises(PaperNotFoundError, match="Paper not found on any configured source"):
        PaperSourceManager.search_papers_multi_source(
            subject_code="0620",
            series_list=["MJ"],
            components=["21"],
            years=["24"],
            doc_types=["QP"],
        )


def test_optimize_source_order_prefers_verified_availability(monkeypatch):
    monkeypatch.setattr(PaperSourceManager, "SOURCES", {
        "bestexamhelp": {"priority": 1},
        "pastpapersco": {"priority": 2},
        "gceguide": {"priority": 3},
    })
    monkeypatch.setattr(SubjectDatabase, "SUBJECT_SOURCE_MAP", {})
    monkeypatch.setattr(SubjectDatabase, "BESTEXAMHELP_SUPPORTED_CODES", set())

    def fake_availability(cls, code):
        if code == "0620":
            return {"verified": True, "sources": ["gceguide", "pastpapersco"], "checked_at": 1.0}
        return {"verified": False, "sources": [], "checked_at": 0.0}

    monkeypatch.setattr(SubjectDatabase, "get_subject_availability", classmethod(fake_availability))

    order = PaperSourceManager._optimize_source_order_for_subject(
        "0620",
        ["bestexamhelp", "pastpapersco", "gceguide"],
    )
    assert order[0] == "gceguide"
    assert order[1] == "pastpapersco"


def test_invalidate_search_cache_clears_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(PaperSourceManager, "SEARCH_CACHE_FILE", str(tmp_path / "cache.json"))
    PaperSourceManager._search_cache_loaded = True
    PaperSourceManager._search_cache = {
        '{"v":2,"subject_code":"0580","series":["MJ"],"components":["21"],"years":["24"],"doc_types":["QP"],"fm_locked_variant":"","series_component_map":{}}': {
            "timestamp": time.time(),
            "status": "success",
            "groups": [],
        },
        '{"v":2,"subject_code":"0620","series":["MJ"],"components":["21"],"years":["24"],"doc_types":["QP"],"fm_locked_variant":"","series_component_map":{}}': {
            "timestamp": time.time(),
            "status": "success",
            "groups": [],
        },
    }
    PaperSourceManager._search_cache_l1 = {}

    removed = PaperSourceManager.invalidate_search_cache("0580")
    assert removed == 1
    assert "0580" not in str(PaperSourceManager._search_cache)
    assert "0620" in str(PaperSourceManager._search_cache)


def test_add_result_to_groups_filters_er():
    groups_by_key = {}
    item = {
        "subject_code": "0620",
        "subject": "Chemistry",
        "series": "MJ",
        "year": "24",
        "component": "21",
        "type": "ER",
        "filename": "0620_s24_er_21",
        "url": "https://example.com/0620_s24_er_21.pdf",
        "source": "test",
    }
    PaperSourceManager._add_result_to_groups(groups_by_key, item, None)
    assert len(groups_by_key) == 0
