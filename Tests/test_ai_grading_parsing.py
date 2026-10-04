from pathlib import Path

from Grading.ai_config import AIConfig
from Grading.ai_grading import (
    UnifiedAIGrader,
    _parse_mark,
    _split_mark_scheme_points,
    check_math_answer,
    check_math_paper_answer,
    check_math_paper_answer_ai,
    get_answer_key,
    normalize_for_grading,
    preprocess_mark_scheme,
)


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


def test_parse_mark_clamps_to_total_marks():
    marks, status = _parse_mark("Reasoning\nFINAL MARK: 99", total_marks=4)
    assert status == "final_mark_line"
    assert marks == 4.0


def test_parse_mark_prefers_out_of_pattern_and_uses_numerator():
    marks, status = _parse_mark("The student deserves 2 out of 3 marks.", total_marks=4)
    assert status == "out_of_pattern"
    assert marks == 2.0


def test_parse_mark_prefers_award_pattern_when_final_mark_missing():
    marks, status = _parse_mark("Point checks complete. Awarded 2 marks.", total_marks=4)
    assert status == "award_pattern"
    assert marks == 2.0


def test_parse_mark_rounds_down_to_half_step_marks():
    marks, status = _parse_mark("Reasoning\nFINAL MARK: 2.9", total_marks=4)
    assert status == "final_mark_line"
    assert marks == 2.5


def test_grade_question_uses_award_pattern_when_final_mark_missing():
    grader = _stub_grader()
    grader._chat_text = lambda **kwargs: "Point checks complete. Awarded 2 marks."  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="1",
        question_text="Explain reactivity.",
        student_answer="Because collisions increase.",
        correct_answer="",
        mark_scheme_text="Any two valid points",
        max_marks=4,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "award_pattern"
    assert response.marks == 2.0
    assert response.raw_response == "Point checks complete. Awarded 2 marks."


def test_grade_drawing_uses_award_pattern_when_final_mark_missing(tmp_path: Path):
    grader = _stub_grader()
    grader._chat_image = lambda **kwargs: "Feature audit complete, 3 marks awarded."  # type: ignore[assignment]

    image_path = tmp_path / "drawing.png"
    image_path.write_bytes(b"not-a-real-png-but-exists")

    result = grader.grade_drawing(
        question_id="2",
        question_text="Draw and label an animal cell.",
        mark_scheme_text="Cell membrane labelled\nNucleus labelled",
        image_path=str(image_path),
        max_marks=4.0,
        subject="0610",
        paper_type="4",
    )

    assert result["manual_review_required"] is False
    assert result["parse_status"] == "award_pattern"
    assert float(result["marks"]) == 3.0


def test_grade_drawing_blocks_hallucinated_awards(tmp_path: Path):
    grader = _stub_grader()
    attempts = {"count": 0}

    def _fake_chat_image(**kwargs):
        attempts["count"] += 1
        return "I cannot see the image, assuming the student correctly completed it. FINAL MARK: 3"

    grader._chat_image = _fake_chat_image  # type: ignore[assignment]

    image_path = tmp_path / "drawing.png"
    image_path.write_bytes(b"not-a-real-png-but-exists")

    result = grader.grade_drawing(
        question_id="4(c)",
        question_text="Draw the dot-and-cross diagram.",
        mark_scheme_text="Dot-and-cross diagram showing all outer electrons",
        image_path=str(image_path),
        max_marks=3.0,
        subject="0620",
        paper_type="4",
    )

    assert result["marks"] == 0.0
    assert result["manual_review_required"] is True
    assert result["parse_status"] == "drawing_hallucination_blocked"
    assert "drawing_hallucination_blocked" in result["warnings"]
    assert result["retry_attempted"] is True
    assert result["retry_parse_status"] == "final_mark_line"
    assert "assuming the student correctly" in result["retry_raw_response"].lower()
    assert attempts["count"] == 2


