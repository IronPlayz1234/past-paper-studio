import pytest

from Utils.gui_utils import series_to_code
from Utils.sources_manager import PaperNotFoundError, PaperSourceManager


def test_specimen_mode_is_temporarily_disabled(monkeypatch):
    monkeypatch.setattr(PaperSourceManager, "SOURCES", {"mock": {"priority": 1}})
    monkeypatch.setattr(PaperSourceManager, "_search_from_source", classmethod(lambda cls, *args, **kwargs: []))
    monkeypatch.setattr(PaperSourceManager, "_attach_compound_resources", classmethod(lambda cls, groups: None))

    calls = {"count": 0}

    def fake_specimen(cls, *args, **kwargs):
        calls["count"] += 1
        return [
            {
                "subject": "Chemistry",
                "subject_code": "0620",
                "year": "2025",
                "series": "SP",
                "component": "4",
                "type": "QP",
                "type_name": "Specimen Question Paper",
                "filename": "0620_y25_sp_4",
                "url": "https://example.com/0620_y25_sp_4.pdf",
                "downloaded": False,
                "source": "mock",
                "is_specimen": True,
            }
        ]

    monkeypatch.setattr(PaperSourceManager, "_search_specimen_multi_source", classmethod(fake_specimen))

    with pytest.raises(PaperNotFoundError, match="Paper not found"):
        PaperSourceManager.search_papers_multi_source(
            subject_code="0620",
            series_list=["MJ"],
            components=["41"],
            years=["24"],
            doc_types=["QP"],
            include_specimen=True,
        )

    assert calls["count"] == 0


def test_series_to_code_no_specimen_mapping():
    assert series_to_code("MJ") == "s"
    assert series_to_code("ON") == "w"
    assert series_to_code("FM") == "m"
    assert series_to_code("SP") == "y"
