import pytest

pytest.importorskip("PySide6")

import Core.exam_mode as exam_mode
from Core.exam_mode import ExtractionResult, MarkSchemeParser, QuestionTextExtractor
from Utils.question_id_mapper import QuestionIDMapper, QuestionLeaf, normalize_question_id_canonical
from Utils.unified_question_extractor import UnifiedQuestionExtractor


def test_ocr_fallback_triggers_for_low_confidence():
    extractor = QuestionTextExtractor()
    result = ExtractionResult(
        question_ids_leaf=["1"],
        confidence_summary={"marker_acceptance": 0.2, "overall": 0.3},
    )
    assert extractor._should_use_ocr_fallback(result) is True


def test_ocr_fallback_skips_when_confident():
    extractor = QuestionTextExtractor()
    result = ExtractionResult(
        question_ids_leaf=["1", "1(a)", "1(a)(i)", "2"],
        confidence_summary={"marker_acceptance": 0.9, "overall": 0.85},
    )
    assert extractor._should_use_ocr_fallback(result) is False


def test_question_extractor_prevents_main_question_bleed_from_next_marker():
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 86.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "1 (0.03)^2",
            "text": "1 (0.03)^2",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 95.0,
            "y": 158.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "2 15",
            "text": "2 15",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 122.0,
            "y": 176.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "Calculate 1/15",
            "text": "Calculate 1/15",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)

    assert "1" in result.question_texts
    assert result.question_texts["1"].strip() == "(0.03)^2"
    assert "/15" not in result.question_texts["1"]
    assert "2" in result.question_texts


def test_parse_written_mark_scheme_supports_numeric_hierarchical_and_inline_rows():
    ms_text = """
    Question Answer Marks
    1 0.0009 1
    2(a) 7 1
    2(a)(i) correct method shown [1]
    3 gradient = 2 2
    """

    parsed = MarkSchemeParser.parse_written_mark_scheme(
        ms_text,
        expected_question_ids=["1", "2(a)", "2(a)(i)", "3"],
    )

    assert parsed["1"]["answer"] == "0.0009"
    assert parsed["1"]["marks"] == 1.0
    assert parsed["2(a)"]["answer"] == "7"
    assert parsed["2(a)"]["marks"] == 1.0
    assert "correct method shown" in parsed["2(a)(i)"]["answer"]
    assert parsed["2(a)(i)"]["marks"] == 1.0
    assert parsed["3"]["answer"] == "gradient = 2"
    assert parsed["3"]["marks"] == 2.0


def test_parse_written_mark_scheme_splits_ocr_merged_lines_and_ignores_decimal_noise_as_marks():
    merged_text = "1 0.0009 1 2 15 1 3 0.45 1"
    parsed_merged = MarkSchemeParser.parse_written_mark_scheme(
        merged_text,
        expected_question_ids=["1", "2", "3"],
    )

    assert parsed_merged["1"]["answer"] == "0.0009"
    assert parsed_merged["1"]["marks"] == 1.0
    assert parsed_merged["2"]["answer"] == "15"
    assert parsed_merged["2"]["marks"] == 1.0
    assert parsed_merged["3"]["answer"] == "0.45"
    assert parsed_merged["3"]["marks"] == 1.0

    decimal_only = MarkSchemeParser.parse_written_mark_scheme("4 0.45", expected_question_ids=["4"])
    assert decimal_only["4"]["answer"] == "0.45"
    assert decimal_only["4"]["marks"] == 1.0


def test_parse_written_mark_scheme_handles_cambridge_multiline_rows_and_answer_numbers():
    ms_text = """
    Question
    Answer
    Marks
    2(b)(i)
    7 < pH <= 12
    1
    4(c)
    N with 1 dot-cross bonding pair with each Cl
    2 non-bonding dots for N
    6 non-bonding crosses for Cl
    3
    6(a)(i)
    3
    1
    """

    parsed = MarkSchemeParser.parse_written_mark_scheme(
        ms_text,
        expected_question_ids=["2(b)(i)", "4(c)", "6(a)(i)"],
    )

    assert parsed["2(b)(i)"]["answer"] == "7 < pH <= 12"
    assert parsed["2(b)(i)"]["marks"] == 1.0
    assert "2 non-bonding dots for N" in parsed["4(c)"]["answer"]
    assert parsed["4(c)"]["marks"] == 3.0
    assert parsed["6(a)(i)"]["answer"] == "3"
    assert parsed["6(a)(i)"]["marks"] == 1.0


def test_parse_written_mark_scheme_strips_rogue_interior_digit_artifact_lines():
    ms_text = """
    Question
    Answer
    Marks
    2(c)(iv)
    (aqueous) sodium hydroxide
    1
    white ppt
    insoluble / remains in excess
    3
    """

    parsed = MarkSchemeParser.parse_written_mark_scheme(
        ms_text,
        expected_question_ids=["2(c)(iv)"],
    )

    assert parsed["2(c)(iv)"]["answer"] == "(aqueous) sodium hydroxide\nwhite ppt\ninsoluble / remains in excess"
    assert parsed["2(c)(iv)"]["marks"] == 3.0