def test_grade_drawing_retries_hallucinated_first_pass_and_keeps_verified_second_pass(tmp_path: Path):
    grader = _stub_grader()
    captured_prompts: list[str] = []
    responses = iter(
        [
            "I cannot see the image, assuming the student correctly completed it. FINAL MARK: 3",
            "I can clearly see the charges and electron arrangement in the image.\nFINAL MARK: 3",
        ]
    )

    def _fake_chat_image(**kwargs):
        captured_prompts.append(str(kwargs["user_prompt"]))
        return next(responses)

    grader._chat_image = _fake_chat_image  # type: ignore[assignment]

    image_path = tmp_path / "drawing.png"
    image_path.write_bytes(b"not-a-real-png-but-exists")

    result = grader.grade_drawing(
        question_id="4(d)",
        question_text="Complete the ionic dot-and-cross diagram.",
        mark_scheme_text="Charges shown and all electrons shown",
        image_path=str(image_path),
        max_marks=3.0,
        subject="0620",
        paper_type="4",
    )

    assert result["marks"] == 3.0
    assert result["manual_review_required"] is False
    assert result["parse_status"] == "final_mark_line"
    assert result["retry_attempted"] is True
    assert result["retry_parse_status"] == "final_mark_line"
    assert result["raw_response"].startswith("I can clearly see")
    assert "CRITICAL RETRY OVERRIDE" in captured_prompts[1]
    assert "image is attached and available" in captured_prompts[1]


def test_grade_drawing_does_not_block_legitimate_vision_language(tmp_path: Path):
    grader = _stub_grader()
    attempts = {"count": 0}

    def _fake_chat_image(**kwargs):
        attempts["count"] += 1
        return "The diagram appears to show 7 dots around chlorine.\nFINAL MARK: 2"

    grader._chat_image = _fake_chat_image  # type: ignore[assignment]

    image_path = tmp_path / "drawing.png"
    image_path.write_bytes(b"not-a-real-png-but-exists")

    result = grader.grade_drawing(
        question_id="4(c)",
        question_text="Draw the dot-and-cross diagram.",
        mark_scheme_text="Dot-and-cross diagram showing all outer electrons",
        image_path=str(image_path),
        max_marks=3.0,
        subject="0620",
        paper_type="4",
    )

    assert result["marks"] == 2.0
    assert result["manual_review_required"] is False
    assert result["parse_status"] == "final_mark_line"
    assert result["retry_attempted"] is False
    assert attempts["count"] == 1


def test_grade_drawing_keeps_visible_verified_response(tmp_path: Path):
    grader = _stub_grader()
    grader._chat_image = lambda **kwargs: "I can clearly see the labelled shared pair and lone pairs.\nFINAL MARK: 2"  # type: ignore[assignment]

    image_path = tmp_path / "drawing.png"
    image_path.write_bytes(b"not-a-real-png-but-exists")

    result = grader.grade_drawing(
        question_id="4(d)",
        question_text="Draw the displayed formula.",
        mark_scheme_text="Displayed formula with all atoms and bonds shown",
        image_path=str(image_path),
        max_marks=2.0,
        subject="0620",
        paper_type="4",
    )

    assert result["marks"] == 2.0
    assert result["manual_review_required"] is False
    assert result["parse_status"] == "final_mark_line"


def test_call_with_retries_uses_exponential_backoff_for_429(monkeypatch):
    grader = _stub_grader()
    grader.retry_delays_sec = ()
    grader.rpm_backoff_base_sec = 1.0
    grader.rpm_backoff_max_sec = 8.0
    grader.rpm_max_retries = 4
    grader._reconnect_client = lambda: None  # type: ignore[assignment]
    grader._wait_for_request_slot = lambda: None  # type: ignore[assignment]

    sleeps: list[float] = []
    monkeypatch.setattr("Grading.ai_grading.time.sleep", lambda seconds: sleeps.append(float(seconds)))

    attempts = {"count": 0}

    def _request():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("429 Too Many Requests")
        return "ok"

    result = grader._call_with_retries("groq_text_completion", _request)

    assert result == "ok"
    assert attempts["count"] == 3
    assert sleeps[:2] == [1.0, 2.0]


