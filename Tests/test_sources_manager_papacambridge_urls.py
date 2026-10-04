import re
import time

import pytest

pytest.importorskip("PySide6")

from Utils.sources_manager import PapacambridgeDocRef, PaperSourceManager


class _Resp:
    def __init__(self, text: str):
        self.text = text


class _ProbeResp:
    def __init__(self, status_code: int, headers: dict, url: str, body: bytes = b""):
        self.status_code = status_code
        self.headers = headers
        self.url = url
        self._body = body

    def iter_content(self, chunk_size: int = 4096):
        if self._body:
            yield self._body[:chunk_size]


@pytest.fixture(autouse=True)
def _reset_probe_caches(monkeypatch):
    import requests
    monkeypatch.setattr(PaperSourceManager, "_session", requests.Session())
    PaperSourceManager._url_pdf_probe_cache.clear()
    PaperSourceManager._pastpapersco_preferred_base = ""
    PaperSourceManager._component_style_cache.clear()
    yield
    PaperSourceManager._url_pdf_probe_cache.clear()
    PaperSourceManager._component_style_cache.clear()


def test_extract_direct_url_from_download_link():
    href = (
        "https://pastpapers.papacambridge.com/download_file.php?files="
        "https%3A%2F%2Fpastpapers.papacambridge.com%2Fdirectories%2FCAIE%2FCAIE-pastpapers%2Fupload%2F0417_m24_sf_31.zip"
    )
    direct = PaperSourceManager._extract_papacambridge_direct_from_download_href(href)
    assert direct.endswith("/0417_m24_sf_31.zip")


def test_parse_listing_joins_viewer_and_download(monkeypatch):
    html = """
    <html><body>
      <a href=\"/viewer/caie/0417_m24_qp_22.pdf\">View</a>
      <a href=\"/download_file.php?files=https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0417_m24_qp_22.pdf\">Download</a>
      <a href=\"/download_file.php?files=https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0417_m24_sf_22.zip\">Download SF</a>
    </body></html>
    """

    monkeypatch.setattr(PaperSourceManager._session, "get", lambda *args, **kwargs: _Resp(html))

    refs = PaperSourceManager._parse_papacambridge_year_listing(
        listing_url="https://pastpapers.papacambridge.com/papers/caie/igcse-ict0417-2024-march",
        subject_code="0417",
        expected_year="2024",
        expected_session="FM",
    )

    by_name = {ref.filename: ref for ref in refs}
    assert "0417_m24_qp_22.pdf" in by_name
    assert "0417_m24_sf_22.zip" in by_name
    assert by_name["0417_m24_qp_22.pdf"].viewer_url.endswith("/viewer/caie/0417_m24_qp_22.pdf")
    assert by_name["0417_m24_qp_22.pdf"].direct_url.endswith("/0417_m24_qp_22.pdf")


def test_component_probe_variations_match_new_rules():
    assert PaperSourceManager._papacambridge_component_fallbacks("1") == ["1", "01", "11", "12", "13"]
    assert PaperSourceManager._papacambridge_component_fallbacks("2") == ["2", "02", "21", "22", "23"]
    assert PaperSourceManager._papacambridge_component_fallbacks("11") == ["11", "1", "01", "12", "13"]
    assert PaperSourceManager._papacambridge_component_fallbacks("42") == ["42", "4", "04", "41", "43"]


def test_pastpapersco_upload_bases_prioritize_canonical_direct_upload():
    PaperSourceManager._pastpapersco_preferred_base = ""
    bases = PaperSourceManager._pastpapersco_upload_bases()
    assert bases
    assert bases[0] == PaperSourceManager.PASTPAPERSCO_CANONICAL_UPLOAD_BASE


