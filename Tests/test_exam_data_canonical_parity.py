from Data.exam_data import (
    get_exam_duration,
    get_mcq_count,
    get_paper_type_from_subject,
    is_mcq_paper,
    parse_total_marks_from_front_page_text,
)
from Data.subjects_structure import get_paper_spec


def test_exam_duration_matches_subject_structure_for_key_subjects():
    checks = [
        ("0580", "4", 2026),
        ("0607", "3", 2026),
        ("0620", "6", 2026),
    ]
    for subject_code, paper, exam_year in checks:
        spec = get_paper_spec(subject_code, paper, exam_year=exam_year)
        assert spec is not None
        expected = spec.duration_minutes if spec.duration_minutes is not None else 60
        assert get_exam_duration(subject_code, paper, exam_year) == expected


def test_is_mcq_paper_aligns_with_canonical_routing():
    assert is_mcq_paper("0620", "1") is True
    assert is_mcq_paper("0620", "4") is False
    assert is_mcq_paper("0580", "1") is False


def test_get_paper_type_from_subject_aligns_with_canonical_data():
    assert get_paper_type_from_subject("Chemistry", "0620", "1") == "MCQ"
    assert get_paper_type_from_subject("Chemistry", "0620", "5") == "Practical"
    assert get_paper_type_from_subject("Mathematics", "0580", "3") == "Written"


def test_get_mcq_count_returns_zero_for_non_mcq_and_positive_for_mcq():
    assert get_mcq_count("0620", "1") > 0
    assert get_mcq_count("0580", "1") == 0


def test_retired_listening_subjects_have_no_mcq_count():
    for code in ("0520", "0528", "0685", "7156"):
        assert get_mcq_count(code, "1") == 0


def test_parse_total_marks_from_front_page_text_detects_maximum_mark():
    text = """
    Cambridge IGCSE Chemistry 0620/42
    Maximum mark: 80
    Candidates answer on the Question Paper.
    """
    assert parse_total_marks_from_front_page_text(text) == 80


def test_parse_total_marks_from_front_page_text_ignores_noise_without_marker_context():
    text = """
    You may use an HB pencil.
    Time: 1 hour 15 minutes
    Answer all questions.
    Page 1 of 16
    """
    assert parse_total_marks_from_front_page_text(text) is None
