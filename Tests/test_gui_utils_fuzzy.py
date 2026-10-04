import pytest

pytest.importorskip("PySide6")

from Utils.gui_utils import SubjectDatabase, get_subject_folder, parse_range, series_to_code


def test_subject_fuzzy_typo_matches_economics(monkeypatch):
    assert SubjectDatabase.find_subject_code("econmics", level="IGCSE") == "0455"


def test_a_level_chem_prefers_searchable_static_code_over_dynamic(monkeypatch):
    monkeypatch.setattr(SubjectDatabase, "DYNAMIC_ALEVEL_SUBJECTS", {"9185": "Chemistry"}, raising=False)

    assert SubjectDatabase.find_subject_code("chem", level="A Level") == "9701"
    assert SubjectDatabase.find_subject_code("chemistry", level="A Level") == "9701"


def test_retained_first_language_english_label_and_folder():
    assert SubjectDatabase.get_subject_name("0500") == "First Language English"
    assert get_subject_folder("0500") == "english-first-language-0500"
    assert SubjectDatabase.find_subject_code("0502") is None


def test_component_parser_normalizes_common_typos():
    parsed = parse_range("2l,2O;21")
    assert "21" in parsed
    assert "20" in parsed


def test_series_to_code_supports_specimen_alias():
    assert series_to_code("SP") == "y"
