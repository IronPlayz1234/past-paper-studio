from Grading.cambridge_rule_engine import (
    apply_cambridge_rule_grading,
    parse_science_practical_mark_scheme,
    grade_science_practical_response,
)


def test_parse_science_practical_mark_scheme_detects_required_count_and_units():
    spec = parse_science_practical_mark_scheme(
        "temperature rises\nrecord value in cm3",
        "State two observations.",
    )

    assert spec.required_count == 2
    assert "cm3" in spec.expected_units


def test_science_list_rule_counts_only_required_slots():
    spec = parse_science_practical_mark_scheme(
        "solution turns blue\nbubbles produced",
        "State two observations.",
    )
    result = grade_science_practical_response(
        "solution turns blue; bubbles produced; extra wrong statement",
        "State two observations.",
        spec,
        max_marks=2.0,
    )

    assert result.marks >= 1.5


def test_science_contradiction_adds_warning():
    spec = parse_science_practical_mark_scheme(
        "temperature increases",
        "Describe the trend.",
    )
    result = grade_science_practical_response(
        "temperature increases and then decreases",
        "Describe the trend.",
        spec,
        max_marks=1.0,
    )

    assert "contradictory_response_detected" in result.warnings


def test_science_ecf_numeric_chain_can_award_credit():
    spec = parse_science_practical_mark_scheme(
        "ecf allowed\nfinal concentration",
        "Calculate concentration.",
    )
    result = grade_science_practical_response(
        "0.25",
        "Calculate concentration.",
        spec,
        max_marks=1.0,
    )

    assert result.marks > 0.0


def test_apply_cambridge_rule_grading_science_practical_route():
    result = apply_cambridge_rule_grading(
        subject_code="0620",
        paper_number="6",
        question_text="State two observations.",
        student_answer="turns blue; bubbles",
        mark_scheme_text="turns blue\nbubbles produced",
        max_marks=2.0,
    )

    assert result is not None
    assert result.rule_type == "science_practical"


def test_parse_science_practical_mark_scheme_strips_rogue_interior_digit_artifact():
    spec = parse_science_practical_mark_scheme(
        "(aqueous) sodium hydroxide\n1\nwhite ppt\ninsoluble / remains in excess",
        "State three observations.",
    )

    assert spec.points == [
        "(aqueous) sodium hydroxide",
        "white ppt",
        "insoluble / remains in excess",
    ]


def test_parse_science_practical_mark_scheme_preserves_single_line_numeric_answer():
    spec = parse_science_practical_mark_scheme(
        "3",
        "State the value.",
    )

    assert spec.points == ["3"]
