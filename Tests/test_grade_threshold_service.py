from Grading import grade_threshold_service as svc


def _sample_threshold_text() -> str:
    return "\n".join(
        [
            "Cambridge International",
            "Grade thresholds June 2023",
            "Syllabus 0580",
            "Maximum raw mark",
            "available",
            "A*",
            "A",
            "B",
            "C",
            "D",
            "E",
            "Component 41",
            "80",
            "62",
            "55",
            "48",
            "41",
            "35",
            "29",
            "Component 42",
            "80",
            "67",
            "59",
            "51",
            "44",
            "37",
            "31",
        ]
    )


def _interpret(*, score: float, component: str) -> dict:
    component_digits = "".join(ch for ch in str(component) if ch.isdigit())[:2] or "42"
    if len(component_digits) == 1:
        component_digits = f"0{component_digits}"
    return svc.interpret_grade_thresholds(
        subject_code="0580",
        year="2023",
        series="MJ",
        component=component_digits,
        candidate_score=score,
        total_mark=80,
        grade_threshold_url="https://example.com/0580_s23_gt.pdf",
        question_url=f"https://example.com/0580_s23_qp_{component_digits}.pdf",
        mark_scheme_url=f"https://example.com/0580_s23_ms_{component_digits}.pdf",
    )


def test_grade_threshold_exact_boundary(monkeypatch):
    monkeypatch.setattr(svc, "_download_threshold_text", lambda _url, timeout_seconds=18.0: (_sample_threshold_text(), ""))

    result = _interpret(score=59, component="42")

    assert result["available"] is True
    assert result["estimated_grade"] == "A"
    assert result["thresholds"]["A*"] == 67
    assert result["thresholds"]["A"] == 59
    assert result["next_grade_label"] == "A*"
    assert result["marks_to_next"] == 8


def test_grade_threshold_one_mark_below_boundary(monkeypatch):
    monkeypatch.setattr(svc, "_download_threshold_text", lambda _url, timeout_seconds=18.0: (_sample_threshold_text(), ""))

    result = _interpret(score=58, component="42")

    assert result["available"] is True
    assert result["estimated_grade"] == "B"
    assert result["next_grade_label"] == "A"
    assert result["marks_to_next"] == 1


def test_grade_threshold_above_top_boundary_has_zero_distance(monkeypatch):
    monkeypatch.setattr(svc, "_download_threshold_text", lambda _url, timeout_seconds=18.0: (_sample_threshold_text(), ""))

    result = _interpret(score=75, component="42")

    assert result["available"] is True
    assert result["estimated_grade"] == "A*"
    assert result["next_grade_label"] == ""
    assert result["marks_to_next"] == 0


def test_grade_threshold_missing_file_or_component_returns_unavailable(monkeypatch):
    monkeypatch.setattr(svc, "_download_threshold_text", lambda _url, timeout_seconds=18.0: ("", "missing file"))
    missing_file = _interpret(score=59, component="42")
    assert missing_file["available"] is False
    assert "missing file" in missing_file["message"].lower()

    monkeypatch.setattr(svc, "_download_threshold_text", lambda _url, timeout_seconds=18.0: (_sample_threshold_text(), ""))
    missing_component = _interpret(score=59, component="99")
    assert missing_component["available"] is False
    assert "component row" in missing_component["message"].lower()


def test_grade_threshold_differs_across_components_same_session(monkeypatch):
    monkeypatch.setattr(svc, "_download_threshold_text", lambda _url, timeout_seconds=18.0: (_sample_threshold_text(), ""))

    comp_41 = _interpret(score=63, component="41")
    comp_42 = _interpret(score=63, component="42")

    assert comp_41["available"] is True
    assert comp_42["available"] is True
    assert comp_41["thresholds"]["A*"] == 62
    assert comp_42["thresholds"]["A*"] == 67
    assert comp_41["estimated_grade"] == "A*"
    assert comp_42["estimated_grade"] == "A"
