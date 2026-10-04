from Grading import math_paper_extractor as mpe


def test_extract_math_questions_from_grouped_lines(monkeypatch):
    lines = [
        "1 (a) Solve 2x + 4 = 10",
        "Working shown below",
        "2 Find the value of y",
        "Use your answer from part (a)",
    ]
    monkeypatch.setattr(mpe, "_extract_pdf_lines", lambda pdf_path, max_pages: list(lines))

    questions = mpe.extract_math_questions("dummy.pdf")
    assert "1" in questions
    assert "2" in questions
    assert "Solve 2x + 4 = 10" in questions["1"]
    assert "Find the value of y" in questions["2"]


def test_extract_math_mark_scheme_marks_and_expected_filter(monkeypatch):
    lines = [
        "1 M1 sets equation and A1 gets x = 3",
        "follow-through accepted",
        "2 [3] accept equivalent fraction form",
    ]
    monkeypatch.setattr(mpe, "_extract_pdf_lines", lambda pdf_path, max_pages: list(lines))

    result = mpe.extract_math_mark_scheme("dummy.pdf", expected_question_ids=["1"])
    assert list(result.keys()) == ["1"]
    assert result["1"]["marks"] == 2.0
    assert result["1"]["is_math_extracted"] is True
    assert "M1" in result["1"]["mark_scheme_text"]


def test_is_math_subject_code_covers_code_and_name():
    assert mpe.is_math_subject_code("0580", "")
    assert mpe.is_math_subject_code("", "International Mathematics")
    assert not mpe.is_math_subject_code("0620", "Chemistry")
