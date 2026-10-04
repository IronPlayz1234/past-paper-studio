from Data.subjects_structure import list_supported_subjects
from Grading.ai_grading import should_use_ai_grading
from Grading.subject_grading_profiles import (
    PROFILES,
    SUBJECT_CODE_TO_PROFILE,
    get_subject_grading_profile,
    get_subject_profile_key,
    render_profile_block,
)


def test_profile_selection_for_science_language_and_humanities():
    chem = get_subject_grading_profile("0620", "4")
    english = get_subject_grading_profile("0500", "1")
    history = get_subject_grading_profile("0470", "2")

    assert chem.key == "chemistry"
    assert english.key == "english_reading"
    assert history.key == "history"


def test_profile_block_contains_grading_style_and_ocr_notes():
    profile = get_subject_grading_profile("0580", "2")
    block = render_profile_block(profile)

    assert "Rubric axes" in block
    assert "Units policy" in block
    assert "Grading Style" in block
    assert "OCR notes" in block


def test_should_use_ai_grading_respects_viewer_only_and_written_modes():
    assert should_use_ai_grading("0417", "2", 2026) is False
    assert should_use_ai_grading("0417", "1", 2026) is True
    assert should_use_ai_grading("0620", "1", 2026) is False
    assert should_use_ai_grading("0620", "4", 2026) is True


def test_profile_mapping_includes_further_math_and_statistics():
    assert get_subject_profile_key("9709", "1") == "mathematics"
    assert get_subject_grading_profile("9709", "1").key == "mathematics"
    assert get_subject_profile_key("9231", "1") == "further_mathematics"
    assert get_subject_profile_key("4040", "1") == "default"


def test_retired_subjects_have_no_grading_profile():
    for code in ("4024", "4037", "0459", "9713", "0990"):
        assert get_subject_profile_key(code, "1") == "default"


def test_profile_mapping_includes_alevel_science_and_computing():
    assert get_subject_profile_key("9702", "1") == "physics"
    assert get_subject_profile_key("9701", "1") == "chemistry"
    assert get_subject_profile_key("9700", "1") == "biology"
    assert get_subject_profile_key("9618", "1") == "computer_science"


def test_english_first_language_paper_two_uses_writing_profile():
    assert get_subject_profile_key("0500", "2") == "english_writing"
    assert get_subject_profile_key("0500", "1") == "english_reading"


def test_all_supported_subjects_resolve_to_non_default_profile():
    supported = list_supported_subjects()
    missing = []
    unknown_profiles = []
    for code in supported:
        profile_key = get_subject_profile_key(code, "")
        if profile_key == "default":
            missing.append(code)
        if profile_key not in PROFILES:
            unknown_profiles.append((code, profile_key))
        assert SUBJECT_CODE_TO_PROFILE[code] == profile_key

    assert missing == []
    assert unknown_profiles == []
