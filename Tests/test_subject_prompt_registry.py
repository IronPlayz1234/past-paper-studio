import pytest

from Grading.ai_config import AIConfig
from Grading.ai_grading import UnifiedAIGrader, check_math_answer
from Grading.subject_prompt_registry import get_subject_prompt_context


def _stub_grader() -> UnifiedAIGrader:
    grader = UnifiedAIGrader.__new__(UnifiedAIGrader)
    grader.config = AIConfig(
        api_key="test-key",
        text_model="meta-llama/llama-4-scout-17b-16e-instruct",
        vision_model="meta-llama/llama-4-scout-17b-16e-instruct",
        timeout=120,
        max_tokens=1000,
        temperature=0.0,
    )
    return grader


def test_subject_prompt_registry_resolves_igcse_science_subjects_with_paper_context():
    biology = get_subject_prompt_context("0610", "6")
    chemistry = get_subject_prompt_context("0620", "4")
    physics = get_subject_prompt_context("0625", "3")

    assert biology.applies is True
    assert biology.subject_key == "biology"
    assert "Alternative to Practical" in biology.system_addendum

    assert chemistry.applies is True
    assert chemistry.subject_key == "chemistry"
    assert "Paper 4" in chemistry.system_addendum

    assert physics.applies is True
    assert physics.subject_key == "physics"
    assert "Paper 3" in physics.system_addendum


def test_subject_prompt_registry_is_profile_driven_for_math_and_economics():
    math_context = get_subject_prompt_context("0580", "2")
    assert math_context.applies is True
    assert math_context.subject_key == "mathematics"
    assert "METHOD MARKS" in math_context.system_addendum

    economics_context = get_subject_prompt_context("0455", "2")
    assert economics_context.applies is True
    assert economics_context.subject_key == "economics"
    assert "Business Studies / Economics" in economics_context.system_addendum


def test_text_prompt_adds_subject_context_without_losing_base_strict_rules():
    grader = _stub_grader()
    system_prompt, user_prompt = grader._build_text_prompt(
        question_id="1",
        question_text="State one product of complete combustion of methane.",
        student_answer="carbon dioxide",
        mark_scheme_text="carbon dioxide",
        max_marks=1.0,
        subject="0620",
        paper_type="4",
    )

    assert "SOLE authoritative source of truth" in system_prompt
    assert "RULE 1 — MISSING MARK SCHEME" in system_prompt
    assert "RULE 2 — MAX MARKS CEILING" in system_prompt
    assert "RULE 4 — CHAINED METHOD MARKS" in system_prompt
    assert "RULE 8 — NO HALLUCINATION" in system_prompt
    assert "CHEMICAL FORMULAE" in system_prompt
    assert "Subject-specific marking guidance" in user_prompt
    assert "Verify formulae are chemically correct" in user_prompt


def test_text_prompt_uses_paper_6_practical_addendum_for_biology():
    grader = _stub_grader()
    system_prompt, user_prompt = grader._build_text_prompt(
        question_id="6(a)",
        question_text="Describe a suitable method.",
        student_answer="Use a water bath and record results in a table.",
        mark_scheme_text="Method + table + observations",
        max_marks=3.0,
        subject="0610",
        paper_type="6",
    )

    assert "Alternative to Practical" in system_prompt
    assert "tables/graphs" in system_prompt
    assert "Paper 6 focus" in user_prompt


def test_drawing_prompt_adds_physics_subject_guidance():
    grader = _stub_grader()
    system_prompt, user_prompt = grader._build_drawing_prompt(
        question_text="Draw a ray diagram and label principal focus.",
        mark_scheme_text="Correct ray paths and focus label.",
        max_marks=2.0,
        subject="0625",
        paper_type="4",
    )

    assert "YOU MUST SEE THE IMAGE" in system_prompt
    assert "UNITS:" in system_prompt
    assert "a resistor drawn as a capacitor is wrong" in system_prompt
    assert 'mark scheme allows "ecf"' in system_prompt
    assert "Only award diagram marks for features clearly visible in the image" in user_prompt


def test_math_parser_interprets_caret_as_exponent_semantics():
    assert check_math_answer("2^3", "8")
    assert check_math_answer("2^{3}", "8")


def test_math_prompt_context_is_added_via_profile_registry():
    grader = _stub_grader()
    system_prompt, user_prompt = grader._build_text_prompt(
        question_id="1",
        question_text="Solve 2x = 10.",
        student_answer="x = 5",
        mark_scheme_text="M1 divide by 2\nA1 x = 5",
        max_marks=2.0,
        subject="0580",
        paper_type="2",
    )

    assert "Mathematics marking focus" in user_prompt
    assert "METHOD MARKS (M)" in system_prompt


@pytest.mark.parametrize(
    ("subject_code", "paper_type", "expected_phrase"),
    [
        ("9701", "4", "CHEMICAL FORMULAE"),
        ("9700", "4", "BIOLOGICAL TERMINOLOGY"),
        ("9702", "4", "UNITS:"),
        ("0607", "4", "METHOD MARKS (M)"),
        ("9231", "4", "METHOD MARKS (M)"),
        ("9093", "1", "READING COMPREHENSION"),
        ("9695", "1", "READING COMPREHENSION"),
        ("9609", "1", "DEFINITIONS: Require precise business/economics definitions."),
        ("9708", "1", "DEFINITIONS: Require precise business/economics definitions."),
    ],
)
def test_subject_prompt_registry_covers_requested_subject_code_families(subject_code: str, paper_type: str, expected_phrase: str):
    context = get_subject_prompt_context(subject_code, paper_type)

    assert context.applies is True
    assert expected_phrase in context.system_addendum
