import pytest

pytest.importorskip("PySide6")

from Utils.sources_manager import PaperGroup, PaperResource, PaperSourceManager


def test_ict_0417_allows_only_source_files_for_p2_p3():
    assert PaperSourceManager._resource_allowed_for_subject("0417", "21", "SOURCE_FILE") is True
    assert PaperSourceManager._resource_allowed_for_subject("0417", "31", "SOURCE_FILE") is True
    assert PaperSourceManager._resource_allowed_for_subject("0417", "11", "SOURCE_FILE") is False
    assert PaperSourceManager._resource_allowed_for_subject("0417", "21", "INSERT") is False


def test_business_0450_insert_only_paper_2():
    assert PaperSourceManager._resource_allowed_for_subject("0450", "21", "INSERT") is True
    assert PaperSourceManager._resource_allowed_for_subject("0450", "22", "INSERT") is True
    assert PaperSourceManager._resource_allowed_for_subject("0450", "11", "INSERT") is False
    assert PaperSourceManager._resource_allowed_for_subject("0450", "21", "SOURCE_FILE") is False


def test_retired_language_subjects_have_no_audio_policy():
    for code in ("0520", "0530", "0544", "0549"):
        assert not PaperSourceManager._resource_allowed_for_subject(code, "11", "AUDIO")
        assert not PaperSourceManager._resource_allowed_for_subject(code, "11", "TRANSCRIPT")


def test_retired_listening_subject_is_not_in_canonical_registry():
    assert not PaperSourceManager._resource_allowed_for_subject("0262", "1", "AUDIO")


def test_listening_resource_fallback_probes_direct_audio_when_listing_missing(monkeypatch):
    group = PaperGroup(
        subject_code="0520",
        subject_name="French - Foreign Language",
        session="MJ",
        year="2024",
        component="1",
        source="papacambridge",
        primary_docs={
            "QP": PaperResource(
                kind="QP",
                filename="0520_s24_qp_1.pdf",
                url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0520_s24_qp_1.pdf",
                source="papacambridge",
            )
        },
    )

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_docs_for_series", lambda *args, **kwargs: [])

    def _probe(url: str):
        if url.endswith("/0520_s24_sf_11.mp3"):
            return (True, 200, url, "audio/mpeg")
        return (False, 404, url, "text/html")

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_head_probe", classmethod(lambda cls, url: _probe(url)))
    monkeypatch.setattr(PaperSourceManager, "_url_exists", lambda *_args, **_kwargs: False)

    PaperSourceManager._attach_compound_resources([group])

    assert group.has_audio() is False
    assert "AU" not in group.resources


def test_resource_family_classification_rules():
    assert PaperSourceManager._classify_resource_family("sf", "zip") == "SOURCE_FILE"
    assert PaperSourceManager._classify_resource_family("sf", "mp3") == "AUDIO"
    assert PaperSourceManager._classify_resource_family("tn", "pdf") == "TRANSCRIPT"
    assert PaperSourceManager._classify_resource_family("qr", "pdf") == "INSERT"
    assert PaperSourceManager._classify_resource_family("map", "pdf") == "MAP"
    assert PaperSourceManager._classify_resource_family("passage", "pdf") == "INSERT"
    assert PaperSourceManager._classify_resource_family("passage_booklet", "pdf") == "INSERT"
    assert PaperSourceManager._classify_resource_family("insert_booklet", "pdf") == "INSERT"
    assert PaperSourceManager._classify_resource_family("source_files", "zip") == "SOURCE_FILE"
    assert PaperSourceManager._classify_resource_family("audio", "mp3") == "AUDIO"
    assert PaperSourceManager._classify_resource_family("transcript", "pdf") == "TRANSCRIPT"


def test_filename_meta_accepts_multiword_tokens_like_passage():
    meta = PaperSourceManager._parse_papacambridge_filename_meta(
        "0500_s24_passage_booklet_22.pdf",
        "0500",
    )
    assert meta is not None
    assert meta["doc_token"] == "passage_booklet"
    assert meta["component"] == "22"


def test_map_resources_allowed_by_default_for_subjects_without_explicit_policy():
    assert PaperSourceManager._resource_allowed_for_subject("0976", "22", "MAP") is True


def test_compound_resource_direct_probe_restores_english_insert_when_listing_empty(monkeypatch):
    group = PaperGroup(
        subject_code="0500",
        subject_name="English - First Language",
        session="MJ",
        year="2024",
        component="21",
        source="bestexamhelp",
        primary_docs={
            "QP": PaperResource(
                kind="QP",
                filename="0500_s24_qp_21.pdf",
                url="https://bestexamhelp.com/exam/cambridge-igcse/english-first-language-0500/2024/0500_s24_qp_21.pdf",
                source="bestexamhelp",
            )
        },
    )

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_docs_for_series", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        PaperSourceManager,
        "_pastpapersco_upload_bases",
        classmethod(lambda cls: ["https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"]),
    )

    def _probe(cls, url: str):
        if str(url).endswith("/0500_s24_in_21.pdf"):
            return (True, 200)
        return (False, 404)

    monkeypatch.setattr(PaperSourceManager, "_pastpapersco_asset_probe", classmethod(_probe))

    PaperSourceManager._attach_compound_resources([group])

    assert group.has_insert() is True
    assert group.resources["IN"].direct_url.endswith("/0500_s24_in_21.pdf")


def test_compound_resource_direct_probe_restores_ict_source_file_when_listing_empty(monkeypatch):
    group = PaperGroup(
        subject_code="0417",
        subject_name="Information and Communication Technology",
        session="MJ",
        year="2024",
        component="31",
        source="bestexamhelp",
        primary_docs={
            "QP": PaperResource(
                kind="QP",
                filename="0417_s24_qp_31.pdf",
                url="https://bestexamhelp.com/exam/cambridge-igcse/information-and-communication-technology-0417/2024/0417_s24_qp_31.pdf",
                source="bestexamhelp",
            )
        },
    )

    monkeypatch.setattr(PaperSourceManager, "_papacambridge_docs_for_series", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        PaperSourceManager,
        "_pastpapersco_upload_bases",
        classmethod(lambda cls: ["https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"]),
    )

    def _probe(cls, url: str):
        if str(url).endswith("/0417_s24_sf_31.zip"):
            return (True, 200)
        return (False, 404)

    monkeypatch.setattr(PaperSourceManager, "_pastpapersco_asset_probe", classmethod(_probe))

    PaperSourceManager._attach_compound_resources([group])

    assert group.has_source_files() is True
    assert group.resources["SF"].direct_url.endswith("/0417_s24_sf_31.zip")
    assert group.resources["SF"].extension == "zip"