def test_question_paper_mark_validation_prefers_question_total_on_any_mismatch(caplog):
    with caplog.at_level("WARNING", logger="Core.exam_mode"):
        validated = exam_mode._apply_question_paper_mark_validation(
            {"2(c)(iv)": {"answer": "white ppt", "mark_scheme_text": "white ppt", "marks": 2.0}},
            {"2(c)(iv)": 3.0},
        )

    assert validated["2(c)(iv)"]["marks"] == 3.0
    assert validated["2(c)(iv)"]["max_marks_source"] == "question_paper_hint"
    assert "Using question paper total." in caplog.text


def test_question_id_normalization_accepts_legacy_and_bracketed_forms():
    assert normalize_question_id_canonical("Q2bi") == "2(b)(i)"
    assert normalize_question_id_canonical("2bi") == "2(b)(i)"
    assert normalize_question_id_canonical("2(b)(i)") == "2(b)(i)"


def test_strict_leaf_mapping_uses_question_paper_hint_when_mark_scheme_row_has_no_marks():
    mapper = QuestionIDMapper()
    mapping = mapper.generate_mapping(["4(c)"], ["4(c)"], question_order=["4(c)"])
    expanded = mapper.expand_answer_key(
        answer_key={"4(c)": {"answer": "diagram points", "mark_scheme_text": "diagram points", "marks": 0.0}},
        mapping=mapping,
        question_marks={"4(c)": 3.0},
        policy="strict_leaf",
    )

    assert expanded["4(c)"]["marks"] == 3.0
    assert expanded["4(c)"]["max_marks_source"] == "question_paper_hint"
    assert expanded["4(c)"]["manual_review_required"] is False


def test_question_extractor_captures_terminal_mark_hints_without_leaking_to_text():
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 84.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "1(a) State two uses of limestone. [3]",
            "text": "1(a) State two uses of limestone. [3]",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)
    assert "1(a)" in result.question_ids_leaf
    assert result.question_mark_hints["1(a)"] == 3.0
    assert "[3]" not in result.question_texts["1(a)"]


def test_question_extractor_keeps_text_when_no_mark_hint_present():
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 84.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "2(a) Explain why the reaction is exothermic.",
            "text": "2(a) Explain why the reaction is exothermic.",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)
    assert "2(a)" in result.question_ids_leaf
    assert result.question_mark_hints == {}
    assert "exothermic" in result.question_texts["2(a)"].lower()


def test_unified_extractor_uses_mark_hints_instead_of_default_one_mark():
    class _DummyWrittenExtractor:
        def extract_with_structure(self, _pdf_path):
            return ExtractionResult(
                question_ids_leaf=["1(a)"],
                question_texts={"1(a)": "State two uses."},
                question_mark_hints={"1(a)": 3.0},
                question_pages={"1(a)": 1},
                question_items=[
                    QuestionLeaf(
                        canonical_id="1(a)",
                        display_id="1(a)",
                        main=1,
                        part="a",
                        subpart=None,
                        page=1,
                        text="State two uses.",
                    )
                ],
            )

    extractor = UnifiedQuestionExtractor(written_extractor=_DummyWrittenExtractor())
    result = extractor.extract_questions(
        pdf_path=None,
        subject_code="0620",
        paper_number="4",
        exam_year=2025,
        mode="WRITTEN_ONLY",
        default_marks=1.0,
        expected_mcq_count=40,
    )
    assert result.question_marks["1(a)"] == 3.0
    assert result.question_mark_hints["1(a)"] == 3.0


def test_question_extractor_prefers_part_markers_over_main_marker_detection():
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 84.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "1(a) Calculate the speed of the car.",
            "text": "1(a) Calculate the speed of the car.",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 112.0,
            "y": 145.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "(b) Explain your answer.",
            "text": "(b) Explain your answer.",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 84.0,
            "y": 178.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "2(a)(i) State one reason.",
            "text": "2(a)(i) State one reason.",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 118.0,
            "y": 202.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "(ii) Give one advantage.",
            "text": "(ii) Give one advantage.",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)

    assert "1(a)" in result.question_ids_leaf
    assert "1(b)" in result.question_ids_leaf
    assert "2(a)(i)" in result.question_ids_leaf
    assert "2(a)(ii)" in result.question_ids_leaf
    assert "1" not in result.question_ids_leaf


def test_question_extractor_prefers_higher_quality_candidate_even_with_lower_count():
    extractor = QuestionTextExtractor()
    current = ExtractionResult(
        question_ids_leaf=[str(i) for i in range(1, 13)],
        confidence_summary={"marker_acceptance": 0.34, "overall": 0.52},
    )
    challenger = ExtractionResult(
        question_ids_leaf=[str(i) for i in range(1, 12)],
        confidence_summary={"marker_acceptance": 0.72, "overall": 0.68},
    )

    assert extractor._prefer_candidate(current, challenger) is True


