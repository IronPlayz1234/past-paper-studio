from Core.paper_mode_router import resolve_mode
from Data.exam_data import get_exam_duration, parse_duration_minutes_from_front_page_text
from Data.subjects_structure import get_paper_spec


def test_alevel_specs_present_for_bestexamhelp_codes():
    from Data.subject_catalog import ALEVEL_SUBJECTS
    for code in ALEVEL_SUBJECTS:
        assert get_paper_spec(code, "1", exam_year=2026) is not None


def test_alevel_mode_routing_for_mcq_and_practical_subjects():
    assert resolve_mode("9702", "1", exam_year=2026).mode == "MCQ_ONLY"
    assert resolve_mode("9702", "3", exam_year=2026).mode == "VIEWER_ONLY"
    assert resolve_mode("9702", "3", exam_year=2026).assessment_type == "practical"
    assert resolve_mode("9708", "1", exam_year=2026).mode == "MCQ_ONLY"
    assert resolve_mode("9709", "5", exam_year=2026).mode == "WRITTEN_ONLY"


def test_unknown_subject_cannot_receive_grades():
    fallback = resolve_mode("9999", "5", exam_year=2026)
    assert fallback.mode == "VIEWER_ONLY"
    assert fallback.gradable is False


def test_retained_english_paper_durations():
    assert get_exam_duration("9093", "1", 2026) == 135
    assert get_exam_duration("9093", "2", 2026) == 120
    for paper in range(1, 5):
        assert get_exam_duration("9695", str(paper), 2026) == 120


def test_parse_duration_minutes_from_front_page_text():
    sample = "Time allowed: 1 hour 30 minutes\\nAnswer all questions."
    assert parse_duration_minutes_from_front_page_text(sample) == 90

    sample2 = "You should spend about 15 minutes on Question 1.\\nTime: 2 hours"
    assert parse_duration_minutes_from_front_page_text(sample2) == 120


def test_practical_safety_does_not_disable_written_science_grading():
    from Core.paper_mode_router import should_enable_ai_grading
    for code in ("9700", "9701", "9702"):
        assert not should_enable_ai_grading(resolve_mode(code, "3", 2026))
        assert should_enable_ai_grading(resolve_mode(code, "4", 2026))
        assert should_enable_ai_grading(resolve_mode(code, "5", 2026))
        assert resolve_mode(code, "not-a-paper", 2026).mode == "VIEWER_ONLY"
