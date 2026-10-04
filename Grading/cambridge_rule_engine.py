"""Deterministic Cambridge-style grading helpers for math and science practical responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import logging
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_MATH_SUBJECT_CODES = {
    "0580",
    "0607",
    "9709",
    "9231",
}

_SCIENCE_SUBJECT_CODES = {
    "0610",
    "0620",
    "0625",
    "9700",
    "9701",
    "9702",
}

_MATH_QUALIFIERS = {"cao", "dep", "eeo", "isw", "oe", "soi", "nfww"}

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

_UNIT_PATTERN = re.compile(
    r"\b(?:mm|cm|m|km|mg|g|kg|s|ms|m/s|cm/s|m/s2|n|pa|kpa|j|w|a|v|ohm|hz|mol|dm3|cm3|°c|c)\b",
    re.IGNORECASE,
)
_NUMERIC_TOLERANCE_DEFAULT = 0.02
_NUMERIC_TOLERANCE_STRICT = 0.005
_SCIENTIFIC_TOKEN_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[x×]\s*10\s*(?:\^|\*\*)\s*(-?\d+)",
    flags=re.IGNORECASE,
)
_FRACTION_TOKEN_PATTERN = re.compile(r"(?<!\d)(-?\d+)\s*/\s*(-?\d+)(?!\d)")
_DECIMAL_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z])(-?\d+(?:\.\d+)?(?:\(\d+\))?)(?![A-Za-z])")
_MATH_MARK_CODE_PATTERN = re.compile(r"\b(?:SC|FT|M|A|B)\s*[0-9]+(?:\.[0-9]+)?\b", re.IGNORECASE)
_BRACKETED_TRAILING_DIGITS_PATTERN = re.compile(r"\((\d+)\)\s*$")


@dataclass(slots=True)
class MathRuleToken:
    kind: str
    marks: float
    dep: bool = False
    ft: bool = False
    sc: bool = False
    qualifiers: List[str] = field(default_factory=list)
    raw: str = ""
    line: str = ""


@dataclass(slots=True)
class MathRuleSpec:
    tokens: List[MathRuleToken]
    qualifiers: List[str]
    mark_scheme_text: str
    has_structured_rules: bool


@dataclass(slots=True)
class ScienceRuleSpec:
    points: List[str]
    required_count: int
    ecf_allowed: bool
    expected_units: List[str]
    mark_scheme_text: str


@dataclass(slots=True)
class RuleGradeResult:
    marks: float
    method_award: float
    final_answer_award: float
    warnings: List[str] = field(default_factory=list)
    manual_review_required: bool = False
    feedback: str = ""
    parse_status: str = ""
    confidence: float = 0.0
    rule_type: str = ""


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(out):
        return float(default)
    return out


def _extract_numbers(text: str) -> List[float]:
    source = str(text or "")
    out: List[float] = []

    for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s*[x×]\s*10\s*(?:\^|\*\*)\s*(-?\d+)", source, flags=re.IGNORECASE):
        mantissa = _to_float(m.group(1), default=float("nan"))
        exponent = _to_float(m.group(2), default=float("nan"))
        if math.isfinite(mantissa) and math.isfinite(exponent):
            out.append(mantissa * (10 ** int(exponent)))

    for m in re.finditer(r"(?<!\d)(-?\d+)\s*/\s*(-?\d+)(?!\d)", source):
        try:
            out.append(float(Fraction(int(m.group(1)), int(m.group(2)))))
        except Exception:
            continue

    for m in re.finditer(r"(?<![A-Za-z])(-?\d+(?:\.\d+)?)(?![A-Za-z])", source):
        out.append(_to_float(m.group(1), default=float("nan")))

    deduped: List[float] = []
    for value in out:
        if not math.isfinite(value):
            continue
        if any(abs(value - existing) <= 1e-12 for existing in deduped):
            continue
        deduped.append(value)
    return deduped


def _extract_numeric_tokens(text: str) -> List[str]:
    source = str(text or "")
    spans: List[Tuple[int, int, str]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= existing_start or start >= existing_end) for existing_start, existing_end, _ in spans)

    for pattern in (_SCIENTIFIC_TOKEN_PATTERN, _FRACTION_TOKEN_PATTERN, _DECIMAL_TOKEN_PATTERN):
        for match in pattern.finditer(source):
            start, end = int(match.start()), int(match.end())
            if _overlaps(start, end):
                continue
            spans.append((start, end, str(match.group(0)).strip()))

    spans.sort(key=lambda item: item[0])
    return [token for _, _, token in spans]


def _normalize_numeric_token_text(token: str) -> str:
    text = str(token or "").strip()
    if not text:
        return ""
    return _BRACKETED_TRAILING_DIGITS_PATTERN.sub("", text).strip()


def _numeric_token_to_float(token: str) -> Optional[float]:
    text = _normalize_numeric_token_text(token)
    if not text:
        return None

    scientific = _SCIENTIFIC_TOKEN_PATTERN.fullmatch(text)
    if scientific:
        mantissa = _to_float(scientific.group(1), default=float("nan"))
        exponent = _to_float(scientific.group(2), default=float("nan"))
        if math.isfinite(mantissa) and math.isfinite(exponent):
            return mantissa * (10 ** int(exponent))
        return None

    fraction = _FRACTION_TOKEN_PATTERN.fullmatch(text)
    if fraction:
        try:
            return float(Fraction(int(fraction.group(1)), int(fraction.group(2))))
        except Exception:
            return None

    value = _to_float(text, default=float("nan"))
    if math.isfinite(value):
        return value
    return None


def _count_significant_figures(token: str) -> int:
    text = _normalize_numeric_token_text(token).lower()
    if not text:
        return 0

    scientific = _SCIENTIFIC_TOKEN_PATTERN.fullmatch(text)
    if scientific:
        text = scientific.group(1)

    if "/" in text:
        left, _, right = text.partition("/")
        return max(_count_significant_figures(left), _count_significant_figures(right))

    text = text.lstrip("+-")
    if not text:
        return 0

    if "." in text:
        digits = text.replace(".", "")
        digits = digits.lstrip("0")
        return len(digits)

    digits = text.lstrip("0").rstrip("0")
    return len(digits)


def _numeric_values_match(
    student_val: float,
    expected_val: float,
    expected_str: str,
    student_str: str = "",
) -> bool:
    """
    Checks if a student numerical answer matches the expected mark scheme
    value within an appropriate tolerance.

    The main tolerance is based on the expected mark-scheme precision.
    A student answer shown to only 1-2 significant figures is allowed a
    looser comparison so answers like 1.5 can still match 1.48, while
    1.50 remains strict.
    """
    if expected_val == 0:
        return abs(student_val) < 1e-9

    if math.isclose(student_val, expected_val, rel_tol=0.0, abs_tol=1e-12):
        return True

    normalized_expected = _normalize_numeric_token_text(expected_str)
    expected_sig_figs = _count_significant_figures(normalized_expected)
    normalized_student = _normalize_numeric_token_text(student_str)
    student_sig_figs = _count_significant_figures(normalized_student) if normalized_student else 0
    relative_diff = abs(student_val - expected_val) / abs(expected_val)

    if expected_sig_figs >= 3:
        if 0 < student_sig_figs <= 2:
            return relative_diff <= 0.02
        abs_tol = min(0.005 * abs(expected_val), 0.01)
        return abs(student_val - expected_val) <= abs_tol
    if expected_sig_figs == 2:
        return relative_diff <= 0.02
    return relative_diff <= 0.05


def _has_keyword_overlap(student_text: str, reference_text: str, min_hits: int = 1) -> bool:
    student_tokens = {
        token
        for token in re.findall(r"[a-z][a-z0-9\-]{2,}", student_text.lower())
        if token not in {"mark", "marks", "answer", "question", "method"}
    }
    if not student_tokens:
        return False

    reference_tokens = {
        token
        for token in re.findall(r"[a-z][a-z0-9\-]{2,}", reference_text.lower())
        if token not in {"mark", "marks", "answer", "question", "method", "cao", "dep", "oe", "eeo"}
    }
    if not reference_tokens:
        return False

    hits = len(student_tokens.intersection(reference_tokens))
    return hits >= int(max(1, min_hits))


def _extract_numeric_token_values(text: str) -> List[Tuple[str, float]]:
    pairs: List[Tuple[str, float]] = []
    for token in _extract_numeric_tokens(text):
        value = _numeric_token_to_float(token)
        if value is None:
            continue
        pairs.append((token, value))
    return pairs


def _extract_terminal_expected_numeric(text: str) -> Tuple[Optional[float], str]:
    cleaned = _strip_math_mark_codes(text)
    tokens = _extract_numeric_tokens(cleaned)
    if not tokens:
        return None, ""
    token = tokens[-1]
    value = _numeric_token_to_float(token)
    if value is None:
        return None, ""
    return value, token


def _remove_mark_scheme_artifacts(text: str) -> str:
    lines = str(text or "").splitlines()
    if len(lines) < 3:
        return str(text or "")

    def _prev_non_empty(index: int) -> str:
        for pos in range(index - 1, -1, -1):
            stripped = str(lines[pos] or "").strip()
            if stripped:
                return stripped
        return ""

    def _next_non_empty(index: int) -> str:
        for pos in range(index + 1, len(lines)):
            stripped = str(lines[pos] or "").strip()
            if stripped:
                return stripped
        return ""

    def _is_descriptive(text_value: str) -> bool:
        stripped = str(text_value or "").strip()
        if not stripped or re.fullmatch(r"[1-9]", stripped):
            return False
        return bool(re.search(r"[A-Za-z<>≤≥=+\-*/()%]", stripped))

    cleaned: List[str] = []
    for idx, line in enumerate(lines):
        stripped = str(line or "").strip()
        if re.fullmatch(r"[1-9]", stripped):
            prev_line = _prev_non_empty(idx)
            next_line = _next_non_empty(idx)
            if _is_descriptive(prev_line) and _is_descriptive(next_line):
                continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _strip_math_mark_codes(text: str) -> str:
    return _MATH_MARK_CODE_PATTERN.sub(" ", str(text or ""))


def parse_math_mark_scheme(mark_scheme_text: str) -> MathRuleSpec:
    text = str(mark_scheme_text or "")
    lines = [line.strip() for line in text.splitlines() if str(line).strip()]
    tokens: List[MathRuleToken] = []
    qualifiers_seen: set[str] = set()

    token_re = re.compile(r"^\s*(SC|FT|M|A|B)\s*([0-9]+(?:\.[0-9]+)?)?\b", re.IGNORECASE)
    for line in lines:
        low_line = line.lower()
        line_qualifiers = sorted({q for q in _MATH_QUALIFIERS if re.search(rf"\b{q}\b", low_line)})
        qualifiers_seen.update(line_qualifiers)
        match = token_re.search(line)
        if not match:
            continue
        kind = str(match.group(1) or "").upper()
        raw_token = str(match.group(0) or "")
        compact_token = re.sub(r"\s+", "", raw_token).upper()
        if re.fullmatch(r"(?:SC|FT|M|A|B)[1-9]", compact_token):
            marks = 1.0
        else:
            marks = _to_float(match.group(2) or 1.0, default=1.0)
        start, end = int(match.start()), int(match.end())
        window = low_line[max(0, start - 24): min(len(low_line), end + 36)]
        dep = "dep" in window or "dependent" in window
        ft = kind == "FT" or "follow-through" in low_line or "follow through" in low_line
        sc = kind == "SC" or "special case" in low_line
        token = MathRuleToken(
            kind=kind,
            marks=max(0.0, marks),
            dep=dep,
            ft=ft,
            sc=sc,
            qualifiers=list(line_qualifiers),
            raw=match.group(0),
            line=line,
        )
        tokens.append(token)

    has_rules = bool(tokens)
    return MathRuleSpec(
        tokens=tokens,
        qualifiers=sorted(qualifiers_seen),
        mark_scheme_text=text,
        has_structured_rules=has_rules,
    )


def grade_math_response(student_answer: str, question_text: str, spec: MathRuleSpec, max_marks: float) -> RuleGradeResult:
    student_text = _clean_text(student_answer)
    q_text = _clean_text(question_text)
    max_marks = max(0.0, _to_float(max_marks, default=0.0))

    if not student_text:
        return RuleGradeResult(
            marks=0.0,
            method_award=0.0,
            final_answer_award=0.0,
            warnings=["blank_answer"],
            feedback="No answer provided.",
            parse_status="blank",
            confidence=1.0,
            rule_type="math",
        )

    if not spec.has_structured_rules:
        return RuleGradeResult(
            marks=0.0,
            method_award=0.0,
            final_answer_award=0.0,
            warnings=["math_rule_tokens_missing"],
            manual_review_required=False,
            feedback="Structured math mark tokens not present; rule engine skipped.",
            parse_status="no_structured_tokens",
            confidence=0.0,
            rule_type="math",
        )

    student_low = student_text.lower()
    student_numbers = _extract_numbers(student_text)
    student_numeric_pairs = _extract_numeric_token_values(student_text)

    method_evidence = bool(
        re.search(r"(?:=|therefore|hence|so\b|working|substitut|factor|expand|solve|gradient|intersect)", student_low)
    ) or len(student_numbers) >= 2 or "\n" in student_answer

    method_award = 0.0
    final_award = 0.0
    warnings: List[str] = []
    any_numeric_step_match = False

    for token in spec.tokens:
        line_low = str(token.line or "").lower()
        expected_value, expected_str = _extract_terminal_expected_numeric(token.line)
        token_numeric_match = False
        if expected_value is not None:
            token_numeric_match = any(
                _numeric_values_match(student_value, expected_value, expected_str, student_token)
                for student_token, student_value in student_numeric_pairs
            )
            if token_numeric_match:
                any_numeric_step_match = True
        token_keyword_match = _has_keyword_overlap(student_text, token.line)
        grant = False

        if token.kind == "M":
            if expected_value is not None:
                grant = token_numeric_match
            else:
                grant = method_evidence or token_keyword_match
            if grant:
                method_award += token.marks

        elif token.kind == "A":
            if token.dep and method_award <= 0.0:
                warnings.append("dep_not_satisfied")
                grant = False
            else:
                grant = token_numeric_match or token_keyword_match
            if "cao" in token.qualifiers and not token_numeric_match:
                grant = False
            if grant:
                final_award += token.marks

        elif token.kind == "B":
            grant = token_numeric_match or token_keyword_match
            if "cao" in token.qualifiers and not token_numeric_match:
                grant = False
            if grant:
                final_award += token.marks

        elif token.kind == "FT":
            grant = method_evidence and bool(student_numbers)
            if grant:
                method_award += token.marks
                warnings.append("follow_through_awarded")

        elif token.kind == "SC":
            sc_match = False
            if "for" in line_low:
                condition = line_low.split("for", 1)[1].strip()
                if condition and (condition in student_low or _has_keyword_overlap(student_text, condition)):
                    sc_match = True
            if not sc_match:
                sc_match = token_numeric_match or token_keyword_match
            if sc_match:
                final_award += token.marks

        if grant and "isw" in token.qualifiers:
            warnings.append("isw_ignored")
        if grant and "oe" in token.qualifiers:
            warnings.append("or_equivalent_applied")

    awarded = max(0.0, min(max_marks, method_award + final_award))
    ambiguous = False

    if not any_numeric_step_match and method_evidence and awarded <= 0.0:
        ambiguous = True
        warnings.append("ambiguous_method_without_credit")

    if "nfww" in spec.qualifiers and any_numeric_step_match:
        warnings.append("nfww_present")

    confidence = 0.35
    if any_numeric_step_match:
        confidence += 0.35
    if method_evidence:
        confidence += 0.15
    if awarded > 0.0:
        confidence += 0.10
    if ambiguous:
        confidence -= 0.20
    confidence = max(0.0, min(1.0, confidence))

    return RuleGradeResult(
        marks=awarded,
        method_award=max(0.0, min(max_marks, method_award)),
        final_answer_award=max(0.0, min(max_marks, final_award)),
        warnings=list(dict.fromkeys(warnings)),
        manual_review_required=ambiguous,
        feedback="Rule-engine math interpretation applied." if awarded > 0.0 else "No deterministic math mark points matched.",
        parse_status="math_rule_scored",
        confidence=confidence,
        rule_type="math",
    )


def _split_points(text: str) -> List[str]:
    lines = [re.sub(r"^[\-•*\d\)\.\s]+", "", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) >= 2:
        return lines
    fallback = [seg.strip() for seg in re.split(r"[;\n]+", str(text or "")) if seg.strip()]
    return fallback


def _extract_required_count(question_text: str) -> int:
    text = str(question_text or "").lower()
    m_num = re.search(
        r"\b(?:state|give|name|describe|suggest|identify|write)\s+(\d+)\b",
        text,
    )
    if m_num:
        return max(0, int(m_num.group(1)))

    m_word = re.search(
        r"\b(?:state|give|name|describe|suggest|identify|write)\s+(one|two|three|four|five|six)\b",
        text,
    )
    if m_word:
        return _NUMBER_WORDS.get(m_word.group(1), 0)
    return 0


def parse_science_practical_mark_scheme(mark_scheme_text: str, question_text: str) -> ScienceRuleSpec:
    text = _remove_mark_scheme_artifacts(str(mark_scheme_text or ""))
    points = _split_points(text)
    required_count = _extract_required_count(question_text)
    expected_units = sorted({unit.lower() for unit in _UNIT_PATTERN.findall(text)})
    ecf_allowed = bool(re.search(r"\b(?:ecf|error carried forward|follow[- ]through|follow through|ft)\b", text, re.IGNORECASE))

    return ScienceRuleSpec(
        points=points,
        required_count=max(0, int(required_count)),
        ecf_allowed=ecf_allowed,
        expected_units=expected_units,
        mark_scheme_text=text,
    )


def _split_student_clauses(student_answer: str) -> List[str]:
    chunks = [seg.strip() for seg in re.split(r"[\n;]+", str(student_answer or ""))]
    if len(chunks) <= 1:
        chunks = [seg.strip() for seg in re.split(r"(?<=[\.!?])\s+", str(student_answer or ""))]
    return [chunk for chunk in chunks if chunk]


def _has_contradiction(text: str) -> bool:
    low = str(text or "").lower()
    contradiction_pairs = [
        ("increase", "decrease"),
        ("increases", "decreases"),
        ("acidic", "alkaline"),
        ("gain", "lose"),
        ("higher", "lower"),
    ]
    for left, right in contradiction_pairs:
        if left in low and right in low:
            return True
    return False


def grade_science_practical_response(student_answer: str, question_text: str, spec: ScienceRuleSpec, max_marks: float) -> RuleGradeResult:
    student_text = _clean_text(student_answer)
    max_marks = max(0.0, _to_float(max_marks, default=0.0))

    if not student_text:
        return RuleGradeResult(
            marks=0.0,
            method_award=0.0,
            final_answer_award=0.0,
            warnings=["blank_answer"],
            feedback="No answer provided.",
            parse_status="blank",
            confidence=1.0,
            rule_type="science_practical",
        )

    if not spec.points:
        return RuleGradeResult(
            marks=0.0,
            method_award=0.0,
            final_answer_award=0.0,
            warnings=["science_rule_points_missing"],
            manual_review_required=False,
            feedback="No structured practical points detected; rule engine skipped.",
            parse_status="no_structured_points",
            confidence=0.0,
            rule_type="science_practical",
        )

    clauses = _split_student_clauses(student_answer)
    required = int(spec.required_count or 0)
    if required > 0:
        considered = clauses[:required]
    else:
        considered = list(clauses)

    warnings: List[str] = []
    if required > 0 and len(considered) < required:
        warnings.append("missing_required_responses")

    if _has_contradiction(" ".join(considered)):
        warnings.append("contradictory_response_detected")

    unmatched_points = list(spec.points)
    matched_points = 0

    for clause in considered:
        matched_index: Optional[int] = None
        for idx, point in enumerate(unmatched_points):
            if _has_keyword_overlap(clause, point):
                matched_index = idx
                break
        if matched_index is not None:
            matched_points += 1
            unmatched_points.pop(matched_index)

    base_target = max(1, len(spec.points))
    marks_per_point = max_marks / float(base_target)
    awarded = float(matched_points) * marks_per_point

    if spec.ecf_allowed and awarded <= 0.0 and _extract_numbers(student_text):
        awarded += min(marks_per_point, max_marks)
        warnings.append("ecf_applied")

    student_units = {unit.lower() for unit in _UNIT_PATTERN.findall(student_text)}
    if spec.expected_units and student_units and student_units.intersection(set(spec.expected_units)):
        awarded += min(0.5, marks_per_point * 0.5)
        warnings.append("unit_credit_applied")

    awarded = max(0.0, min(max_marks, awarded))

    confidence = 0.35 + (0.45 * (float(matched_points) / float(base_target)))
    if "contradictory_response_detected" in warnings:
        confidence -= 0.20
    confidence = max(0.0, min(1.0, confidence))

    manual_review_required = "contradictory_response_detected" in warnings and awarded > 0.0

    return RuleGradeResult(
        marks=awarded,
        method_award=0.0,
        final_answer_award=awarded,
        warnings=list(dict.fromkeys(warnings)),
        manual_review_required=manual_review_required,
        feedback="Science practical rule interpretation applied.",
        parse_status="science_practical_rule_scored",
        confidence=confidence,
        rule_type="science_practical",
    )


def apply_cambridge_rule_grading(
    *,
    subject_code: str,
    paper_number: str,
    question_text: str,
    student_answer: str,
    mark_scheme_text: str,
    max_marks: float,
) -> Optional[RuleGradeResult]:
    subject = str(subject_code or "").strip()
    paper = str(paper_number or "").strip()
    mark_scheme = str(mark_scheme_text or "")

    if not mark_scheme.strip():
        return None

    math_like = subject in _MATH_SUBJECT_CODES or bool(re.search(r"\b(?:M|A|B|SC|FT)\s*\d", mark_scheme, re.IGNORECASE))
    if math_like:
        spec = parse_math_mark_scheme(mark_scheme)
        if spec.has_structured_rules:
            return grade_math_response(student_answer, question_text, spec, max_marks)
        return None

    science_practical = subject in _SCIENCE_SUBJECT_CODES and (
        paper.startswith("6")
        or bool(re.search(r"\b(?:practical|table|graph|apparatus|observation|gradient|unit)\b", str(question_text or ""), re.IGNORECASE))
    )
    if science_practical:
        spec = parse_science_practical_mark_scheme(mark_scheme, question_text)
        if spec.points:
            return grade_science_practical_response(student_answer, question_text, spec, max_marks)

    return None