def test_text_prompt_includes_strict_inclusion_partial_credit_synonym_and_no_hallucination_rules():
    grader = _stub_grader()
    system_prompt, user_prompt = grader._build_text_prompt(
        question_id="5",
        question_text="Define isotopes.",
        student_answer="Same protons, different neutrons.",
        mark_scheme_text="Atoms of the same element with the same number of protons.",
        max_marks=1.0,
        subject="0620",
        paper_type="4",
    )

    assert "authoritative source of truth" in system_prompt
    assert "Strict inclusion rule" in system_prompt
    assert "Partial-credit rule" in system_prompt
    assert "Synonym rule" in system_prompt
    assert "No hallucinations" in system_prompt
    assert "'delocalised'/'delocalized' as valid for 'mobile' electrons" in system_prompt
    assert "Never require extra detail not written in the mark scheme point itself." in user_prompt
    assert "Evaluate independent clauses separately and add marks for correct clauses." in user_prompt
    assert "must be applied exactly as written" in user_prompt


def test_drawing_prompt_includes_visible_only_and_no_assumption_rules():
    grader = _stub_grader()
    system_prompt, _user_prompt = grader._build_drawing_prompt(
        question_text="Draw the bonding and label the shared pair.",
        mark_scheme_text="Shared pair shown and labelled.",
        max_marks=2.0,
        subject="0620",
        paper_type="4",
    )

    assert "grading a student drawing/diagram from an image" in system_prompt
    assert "Award marks only for explicit mark-scheme features visible in the image." in system_prompt
    assert "Do not infer hidden features." in system_prompt


def test_text_prompt_includes_ocr_tolerance_for_arabic_profile():
    grader = _stub_grader()
    _system_prompt, user_prompt = grader._build_text_prompt(
        question_id="1",
        question_text="اقرا النص ثم اجب.",
        student_answer="الجواب صحيح",
        mark_scheme_text="Any valid correct response",
        max_marks=1.0,
        subject="0508",
        paper_type="4",
    )

    assert "Profile guidance" in user_prompt
    assert "Question Text" in user_prompt


def test_grade_question_short_circuits_when_mark_scheme_is_missing():
    grader = _stub_grader()
    grader._chat_text = lambda **kwargs: (_ for _ in ()).throw(AssertionError("AI should not be called"))  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="1",
        question_text="State the product.",
        student_answer="Mg",
        correct_answer="",
        mark_scheme_text="[See Mark Scheme]",
        max_marks=1,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "missing_mark_scheme"
    assert response.marks == 0.0
    assert "missing_mark_scheme" in response.warnings
    assert response.manual_review_required is True
    assert "Manual review required" in response.feedback


def test_grade_question_blocks_text_only_answer_when_diagram_is_required():
    grader = _stub_grader()
    grader._chat_text = lambda **kwargs: (_ for _ in ()).throw(AssertionError("AI should not be called"))  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="5(b)",
        question_text="Draw the structure of the monomer.",
        student_answer=(
            "The monomer is a dioic acid with two fully displayed carboxylic acid groups and "
            "a long prose explanation that keeps going so it is clearly not a diagram at all."
        ),
        correct_answer="",
        mark_scheme_text="diagram of dioic acid showing two fully displayed carboxylic acid groups",
        max_marks=2,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "diagram_required_text_only"
    assert response.marks == 0.0
    assert response.manual_review_required is True
    assert "diagram_required_text_only" in response.warnings


def test_grade_question_allows_drawing_placeholder_for_diagram_required_question():
    grader = _stub_grader()
    grader._chat_text = lambda **kwargs: "Visible diagram features match.\nFINAL MARK: 2"  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="5(c)",
        question_text="Draw the structure of the monomer.",
        student_answer="[Drawing submitted]",
        correct_answer="",
        mark_scheme_text="diagram of dioic acid showing two fully displayed carboxylic acid groups",
        max_marks=2,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "final_mark_line"
    assert response.marks == 2.0
    assert response.manual_review_required is False


def test_grade_question_does_not_block_short_formula_for_diagram_required_question():
    grader = _stub_grader()
    grader._chat_text = lambda **kwargs: "Formula alone is insufficient but AI path was reached.\nFINAL MARK: 0"  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="5(d)",
        question_text="Draw the structure of magnesium oxide.",
        student_answer="Mg",
        correct_answer="",
        mark_scheme_text="diagram of magnesium oxide showing all ions",
        max_marks=1,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "final_mark_line"
    assert response.manual_review_required is False


