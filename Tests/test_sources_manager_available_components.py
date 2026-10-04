from Utils.gui_utils import ComponentsDatabase, SubjectDatabase
from Utils.sources_manager import PaperSourceManager


def _reset_component_cache_state(cache_path: str) -> None:
    PaperSourceManager.COMPONENT_CACHE_FILE = str(cache_path)
    PaperSourceManager._component_cache_loaded = False
    PaperSourceManager._component_cache_dirty = False
    PaperSourceManager._component_cache = {}


def test_available_components_groups_variants(monkeypatch, tmp_path):
    _reset_component_cache_state(tmp_path / "available_components_cache.json")

    monkeypatch.setattr(
        SubjectDatabase,
        "is_searchable_subject",
        classmethod(lambda cls, _code: True),
    )
    monkeypatch.setattr(
        ComponentsDatabase,
        "COMPONENTS",
        {"0620": ["11", "21", "22", "23", "41", "42", "43"]},
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_component_label_from_row",
        classmethod(lambda cls, _subject, paper, _year: f"Paper {paper}"),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_component_type_from_row",
        classmethod(lambda cls, _subject, _paper: "Written"),
    )

    existing = {"11", "21", "22", "23", "41", "42", "43"}

    def fake_exists(cls, _subject_code, _series, _year, component):
        return str(component) in existing

    monkeypatch.setattr(PaperSourceManager, "_bestexamhelp_component_exists", classmethod(fake_exists))

    rows = PaperSourceManager.get_available_components("0620", "MJ", "2023", refresh=True)
    by_component = {str(row.get("component")): row for row in rows}

    assert set(by_component.keys()) == {"1", "2", "4"}
    assert by_component["2"]["variants"] == ["21", "22", "23"]
    assert by_component["2"]["full_component"] == "21"
    assert by_component["4"]["variants"] == ["41", "42", "43"]


def test_available_components_uses_cache(monkeypatch, tmp_path):
    _reset_component_cache_state(tmp_path / "available_components_cache.json")

    monkeypatch.setattr(
        SubjectDatabase,
        "is_searchable_subject",
        classmethod(lambda cls, _code: True),
    )
    monkeypatch.setattr(
        ComponentsDatabase,
        "COMPONENTS",
        {"0580": ["21", "22", "23"]},
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_component_label_from_row",
        classmethod(lambda cls, _subject, paper, _year: f"Paper {paper}"),
    )
    monkeypatch.setattr(
        PaperSourceManager,
        "_component_type_from_row",
        classmethod(lambda cls, _subject, _paper: "Written"),
    )

    calls = {"count": 0}

    def fake_exists(cls, _subject_code, _series, _year, _component):
        calls["count"] += 1
        return True

    monkeypatch.setattr(PaperSourceManager, "_bestexamhelp_component_exists", classmethod(fake_exists))

    first = PaperSourceManager.get_available_components("0580", "MJ", "2024", refresh=False)
    first_calls = calls["count"]
    second = PaperSourceManager.get_available_components("0580", "MJ", "2024", refresh=False)

    assert first
    assert second
    assert calls["count"] == first_calls
