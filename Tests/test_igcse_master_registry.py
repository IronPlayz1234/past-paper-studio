import pytest

pytest.importorskip("PySide6")

from Data.igcse_components_registry import get_all_rows, get_subject_map
from Utils.gui_utils import ComponentsDatabase, SubjectDatabase


def test_registry_contains_exactly_eleven_subjects():
    subjects = get_subject_map()
    rows = get_all_rows()
    assert len(subjects) == 11
    assert {row["subject_code"] for row in rows} == set(subjects)


def test_registry_contains_key_regression_subjects():
    subjects = get_subject_map()
    for code in ("0500", "0580", "0607", "0620", "0478"):
        assert code in subjects


def test_subject_database_igcse_names_are_registry_authoritative():
    assert SubjectDatabase.get_all_subjects("IGCSE") == get_subject_map()


def test_alevel_subject_map_is_still_present():
    alevel = SubjectDatabase.get_all_subjects("A Level")
    assert "9709" in alevel
    assert alevel["9709"] == "Mathematics"


def test_components_database_accepts_base_and_filename_variants():
    assert ComponentsDatabase.validate_component("0620", "1") is True
    assert ComponentsDatabase.validate_component("0620", "01") is True
    assert ComponentsDatabase.validate_component("0620", "11") is True
    assert ComponentsDatabase.validate_component("0620", "7") is False


def test_components_database_preserves_legacy_two_digit_variants():
    assert ComponentsDatabase.validate_component("0580", "41") is True
    assert ComponentsDatabase.validate_component("0580", "42") is True
    assert ComponentsDatabase.validate_component("0580", "43") is True