def test_grade_question_appends_method_chain_override_for_answer_only_response():
    grader = _stub_grader()
    captured = {}

    def _fake_chat_text(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return "FINAL MARK: 1"

    grader._chat_text = _fake_chat_text  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="4(b)",
        question_text="Determine the molecular formula.",
        student_answer="molecular formula = S₂F₁₀",
        correct_answer="",
        mark_scheme_text=(
            "Method 1\n"
            "M1 sulfur working\n"
            "M2 divide by ratio\n"
            "M3 S2F10"
        ),
        max_marks=3,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "final_mark_line"
    assert "CRITICAL OVERRIDE" in captured["user_prompt"]
    assert "Award ONLY the final answer mark" in captured["user_prompt"]


def test_grade_question_does_not_append_method_chain_override_when_working_is_present():
    grader = _stub_grader()
    captured = {}

    def _fake_chat_text(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return "FINAL MARK: 3"

    grader._chat_text = _fake_chat_text  # type: ignore[assignment]

    response = grader.grade_question(
        question_id="4(b)",
        question_text="Determine the molecular formula.",
        student_answer="25.2 / 32 = 0.7875\n74.8 / 19 = 3.94\nratio = 1 : 5, so S₂F₁₀",
        correct_answer="",
        mark_scheme_text=(
            "Method 1\n"
            "M1 sulfur working\n"
            "M2 divide by ratio\n"
            "M3 S2F10"
        ),
        max_marks=3,
        subject="0620",
        paper_type="4",
    )

    assert response.parse_status == "final_mark_line"
    assert "CRITICAL OVERRIDE" not in captured["user_prompt"]


def test_fallback_keyword_grade_accepts_delocalised_as_mobile_synonym():
    marks, feedback = UnifiedAIGrader._fallback_keyword_grade(
        question_id="2",
        question_text="Why does graphite conduct electricity?",
        student_answer="Graphite has delocalised electrons that can move.",
        mark_scheme_text="Contains mobile electrons.",
        max_marks=1.0,
    )

    assert marks == 1.0
    assert "matched" in feedback.lower()


def test_fallback_keyword_grade_awards_additive_partial_for_independent_clauses():
    marks, _feedback = UnifiedAIGrader._fallback_keyword_grade(
        question_id="3",
        question_text="Define isotopes.",
        student_answer="They have the same number of protons but different neutrons.",
        mark_scheme_text="same number of protons and same number of electrons",
        max_marks=2.0,
    )

    assert marks == 1.0


def test_mark_scheme_preprocessing_handles_unicode_bullets_and_mark_codes():
    text = "‣ B1 correct point\n◦ M1 valid method\n⁃ A1 accurate answer\n∙ FT follow through\n· final note"
    cleaned = preprocess_mark_scheme(text)
    points = _split_mark_scheme_points(cleaned)

    assert cleaned.count("\n") >= 4
    assert points[0].startswith("B1")
    assert any(point.startswith("M1") for point in points)
    assert any("FT" in point for point in points)


def test_normalize_for_grading_fixes_common_ocr_math_and_science_symbols():
    normalized = normalize_for_grading("x² + H₂O + Fe²⁺ − 6×7 ÷ 2")

    assert "x^2" in normalized
    assert "H2O" in normalized
    assert "Fe^2+" in normalized
    assert "-" in normalized
    assert "*" in normalized
    assert "/" in normalized


def test_math_prompt_includes_method_accuracy_follow_through_instruction():
    grader = _stub_grader()
    system_prompt, _user_prompt = grader._build_text_prompt(
        question_id="1",
        question_text="Solve for x.",
        student_answer="x = 4",
        mark_scheme_text="M1 for method, A1 for answer",
        max_marks=2.0,
        subject="9709",
        paper_type="1",
    )

    assert "Method Marks (M)" in system_prompt
    assert "Accuracy Marks (A)" in system_prompt
    assert "Follow-Through marks (FT)" in system_prompt
    assert "structured multi-line workings" in system_prompt


def test_non_math_prompt_excludes_method_accuracy_follow_through_instruction():
    grader = _stub_grader()
    system_prompt, _user_prompt = grader._build_text_prompt(
        question_id="2",
        question_text="Define ionic bonding.",
        student_answer="Electrostatic attraction between ions.",
        mark_scheme_text="Attraction between oppositely charged ions",
        max_marks=1.0,
        subject="0620",
        paper_type="4",
    )

    assert "Method Marks (M)" not in system_prompt
    assert "Accuracy Marks (A)" not in system_prompt
    assert "Follow-Through marks (FT)" not in system_prompt


def test_get_answer_key_returns_normalized_schema():
    key = get_answer_key("0580", "2", "2023")

    assert isinstance(key, dict)
    assert "1" in key
    assert key["1"]["answer"] == "42"
    assert key["1"]["marks"] == 1


def test_check_math_paper_answer_returns_compatibility_fields_with_use_ai_false():
    result = check_math_paper_answer(
        user_answers={"1": "42", "2(a)": "3"},
        answer_key={
            "1": {"answer": "42", "marks": 1},
            "2a": {"answer": "3", "marks": 2},
        },
        use_ai=False,
        subject_code="0580",
        paper_number="2",
        year="2025",
    )

    assert result["ai_used"] is False
    assert result["ai_applied_count"] == 0
    assert result["api_calls_made"] == 0
    assert "model_answers" in result
    assert "question_results" in result
    assert set(result["question_results"].keys()) == {"1", "2(a)"}
    row = result["question_results"]["2(a)"]
    assert {"student_answer", "correct_answer", "total_marks", "earned_marks", "grading_source"} <= set(row.keys())


def test_check_math_answer_keeps_legacy_symbol_normalization_behavior():
    assert check_math_answer("6 × 7", "42") is True
    assert check_math_answer("84÷2", "42") is True


def test_check_math_paper_answer_ai_honors_question_filter(monkeypatch):
    captured_questions = []

    def _fake_grade_paper_with_ai(**kwargs):
        captured_questions.extend(kwargs.get("questions", []))
        return type(
            "_Result",
            (),
            {
                "total_questions": len(captured_questions),
                "awarded_marks": 0.0,
                "max_marks": 0.0,
                "percentage": 0.0,
                "question_results": {},
                "model_answers": {},
                "grading_errors": [],
                "api_calls_made": 0,
                "subject_code": "0580",
                "paper_number": "4",
                "year": "2025",
                "ai_quota_exhausted": False,
            },
        )()

    monkeypatch.setattr("Grading.ai_grading.is_ai_enabled", lambda: True)
    monkeypatch.setattr("Grading.ai_grading.grade_paper_with_ai", _fake_grade_paper_with_ai)

    check_math_paper_answer_ai(
        user_answers={"1": "a", "2": "b"},
        answer_key={
            "1": {"answer": "a", "marks": 1},
            "2": {"answer": "b", "marks": 1},
        },
        subject_code="0580",
        paper_number="4",
        year="2025",
        question_filter={"2"},
    )

    assert [q["id"] for q in captured_questions] == ["2"]


def test_ai_config_load_from_env_strips_surrounding_quotes(monkeypatch):
    monkeypatch.setattr("Grading.ai_config._env_path", lambda: "/tmp/nonexistent-env-for-test")
    monkeypatch.setattr("Grading.ai_config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("GROQ_API_KEY", '"gsk_test_key"')
    monkeypatch.setenv("GROQ_TEXT_MODEL", "'meta-llama/llama-4-scout-17b-16e-instruct'")
    monkeypatch.setenv("GROQ_VISION_MODEL", '"meta-llama/llama-4-scout-17b-16e-instruct"')

    cfg = AIConfig.load_from_env()

    assert cfg.api_key == "gsk_test_key"
    assert cfg.text_model == "meta-llama/llama-4-scout-17b-16e-instruct"
    assert cfg.vision_model == "meta-llama/llama-4-scout-17b-16e-instruct"
