from Grading.cambridge_rule_engine import (
    _numeric_values_match,
    apply_cambridge_rule_grading,
    grade_math_response,
    parse_math_mark_scheme,
)


def test_parse_math_mark_scheme_detects_tokens_and_qualifiers():
    spec = parse_math_mark_scheme("M1 for method\nA1 dep on M1 cao\nFT1 oe")

    assert spec.has_structured_rules is True
    kinds = [token.kind for token in spec.tokens]
    assert "M" in kinds
    assert "A" in kinds
    assert "FT" in kinds
    assert all(token.marks == 1.0 for token in spec.tokens)
    assert any(token.dep for token in spec.tokens if token.kind == "A")
    assert "cao" in spec.qualifiers
    assert "oe" in spec.qualifiers


def test_grade_math_response_awards_method_without_final_accuracy():
    spec = parse_math_mark_scheme("M1 method\nA1 final answer cao")
    result = grade_math_response(
        student_answer="2x + 4 = 10\n2x = 6",
        question_text="Solve for x.",
        spec=spec,
        max_marks=2.0,
    )

    assert result.method_award >= 1.0
    assert result.final_answer_award <= 0.0
    assert 0.99 <= result.marks <= 1.01


def test_grade_math_response_dep_blocks_accuracy_when_method_not_met():
    spec = parse_math_mark_scheme("M1 for method\nA1 dep on M1 cao")
    result = grade_math_response(
        student_answer="7",
        question_text="Solve for x.",
        spec=spec,
        max_marks=2.0,
    )

    assert result.marks <= 0.01
    assert "dep_not_satisfied" in result.warnings


def test_grade_math_response_accepts_fraction_decimal_equivalence():
    spec = parse_math_mark_scheme("A1 answer 0.5")
    result = grade_math_response(
        student_answer="1/2",
        question_text="Give the probability.",
        spec=spec,
        max_marks=1.0,
    )

    assert result.marks >= 0.99


def test_grade_math_response_awards_special_case():
    spec = parse_math_mark_scheme("SC1 for x=0")
    result = grade_math_response(
        student_answer="x = 0",
        question_text="State a special-case root.",
        spec=spec,
        max_marks=1.0,
    )

    assert result.marks >= 0.99


def test_apply_cambridge_rule_grading_math_route_uses_structured_rules():
    result = apply_cambridge_rule_grading(
        subject_code="0580",
        paper_number="4",
        question_text="Solve the equation.",
        student_answer="x = 4",
        mark_scheme_text="A1 x = 4",
        max_marks=1.0,
    )

    assert result is not None
    assert result.rule_type == "math"


def test_grade_math_response_rejects_over_precise_wrong_final_value():
    spec = parse_math_mark_scheme("M4 correct method\nA1 final answer 1.48")
    result = grade_math_response(
        student_answer="working = 74 * 0.0200 = 1.50",
        question_text="Calculate the concentration.",
        spec=spec,
        max_marks=2.0,
    )

    assert result.method_award >= 0.99
    assert result.final_answer_award <= 0.0
    assert 0.99 <= result.marks <= 1.01


def test_grade_math_response_accepts_exact_decimal_match():
    spec = parse_math_mark_scheme("A1 final answer 1.48")
    result = grade_math_response(
        student_answer="1.48",
        question_text="Calculate the concentration.",
        spec=spec,
        max_marks=1.0,
    )

    assert result.final_answer_award >= 0.99
    assert result.marks >= 0.99


def test_grade_math_response_accepts_exact_equivalent_decimal_precision():
    spec = parse_math_mark_scheme("A1 final answer 1.48")
    result = grade_math_response(
        student_answer="1.480",
        question_text="Calculate the concentration.",
        spec=spec,
        max_marks=1.0,
    )

    assert result.final_answer_award >= 0.99
    assert result.marks >= 0.99


def test_grade_math_response_accepts_two_sig_fig_answer():
    spec = parse_math_mark_scheme("A1 final answer 1.48")
    result = grade_math_response(
        student_answer="1.5",
        question_text="Calculate the concentration.",
        spec=spec,
        max_marks=1.0,
    )

    assert result.final_answer_award >= 0.99
    assert result.marks >= 0.99


def test_numeric_values_match_rejects_150_for_148_when_student_precision_is_strict():
    assert _numeric_values_match(1.50, 1.48, "1.48", "1.50") is False


def test_numeric_values_match_accepts_exact_and_equivalent_values():
    assert _numeric_values_match(1.48, 1.48, "1.48", "1.48") is True
    assert _numeric_values_match(1.480, 1.48, "1.48", "1.480") is True


def test_numeric_values_match_accepts_two_sig_fig_student_answer():
    assert _numeric_values_match(1.5, 1.48, "1.48", "1.5") is True


def test_numeric_values_match_accepts_bracketed_trailing_digits_notation():
    assert _numeric_values_match(0.001, 0.00100, "0.001(00)", "0.001") is True
    assert _numeric_values_match(0.0200, 0.0200, "0.02(00)", "0.0200") is True
    assert _numeric_values_match(74, 74, "74", "74") is True


def test_grade_math_response_scores_intermediate_chain_steps_but_rejects_wrong_final_value():
    spec = parse_math_mark_scheme(
        "M1 Mol HCl = 0.0500 × 20.0 / 1000 = 0.001(00)\n"
        "M2 Mol Ca(OH)2 = M1 / 2 = 0.00100 / 2 = 0.0005(00)\n"
        "M3 M2 × 1000 / 25 = 0.0005(00) × 40 = 0.02(00)\n"
        "M4 Mr Ca(OH)2 = 74\n"
        "M5 M4 × M3 = 74 × 0.02 = 1.48 (g / dm3)"
    )
    result = grade_math_response(
        student_answer=(
            "moles of HCl = 0.0500 × 20.0 / 1000 = 0.00100\n"
            "moles of Ca(OH)2 = 0.00100 / 2 = 0.000500\n"
            "concentration = 0.000500 × 1000 / 25.0 = 0.0200\n"
            "Mr = 74\n"
            "concentration in g/dm3 = 74 × 0.0200 = 1.50"
        ),
        question_text="Calculate the concentration of Ca(OH)2 in g/dm3.",
        spec=spec,
        max_marks=5.0,
    )

    assert result.method_award == 4.0
    assert result.final_answer_award == 0.0
    assert result.marks == 4.0
