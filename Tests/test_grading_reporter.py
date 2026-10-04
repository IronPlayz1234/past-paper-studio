from pathlib import Path

from Grading.grading_reporter import write_grading_report


def test_write_grading_report_creates_markdown_with_metadata_and_question_sections(tmp_path: Path):
    results = {
        "total_marks": 6.0,
        "earned_marks": 4.0,
        "percentage": 66.666,
        "auto_graded_marks": 4.0,
        "auto_graded_total_marks": 5.0,
        "pending_manual_marks": 1.0,
        "pending_manual_count": 1,
        "grading_errors": ["1 drawing question requires manual review."],
        "question_results": {
            "1": {
                "grading_source": "ai",
                "earned_marks": 2.0,
                "total_marks": 3.0,
                "manual_review_required": False,
                "manual_review_status": "",
                "parse_status": "final_mark_line",
                "model_used": "meta-llama/llama-4-scout-17b-16e-instruct",
                "ai_error": "",
                "warnings": ["parse:final_mark_line"],
                "student_answer": "Sample student answer",
                "mark_scheme_text": "Sample mark scheme",
                "feedback": "Point-by-point reasoning",
                "raw_response": "Reasoning...\nFINAL MARK: 2",
            }
        },
    }

    report_path = write_grading_report(
        project_root=str(tmp_path),
        subject_code="0620",
        paper_number="4",
        year="2025",
        results=results,
        source_label="loaded/downloaded mark scheme",
        subject_name="Chemistry",
        past_paper_code="0620_s25_qp_41",
    )

    path = Path(report_path)
    content = path.read_text(encoding="utf-8")

    assert path.exists()
    assert path.parent == tmp_path
    assert path.name.startswith("Chemistry 0620_s25_qp_41 Done ")
    assert path.suffix == ".md"
    assert "# Auto-Grade Report" in content
    assert "- Subject Name: Chemistry" in content
    assert "- Subject Code: 0620" in content
    assert "- Past Paper Code: 0620_s25_qp_41" in content
    assert "- Paper Number: 4" in content
    assert "### Q1" in content
    assert "Point-by-point reasoning" in content
    assert "FINAL MARK: 2" in content


def test_write_grading_report_includes_threshold_section_when_available(tmp_path: Path):
    results = {
        "total_marks": 80.0,
        "earned_marks": 63.0,
        "percentage": 78.75,
        "auto_graded_marks": 63.0,
        "auto_graded_total_marks": 80.0,
        "pending_manual_marks": 0.0,
        "pending_manual_count": 0,
        "question_results": {},
        "threshold_interpretation": {
            "available": True,
            "candidate_score": 63,
            "max_raw_mark": 80,
            "threshold_rows": [
                {"grade": "A*", "mark": 67},
                {"grade": "A", "mark": 59},
                {"grade": "B", "mark": 51},
                {"grade": "C", "mark": 44},
            ],
            "estimated_grade": "A",
            "next_grade_label": "A*",
            "marks_to_next": 4,
        },
    }

    report_path = write_grading_report(
        project_root=str(tmp_path),
        subject_code="0580",
        paper_number="4",
        year="2023",
        results=results,
        source_label="loaded/downloaded mark scheme",
        subject_name="Mathematics",
        past_paper_code="0580_s23_qp_42",
    )
    content = Path(report_path).read_text(encoding="utf-8")

    assert "## Grade Thresholds" in content
    assert "- Candidate Score: 63 / 80" in content
    assert "- A*: 67" in content
    assert "- A: 59" in content
    assert "- Estimated Grade: A" in content
    assert "- Marks to A*: 4" in content


def test_write_grading_report_includes_threshold_unavailable_line(tmp_path: Path):
    results = {
        "total_marks": 80.0,
        "earned_marks": 63.0,
        "percentage": 78.75,
        "auto_graded_marks": 63.0,
        "auto_graded_total_marks": 80.0,
        "pending_manual_marks": 0.0,
        "pending_manual_count": 0,
        "question_results": {},
        "threshold_interpretation": {
            "available": False,
            "candidate_score": 63,
            "total_mark": 80,
            "message": "Grade threshold data unavailable for this paper/session: Exact component row was not found in threshold table.",
        },
    }

    report_path = write_grading_report(
        project_root=str(tmp_path),
        subject_code="0580",
        paper_number="4",
        year="2023",
        results=results,
        source_label="loaded/downloaded mark scheme",
        subject_name="Mathematics",
        past_paper_code="0580_s23_qp_42",
    )
    content = Path(report_path).read_text(encoding="utf-8")

    assert "## Grade Thresholds" in content
    assert "- Candidate Score: 63 / 80" in content
    assert "Grade threshold data unavailable for this paper/session" in content


def test_write_grading_report_prefers_leaf_awarded_and_max_marks_fields(tmp_path: Path):
    results = {
        "total_marks": 3.0,
        "earned_marks": 2.0,
        "percentage": 66.666,
        "auto_graded_marks": 2.0,
        "auto_graded_total_marks": 3.0,
        "pending_manual_marks": 0.0,
        "pending_manual_count": 0,
        "question_results": {
            "2(b)(i)": {
                "question_id": "2(b)(i)",
                "question_text": "Suggest the pH of aqueous calcium hydroxide.",
                "grading_source": "ai",
                "awarded_marks": 1.0,
                "max_marks": 1.0,
                "earned_marks": 9.0,
                "total_marks": 12.0,
                "mark_scheme_text": "7 < pH <= 12",
                "explanation": "Student answer falls in the accepted range.",
                "raw_response": "FINAL MARK: 1",
                "max_marks_source": "mark_scheme_row",
                "mark_scheme_source": "mark_scheme_pdf",
                "mapping_strategy": "direct",
                "fallback_used": False,
            }
        },
    }

    report_path = write_grading_report(
        project_root=str(tmp_path),
        subject_code="0620",
        paper_number="4",
        year="2022",
        results=results,
        source_label="loaded/downloaded mark scheme",
        subject_name="Chemistry",
        past_paper_code="0620_s22_qp_42",
    )
    content = Path(report_path).read_text(encoding="utf-8")

    assert "### Q2(b)(i)" in content
    assert "- Marks: 1 / 1" in content
    assert "Suggest the pH of aqueous calcium hydroxide." in content
    assert "Student answer falls in the accepted range." in content
