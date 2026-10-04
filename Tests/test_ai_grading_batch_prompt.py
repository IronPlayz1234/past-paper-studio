from Grading.ai_config import AIConfig
from Grading.ai_grading import GradingResponse, UnifiedAIGrader


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


def test_grade_paper_loops_question_by_question_and_preserves_mark_scheme_text():
    grader = _stub_grader()

    calls = []

    def _fake_grade_question(**kwargs):
        calls.append(kwargs)
        qid = str(kwargs.get("question_id", ""))
        awarded = 1.0 if qid == "1" else 0.0
        return GradingResponse(
            marks=awarded,
            feedback=f"graded {qid}",
            method_award=awarded,
            final_answer_award=awarded,
            is_partial_credit=False,
            warnings=[],
            model_used=grader.config.text_model,
            model_fallback_used=False,
            raw_response=f"Reasoning for {qid}\nFINAL MARK: {int(awarded)}",
            parse_status="final_mark_line",
            error=None,
        )

    grader.grade_question = _fake_grade_question  # type: ignore[assignment]

    result = grader.grade_paper(
        questions=[
            {
                "id": "1",
                "text": "State the element.",
                "answer": "Argon",
                "mark_scheme_text": "Argon",
                "marks": 1,
            },
            {
                "id": "2",
                "text": "Explain reactivity trend.",
                "answer": "Detailed explanation",
                "mark_scheme_text": "Any valid explanation",
                "marks": 2,
            },
        ],
        student_answers={"1": "argon", "2": "wrong answer"},
        subject_code="0620",
        paper_number="4",
        year="2024",
    )

    assert result.api_calls_made == 2
    assert result.question_results["1"].marks == 1.0
    assert result.question_results["2"].marks == 0.0
    assert [call["question_id"] for call in calls] == ["1", "2"]
    assert calls[0]["mark_scheme_text"] == "Argon"
    assert calls[1]["mark_scheme_text"] == "Any valid explanation"


def test_grade_paper_continues_after_single_question_exception():
    grader = _stub_grader()
    calls = []

    def _fake_grade_question(**kwargs):
        qid = str(kwargs.get("question_id", ""))
        calls.append(qid)
        if qid == "1":
            raise RuntimeError("timed out while grading question 1")
        return GradingResponse(
            marks=1.0,
            feedback=f"graded {qid}",
            method_award=1.0,
            final_answer_award=1.0,
            is_partial_credit=False,
            warnings=[],
            model_used=grader.config.text_model,
            model_fallback_used=False,
            raw_response=f"Reasoning for {qid}\nFINAL MARK: 1",
            parse_status="final_mark_line",
            error=None,
        )

    grader.grade_question = _fake_grade_question  # type: ignore[assignment]

    result = grader.grade_paper(
        questions=[
            {"id": "1", "text": "Q1", "answer": "", "mark_scheme_text": "point", "marks": 1},
            {"id": "2", "text": "Q2", "answer": "", "mark_scheme_text": "point", "marks": 1},
        ],
        student_answers={"1": "a", "2": "b"},
        subject_code="0620",
        paper_number="4",
        year="2024",
    )

    assert calls == ["1", "2"]
    assert result.question_results["1"].parse_status == "manager_exception"
    assert result.question_results["2"].parse_status == "final_mark_line"
    assert result.question_results["2"].marks == 1.0


def test_grade_paper_budget_warning_includes_error_type_breakdown():
    grader = _stub_grader()

    def _fake_grade_question(**kwargs):
        qid = str(kwargs.get("question_id", ""))
        if qid == "1":
            return GradingResponse(marks=0.0, feedback="fallback", error="429 Too Many Requests")
        if qid == "2":
            return GradingResponse(marks=0.0, feedback="fallback", error="401 Unauthorized")
        return GradingResponse(marks=1.0, feedback="ok")

    grader.grade_question = _fake_grade_question  # type: ignore[assignment]

    result = grader.grade_paper(
        questions=[
            {"id": "1", "text": "Q1", "answer": "", "mark_scheme_text": "point", "marks": 1},
            {"id": "2", "text": "Q2", "answer": "", "mark_scheme_text": "point", "marks": 1},
            {"id": "3", "text": "Q3", "answer": "", "mark_scheme_text": "point", "marks": 1},
        ],
        student_answers={"1": "a", "2": "b", "3": "c"},
        subject_code="0620",
        paper_number="4",
        year="2024",
        max_calls=2,
    )

    budget_errors = [err for err in result.grading_errors if "AI call budget reached" in err]
    assert budget_errors
    budget_message = budget_errors[0]
    assert "429=1" in budget_message
    assert "401=1" in budget_message
    assert "local_exception=0" in budget_message