def test_question_extractor_keeps_current_when_challenger_loses_too_much_coverage():
    extractor = QuestionTextExtractor()
    current = ExtractionResult(
        question_ids_leaf=[str(i) for i in range(1, 16)],
        confidence_summary={"marker_acceptance": 0.66, "overall": 0.70},
    )
    challenger = ExtractionResult(
        question_ids_leaf=[str(i) for i in range(1, 6)],
        confidence_summary={"marker_acceptance": 0.80, "overall": 0.76},
    )

    assert extractor._prefer_candidate(current, challenger) is False


@pytest.mark.parametrize(
    ("ocr_marker", "expected_first"),
    [
        ("(i) first subpart", "1(a)(i)"),
        ("(1) first subpart", "1(a)(i)"),
        ("(l) first subpart", "1(a)(i)"),
        ("a(i) first subpart", "1(a)(i)"),
        ("a (i) first subpart", "1(a)(i)"),
    ],
)
def test_question_extractor_recovers_first_subpart_from_common_ocr_variants(ocr_marker, expected_first):
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 84.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "1(a) Setup statement",
            "text": "1(a) Setup statement",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 110.0,
            "y": 145.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": ocr_marker,
            "text": ocr_marker,
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 120.0,
            "y": 170.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "(ii) second subpart",
            "text": "(ii) second subpart",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)
    assert expected_first in result.question_ids_leaf
    assert "1(a)(ii)" in result.question_ids_leaf


def test_collect_page_tokens_from_ocr_data_relaxes_confidence_floor_when_strict_pass_is_empty():
    extractor = QuestionTextExtractor()
    data = {
        "text": ["1(a) State one use of limestone."],
        "conf": [9.0],
        "left": [168],
        "top": [240],
        "width": [180],
        "height": [18],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
    }

    tokens = extractor._collect_page_tokens_from_ocr_data(
        data,
        scale=2.0,
        page_num=0,
        page_w=595.0,
        page_h=842.0,
        conf_floor=15.0,
    )

    assert len(tokens) == 1
    assert tokens[0]["text"] == "1(a) State one use of limestone."
    assert tokens[0]["ocr_confidence"] == pytest.approx(9.0)


def test_collect_page_tokens_from_ocr_raster_dedupes_same_line_and_keeps_better_variant(monkeypatch):
    extractor = QuestionTextExtractor()

    class _Pixmap:
        width = 1
        height = 1
        samples = b"\x00\x00\x00"

    class _Page:
        def get_pixmap(self, matrix, alpha=False):
            return _Pixmap()

    monkeypatch.setattr(
        QuestionTextExtractor,
        "_build_ocr_image_variants",
        lambda self, _img, include_autocontrast: [
            ("base", object(), 15.0),
            ("binary", object(), 8.0),
        ],
    )
    monkeypatch.setattr(exam_mode, "ocr_image_to_data", lambda *_args, **_kwargs: {"text": ["ignored"]})

    variant_calls = {"count": 0}

    def _fake_collect(self, _data, *, scale, page_num, page_w, page_h, conf_floor):
        variant_calls["count"] += 1
        common = {
            "page": page_num,
            "x": 84.0,
            "y": 120.0,
            "page_w": page_w,
            "page_h": page_h,
            "font_size": 10.0,
        }
        if variant_calls["count"] == 1:
            return [
                {
                    **common,
                    "raw": "1 a Set up",
                    "text": "1 a Set up",
                    "ocr_confidence": 48.0,
                }
            ]
        return [
            {
                **common,
                "x": 84.4,
                "y": 120.2,
                "raw": "1 a Setup statement",
                "text": "1 a Setup statement",
                "ocr_confidence": 91.0,
            }
        ]

    monkeypatch.setattr(QuestionTextExtractor, "_collect_page_tokens_from_ocr_data", _fake_collect)

    tokens = extractor._collect_page_tokens_from_ocr_raster(
        _Page(),
        page_num=0,
        page_w=595.0,
        page_h=842.0,
        scales=(2.0,),
        include_autocontrast=True,
    )

    assert len(tokens) == 1
    assert tokens[0]["text"] == "1 a Setup statement"


def test_question_extractor_recovers_loose_ocr_part_marker_without_parentheses():
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 84.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "1 a State one use of limestone.",
            "text": "1 a State one use of limestone.",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 112.0,
            "y": 146.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "(b) Explain why it is added to the furnace.",
            "text": "(b) Explain why it is added to the furnace.",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)

    assert "1(a)" in result.question_ids_leaf
    assert "1(b)" in result.question_ids_leaf
    assert "1" not in result.question_ids_leaf


def test_question_extractor_does_not_treat_main_question_article_as_loose_part_marker():
    extractor = QuestionTextExtractor()
    tokens = [
        {
            "page": 0,
            "x": 84.0,
            "y": 120.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "1 A car accelerates uniformly.",
            "text": "1 A car accelerates uniformly.",
            "font_size": 10.0,
        },
        {
            "page": 0,
            "x": 112.0,
            "y": 146.0,
            "page_w": 595.0,
            "page_h": 842.0,
            "raw": "Calculate its speed after 5 s.",
            "text": "Calculate its speed after 5 s.",
            "font_size": 10.0,
        },
    ]

    result = extractor._parse_tokens(tokens)

    assert "1" in result.question_ids_leaf
    assert "1(a)" not in result.question_ids_leaf
