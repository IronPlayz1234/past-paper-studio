from Core.paper_mode_router import resolve_mode
from Data.subjects_structure import get_paper_spec


def test_retired_listening_subject_has_no_metadata_or_grading():
    assert get_paper_spec("0520", "1", 2026) is None
    assert resolve_mode("0520", "1", 2026).mode == "VIEWER_ONLY"


def test_retired_language_cannot_reenter_catalog():
    assert get_paper_spec("0549", "1", 2026) is None
    assert not resolve_mode("0549", "1", 2026).gradable


def test_speaking_listening_optional_paper_stays_viewer_only():
    spec = get_paper_spec("0500", "4", exam_year=2026)
    assert spec is not None
    assert spec.mode == "VIEWER_ONLY"
    assert spec.gradable is False


def test_math_calculator_policy_loaded_for_0580():
    assert get_paper_spec("0580", "1", 2026).calculator_policy == "not_allowed"
    assert get_paper_spec("0580", "3", 2026).calculator_policy == "required"
    assert get_paper_spec("0980", "1", 2026) is None