def test_direct_probe_skips_repeated_unreachable_base(monkeypatch):
    dead_base = "https://dead.example/upload"
    live_base = "https://live.example/upload"
    calls = {"dead": 0, "live": 0}
    PaperSourceManager._url_pdf_probe_cache.clear()

    monkeypatch.setattr(
        PaperSourceManager,
        "_pastpapersco_upload_bases",
        classmethod(lambda cls: [dead_base, live_base]),
    )

    def _probe(cls, url: str):
        if str(url).startswith(dead_base):
            calls["dead"] += 1
            return (False, 0)
        calls["live"] += 1
        component = re.search(r"_qp_(\d+)\.pdf$", url).group(1)  # type: ignore[union-attr]
        if component == "11":
            return (True, 200)
        return (False, 404)

    monkeypatch.setattr(PaperSourceManager, "_pastpapersco_asset_probe", classmethod(_probe))

    rows = PaperSourceManager._search_papacambridge_hardcoded_direct(
        subject_code="0452",
        year="24",
        series="MJ",
        component="1",
        doc_types=["QP"],
    )

    assert len(rows) == 1
    assert rows[0]["component"] == "11"
    assert calls["dead"] == 1
    assert calls["live"] == 2
    PaperSourceManager._url_pdf_probe_cache.clear()


def test_direct_hardcoded_probe_skips_403_404_and_tries_next(monkeypatch):
    attempts = []

    def _probe(url: str):
        component = re.search(r"_qp_(\d+)\.pdf$", url).group(1)  # type: ignore[union-attr]
        attempts.append(component)
        if component == "1":
            return (False, 404, url, "text/html")
        if component == "01":
            return (False, 403, url, "text/html")
        return (True, 200, url, "application/pdf")

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_head_probe", classmethod(lambda cls, url: _probe(url)))

    rows = PaperSourceManager._search_papacambridge_hardcoded_direct(
        subject_code="0452",
        year="24",
        series="MJ",
        component="1",
        doc_types=["QP"],
    )

    assert attempts == ["01", "11"]
    assert len(rows) == 1
    assert rows[0]["component"] == "11"
    assert rows[0]["type"] == "QP"


def test_direct_hardcoded_probe_skips_non_asset_success(monkeypatch):
    def _probe(url: str):
        component = re.search(r"_qp_(\d+)\.pdf$", url).group(1)  # type: ignore[union-attr]
        if component == "1":
            return (False, 200, "https://pastpapers.papacambridge.com/papers/caie/igcse", "text/html"), component
        return (True, 200, url, "application/pdf"), component

    probe_calls = []

    def _wrapped_probe(url: str):
        result, component = _probe(url)
        probe_calls.append(component)
        return result

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_head_probe", classmethod(lambda cls, url: _wrapped_probe(url)))

    rows = PaperSourceManager._search_papacambridge_hardcoded_direct(
        subject_code="0452",
        year="24",
        series="MJ",
        component="1",
        doc_types=["QP"],
    )

    assert probe_calls[0] == "01"
    assert "01" in probe_calls
    assert len(rows) == 1
    assert rows[0]["component"] == "01"


def test_search_papacambridge_uses_hardcoded_path_before_listing(monkeypatch):
    hardcoded_row = PaperSourceManager._format_result(
        subject_code="0452",
        year="24",
        series="MJ",
        component="1",
        doc_type="QP",
        filename="0452_s24_qp_1",
        url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0452_s24_qp_1.pdf",
        source="papacambridge",
    )

    monkeypatch.setattr(
        PaperSourceManager,
        "_search_papacambridge_hardcoded_direct",
        classmethod(lambda cls, **kwargs: [hardcoded_row]),
    )

    calls = {"listing": 0}

    def _listing(*_args, **_kwargs):
        calls["listing"] += 1
        return []

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_docs_for_series", _listing)

    rows = PaperSourceManager._search_papacambridge(
        subject_code="0452",
        year="24",
        series="MJ",
        component="1",
        doc_types=["QP"],
    )
    assert len(rows) == 1
    assert calls["listing"] == 0


def test_search_papacambridge_uses_listing_when_hardcoded_misses(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "_search_papacambridge_hardcoded_direct",
        classmethod(lambda cls, **kwargs: []),
    )

    monkeypatch.setattr(
        PaperSourceManager,
        "_papacambridge_docs_for_series",
        classmethod(
            lambda cls, subject_code, year, series: [
                PapacambridgeDocRef(
                    filename="0452_s24_qp_11.pdf",
                    subject_code=subject_code,
                    year="2024",
                    session="MJ",
                    component="11",
                    doc_token="qp",
                    direct_url=(
                        "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/"
                        "0452_s24_qp_11.pdf"
                    ),
                    viewer_url="https://pastpapers.papacambridge.com/viewer/caie/0452_s24_qp_11.pdf",
                )
            ]
        ),
    )

    rows = PaperSourceManager._search_papacambridge(
        subject_code="0452",
        year="24",
        series="MJ",
        component="1",
        doc_types=["QP"],
    )
    assert len(rows) == 1
    assert rows[0]["type"] == "QP"
    assert rows[0]["source"] == "papacambridge"


