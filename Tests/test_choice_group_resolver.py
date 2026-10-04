from Grading.paper_choice_resolver import parse_choice_structure, resolve_choice_selection


def test_choice_resolver_english_one_from_four_fallback_group():
    question_ids = ["1", "2", "3", "4"]
    question_texts = {
        "1": "Choose one of the following writing tasks and write your answer.",
        "2": "Choose one of the following writing tasks and write your answer.",
        "3": "Choose one of the following writing tasks and write your answer.",
        "4": "Choose one of the following writing tasks and write your answer.",
    }
    structure = parse_choice_structure("", question_ids, question_texts)
    resolution = resolve_choice_selection(
        structure=structure,
        answers={"1": "", "2": "Narrative response", "3": "", "4": ""},
        question_marks={qid: 40.0 for qid in question_ids},
        explicit_selection={},
    )

    assert "2" in resolution.active_question_ids
    assert "1" in resolution.skipped_question_ids
    assert "3" in resolution.skipped_question_ids
    assert "4" in resolution.skipped_question_ids


def test_choice_structure_no_warning_for_normal_compulsory_paper_without_choice_signals():
    structure = parse_choice_structure(
        "",
        ["1", "2", "3"],
        {"1": "Question 1", "2": "Question 2", "3": "Question 3"},
    )

    assert structure.groups == []
    assert structure.warnings == []


def test_choice_resolver_either_or_pattern():
    question_ids = ["5", "6"]
    structure = parse_choice_structure(
        "Answer either Question 5 or Question 6.",
        question_ids,
        {"5": "Question 5", "6": "Question 6"},
    )
    resolution = resolve_choice_selection(
        structure=structure,
        answers={"5": "", "6": "chosen"},
        question_marks={"5": 25.0, "6": 25.0},
        explicit_selection={},
    )

    assert resolution.active_question_ids == ["6"]
    assert resolution.skipped_question_ids == ["5"]


def test_choice_resolver_one_from_each_section_pattern():
    question_ids = ["1", "2", "3", "4"]
    structure = parse_choice_structure(
        "Answer one question from each section.",
        question_ids,
        {
            "1": "Section A Question 1",
            "2": "Section A Question 2",
            "3": "Section B Question 3",
            "4": "Section B Question 4",
        },
    )
    resolution = resolve_choice_selection(
        structure=structure,
        answers={"1": "attempted", "2": "", "3": "", "4": "attempted"},
        question_marks={qid: 10.0 for qid in question_ids},
        explicit_selection={},
    )

    assert set(resolution.active_question_ids) == {"1", "4"}
    assert set(resolution.skipped_question_ids) == {"2", "3"}


def test_choice_resolver_compulsory_plus_choice_pattern():
    question_ids = ["1", "2", "3", "4", "5"]
    structure = parse_choice_structure(
        "Answer compulsory question 1 and three questions from Section B.",
        question_ids,
        {
            "1": "Compulsory data question",
            "2": "Section B Question 2",
            "3": "Section B Question 3",
            "4": "Section B Question 4",
            "5": "Section B Question 5",
        },
    )
    resolution = resolve_choice_selection(
        structure=structure,
        answers={"1": "yes", "2": "yes", "3": "yes", "4": "yes", "5": ""},
        question_marks={qid: 10.0 for qid in question_ids},
        explicit_selection={},
    )

    assert "1" in resolution.active_question_ids
    assert "5" in resolution.skipped_question_ids


def test_choice_resolver_over_selected_group_flags_manual_review():
    question_ids = ["1", "2"]
    structure = parse_choice_structure(
        "Answer either Question 1 or Question 2.",
        question_ids,
        {"1": "Section A", "2": "Section A"},
    )
    resolution = resolve_choice_selection(
        structure=structure,
        answers={"1": "attempt", "2": "attempt"},
        question_marks={"1": 10.0, "2": 10.0},
        explicit_selection={},
    )

    assert resolution.manual_review_required_ids
    assert any(token.startswith("over_selected:") for token in resolution.warnings)


def test_choice_structure_warns_only_when_choice_signals_exist_but_structure_is_unresolved():
    structure = parse_choice_structure(
        "Answer one question from each section.",
        ["1", "2", "3"],
        {"1": "Question 1", "2": "Question 2", "3": "Question 3"},
    )

    assert structure.groups == []
    assert "choice_structure_not_detected" in structure.warnings
