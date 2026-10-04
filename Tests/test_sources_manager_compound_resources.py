import pytest

pytest.importorskip("PySide6")

from Utils.sources_manager import PapacambridgeDocRef, PaperGroup, PaperResource, PaperSourceManager


def test_compound_resource_association_case_insensitive(monkeypatch):
    group = PaperGroup(
        subject_code="0620",
        subject_name="Chemistry",
        session="MJ",
        year="2024",
        component="21",
        source="papacambridge",
        primary_docs={
            "QP": PaperResource(
                kind="QP",
                filename="0620_S24_QP_21.PDF",
                url="https://example.com/0620_S24_QP_21.PDF",
                source="papacambridge",
            )
        },
    )

    monkeypatch.setattr(
        PaperSourceManager,
        "_collect_source_pdf_catalog",
        classmethod(lambda cls, source, subject_code: {}),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_papacambridge_docs_for_series",
        classmethod(lambda cls, subject_code, year, series: []),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_url_exists",
        classmethod(lambda cls, url: str(url).lower().endswith(("_in.pdf", "_sf.pdf"))),
    )

    PaperSourceManager._attach_compound_resources([group])

    assert group.has_insert()
    assert group.has_source_files()
    assert group.resources["IN"].url.lower().endswith("_in.pdf")
    assert group.resources["SF"].url.lower().endswith("_sf.pdf")


def test_safe_join_path_normalizes_separators():
    joined = PaperSourceManager._safe_join_path("base", "nested\\path", "file.pdf")
    assert "\\" not in joined
    assert joined.endswith("nested/path/file.pdf")


def test_grouping_keeps_first_primary_doc_per_kind(monkeypatch):
    monkeypatch.setattr(PaperSourceManager, "SOURCES", {"mock": {"priority": 1}})

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        return [
            {
                "subject": "ICT",
                "subject_code": subject_code,
                "year": "2024",
                "series": series,
                "component": component,
                "type": "QP",
                "type_name": "Question Paper",
                "filename": "0417_s24_qp_11",
                "url": "https://example.com/first_qp.pdf",
                "downloaded": False,
                "source": source_name,
                "is_specimen": False,
            },
            {
                "subject": "ICT",
                "subject_code": subject_code,
                "year": "2024",
                "series": series,
                "component": component,
                "type": "QP",
                "type_name": "Question Paper",
                "filename": "0417_s24_qp_11_dup",
                "url": "https://example.com/second_qp.pdf",
                "downloaded": False,
                "source": source_name,
                "is_specimen": False,
            },
            {
                "subject": "ICT",
                "subject_code": subject_code,
                "year": "2024",
                "series": series,
                "component": component,
                "type": "MS",
                "type_name": "Mark Scheme",
                "filename": "0417_s24_ms_11",
                "url": "https://example.com/ms.pdf",
                "downloaded": False,
                "source": source_name,
                "is_specimen": False,
            },
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0417",
        series_list=["MJ"],
        components=["11"],
        years=["24"],
        doc_types=["QP", "MS"],
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.primary_docs["QP"].url == "https://example.com/first_qp.pdf"
    assert group.primary_docs["MS"].url == "https://example.com/ms.pdf"


def test_attach_papacambridge_insert_even_when_primary_source_is_other(monkeypatch):
    group = PaperGroup(
        subject_code="0500",
        subject_name="English - First Language",
        session="MJ",
        year="2024",
        component="22",
        source="bestexamhelp",
        primary_docs={
            "QP": PaperResource(
                kind="QP",
                filename="0500_s24_qp_22.pdf",
                url="https://bestexamhelp.com/0500_s24_qp_22.pdf",
                source="bestexamhelp",
            )
        },
    )

    monkeypatch.setattr(
        PaperSourceManager,
        "_papacambridge_docs_for_series",
        classmethod(
            lambda cls, subject_code, year, series: [
                PapacambridgeDocRef(
                    filename="0500_s24_in_22.pdf",
                    subject_code="0500",
                    year="2024",
                    session="MJ",
                    component="22",
                    doc_token="in",
                    direct_url="https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0500_s24_in_22.pdf",
                    viewer_url="",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_collect_source_pdf_catalog",
        classmethod(lambda cls, source, subject_code: {}),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_url_exists",
        classmethod(lambda cls, url: False),
    )

    PaperSourceManager._attach_compound_resources([group])

    assert group.has_insert()
    assert group.resources["IN"].filename == "0500_s24_in_22.pdf"
    assert group.resources["IN"].source == "papacambridge"

def test_series_component_map_applies_components_per_series(monkeypatch):
    monkeypatch.setattr(PaperSourceManager, "SOURCES", {"mock": {"priority": 1}})
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    captured_calls = []

    def fake_search_from_source(cls, source_name, subject_code, year, series, component, doc_types):
        captured_calls.append((series, component))
        return [
            {
                "subject": "Chemistry",
                "subject_code": subject_code,
                "year": "2024",
                "series": series,
                "component": component,
                "type": "QP",
                "type_name": "Question Paper",
                "filename": f"{subject_code}_s24_qp_{component}",
                "url": f"https://example.com/{series}_{component}.pdf",
                "downloaded": False,
                "source": source_name,
                "is_specimen": False,
            }
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(fake_search_from_source))

    groups = PaperSourceManager.search_papers_multi_source(
        subject_code="0620",
        series_list=["MJ", "FM"],
        components=["21"],
        years=["24"],
        doc_types=["QP"],
        series_component_map={"MJ": ["21"], "FM": ["22"]},
        fm_locked_variant="2",
    )

    assert ("MJ", "21") in captured_calls
    assert ("FM", "22") in captured_calls
    assert ("FM", "21") not in captured_calls
    assert len(groups) == 2