def test_papacambridge_on_session_slug_uses_oct_nov(monkeypatch):
    calls = {"listing_url": ""}

    monkeypatch.setattr(
        PaperSourceManager,
        "_resolve_papacambridge_subject_slug",
        lambda *_args, **_kwargs: "igcse-business-studies-0450",
    )

    def _capture_listing(cls, *, listing_url, subject_code, expected_year, expected_session):
        _ = (cls, subject_code, expected_year, expected_session)
        calls["listing_url"] = listing_url
        return []

    monkeypatch.setattr(PaperSourceManager, "_parse_papacambridge_year_listing", classmethod(_capture_listing))
    PaperSourceManager._papacambridge_docs_cache.clear()
    PaperSourceManager._papacambridge_docs_for_series("0450", "2024", "ON")

    assert calls["listing_url"].endswith("-2024-oct-nov")


def test_head_probe_rejects_redirect_to_html(monkeypatch):
    class _HeadResp:
        def __init__(self):
            self.status_code = 200
            self.url = "https://pastpapers.papacambridge.com/papers/caie/igcse"
            self.headers = {"content-type": "text/html; charset=utf-8"}

        def close(self):
            return None

    monkeypatch.setattr(PaperSourceManager._session, "head", lambda *args, **kwargs: _HeadResp())
    ok, status, final_url, content_type = PaperSourceManager._papacambridge_head_probe(
        "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0452_s24_qp_11.pdf"
    )
    assert ok is False
    assert status == 200
    assert final_url.endswith("/igcse")
    assert "text/html" in content_type


def test_search_papacambridge_returns_empty_when_hardcoded_path_fails(monkeypatch):
    monkeypatch.setattr(
        PaperSourceManager,
        "_search_papacambridge_hardcoded_direct",
        classmethod(lambda cls, **kwargs: []),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_papacambridge_docs_for_series",
        classmethod(lambda cls, *args, **kwargs: []),
    )
    rows = PaperSourceManager._search_papacambridge(
        subject_code="0427",
        year="2024",
        series="MJ",
        component="11",
        doc_types=["QP"],
    )
    assert rows == []


def test_parse_meta_allows_componentless_gt():
    meta = PaperSourceManager._parse_papacambridge_filename_meta("0427_s24_gt.pdf", "0427")
    assert meta is not None
    assert meta["doc_token"] == "gt"
    assert meta["component"] == ""


def test_papacambridge_docs_empty_result_is_not_sticky(monkeypatch):
    PaperSourceManager._papacambridge_docs_cache.clear()
    monkeypatch.setattr(PaperSourceManager, "ENABLE_PASTPAPERSCO_LISTING_FALLBACK", True)

    monkeypatch.setattr(
        PaperSourceManager,
        "_resolve_papacambridge_subject_slug",
        lambda *_args, **_kwargs: "igcse-computer-science-0478",
    )

    calls = {"count": 0}

    def _fake_parse(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        return [
            PapacambridgeDocRef(
                filename="0478_s24_qp_12.pdf",
                subject_code="0478",
                year="2024",
                session="MJ",
                component="12",
                doc_token="qp",
                direct_url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0478_s24_qp_12.pdf",
                viewer_url="",
            )
        ]

    monkeypatch.setattr(PaperSourceManager, "_parse_papacambridge_year_listing", _fake_parse)

    first = PaperSourceManager._papacambridge_docs_for_series("0478", "2024", "MJ")
    second = PaperSourceManager._papacambridge_docs_for_series("0478", "2024", "MJ")

    assert first == []
    assert len(second) == 1
    assert calls["count"] == 2


def test_url_routing_pdf_viewer_nonpdf_direct():
    pdf_row = PaperSourceManager._format_result(
        subject_code="0417",
        year="2024",
        series="FM",
        component="22",
        doc_type="QP",
        filename="0417_m24_qp_22",
        url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0417_m24_qp_22.pdf",
        source="papacambridge",
        direct_url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0417_m24_qp_22.pdf",
        viewer_url="https://pastpapers.papacambridge.com/viewer/caie/0417_m24_qp_22.pdf",
        extension="pdf",
    )
    assert pdf_row["open_url"].endswith("/0417_m24_qp_22.pdf")
    assert pdf_row["download_url"].endswith("/0417_m24_qp_22.pdf")

    audio_row = PaperSourceManager._format_result(
        subject_code="0520",
        year="2024",
        series="MJ",
        component="11",
        doc_type="AU",
        filename="0520_s24_sf_11",
        url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0520_s24_sf_11.mp3",
        source="papacambridge",
        direct_url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0520_s24_sf_11.mp3",
        viewer_url="https://pastpapers.papacambridge.com/viewer/caie/0520_s24_sf_11.mp3",
        extension="mp3",
    )
    assert audio_row["open_url"].endswith("/0520_s24_sf_11.mp3")
    assert audio_row["download_url"].endswith("/0520_s24_sf_11.mp3")


def test_url_exists_rejects_html_payload_even_if_pdf_suffix(monkeypatch):
    target = "https://example.com/fake.pdf"
    PaperSourceManager._url_pdf_probe_cache.clear()

    monkeypatch.setattr(
        PaperSourceManager._session,
        "head",
        lambda *args, **kwargs: _ProbeResp(
            200,
            {"content-type": "application/octet-stream"},
            target,
        ),
    )
    monkeypatch.setattr(
        PaperSourceManager._session,
        "get",
        lambda *args, **kwargs: _ProbeResp(
            200,
            {"content-type": "application/octet-stream"},
            target,
            body=b"<!doctype html><html><body>login</body></html>",
        ),
    )

    assert PaperSourceManager._url_exists(target) is False


def test_url_exists_accepts_pdf_signature_when_content_type_generic(monkeypatch):
    target = "https://example.com/real.pdf"
    PaperSourceManager._url_pdf_probe_cache.clear()

    monkeypatch.setattr(
        PaperSourceManager._session,
        "head",
        lambda *args, **kwargs: _ProbeResp(
            200,
            {"content-type": "application/octet-stream"},
            target,
        ),
    )
    monkeypatch.setattr(
        PaperSourceManager._session,
        "get",
        lambda *args, **kwargs: _ProbeResp(
            200,
            {"content-type": "application/octet-stream"},
            target,
            body=b"%PDF-1.7\n%",
        ),
    )

    assert PaperSourceManager._url_exists(target) is True


def test_source_catalog_empty_cache_entry_expires(monkeypatch):
    cache_key = "dynamicpapers|0620"
    monkeypatch.setattr(PaperSourceManager, "SOURCE_PDF_CATALOG_NEGATIVE_TTL_SECONDS", 1)
    PaperSourceManager._source_pdf_catalog_cache[cache_key] = {
        "catalog": {},
        "checked_at": time.time() - 10.0,
        "status": "empty",
    }

    monkeypatch.setattr(
        PaperSourceManager,
        "_http_get_text",
        classmethod(
            lambda cls, url, timeout=None: (
                '<a href="https://dynamicpapers.com/wp-content/uploads/0620_s24_qp_42.pdf">qp</a>'
            )
        ),
    )

    catalog = PaperSourceManager._collect_source_pdf_catalog("dynamicpapers", "0620")
    key = PaperSourceManager._normalize_file_key("0620_s24_qp_42.pdf")
    assert key in catalog


def test_gceguide_subject_cache_negative_entry_expires(monkeypatch):
    index_url = "https://www.gceguide.cc/papers/cambridge-IGCSE/"
    cache_key = f"{index_url}|0620"
    monkeypatch.setattr(PaperSourceManager, "GCEGUIDE_SUBJECT_NEGATIVE_TTL_SECONDS", 1)
    PaperSourceManager._gceguide_subject_cache[cache_key] = {
        "subject_page": None,
        "checked_at": time.time() - 10.0,
        "status": "empty",
    }

    monkeypatch.setattr(
        PaperSourceManager,
        "_http_get_text",
        classmethod(
            lambda cls, url, timeout=None: (
                '<a href="chemistry-0620/">Chemistry (0620)</a>'
            )
        ),
    )

    subject_page = PaperSourceManager._resolve_gceguide_subject_page(index_url, "0620")
    assert subject_page == "https://www.gceguide.cc/papers/cambridge-IGCSE/chemistry-0620/"
