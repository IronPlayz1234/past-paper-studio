"""
Unified AI Grading Module
Supports grading for MCQ, Math, Sciences, and Written responses.

Uses Groq chat completion APIs for text and image grading.
"""

from __future__ import annotations

import base64
import gc
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from Core.runtime_tuning import ai_grading_batch_size, maybe_collect_garbage
from Grading.ai_config import AIConfig, get_ai_config, is_ai_enabled
from Grading.subject_prompt_registry import get_subject_prompt_context
from Core.paper_mode_router import resolve_mode
from Grading.cambridge_rule_engine import apply_cambridge_rule_grading
from Grading.subject_grading_profiles import get_subject_grading_profile, get_subject_profile_key
from Data.user_documentation import groq_setup_instructions_plain
from Utils.question_id_mapper import normalize_question_id_canonical, format_question_display

try:
    from Core import pdf_service as fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except Exception:
    fitz = None  # type: ignore[assignment]
    FITZ_AVAILABLE = False

try:
    from groq import Groq
except Exception:  # pragma: no cover - exercised in environments without groq installed
    class Groq:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "The 'groq' Python package is required. Install dependencies from requirements.txt.\n\n"
                f"{groq_setup_instructions_plain()}"
            )


# ---------------------------------------------------------------------------
# Debug and Error Helpers
# ---------------------------------------------------------------------------

_GRADING_DEBUG = str(os.getenv("GRADING_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}
_FINAL_MARK_PATTERN = re.compile(r"FINAL\s*MARK\s*:\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_OUT_OF_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(?:out of|/)\s*(-?\d+(?:\.\d+)?)\s*marks?",
    re.IGNORECASE,
)
_AWARD_PATTERN = re.compile(
    r"(?:"
    r"(?:award(?:ed)?|give|given)\s+(-?\d+(?:\.\d+)?)\s*marks?"
    r"|"
    r"(-?\d+(?:\.\d+)?)\s*marks?\s+awarded"
    r")",
    re.IGNORECASE,
)
_TOKEN_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
_RATE_LIMIT_HINTS = (
    "429",
    "resource_exhausted",
    "quota exceeded",
    "quota_exceeded",
    "quota",
    "rate limit",
    "rate-limit",
    "insufficient_quota",
    "credits",
)
_AUTH_HINTS = (
    "401",
    "unauthorized",
    "authentication",
    "invalid api key",
    "invalid_api_key",
    "api key invalid",
    "permission denied",
)
_TIMEOUT_HINTS = (
    "timeout",
    "timed out",
    "read timed out",
    "connect timeout",
    "deadline exceeded",
)
_ERROR_CAUSE_ORDER = ("rate_limit_429", "auth_401", "timeout", "local_exception")
_TOKEN_SYNONYM_MAP = {
    "delocalised": "electron_mobility_term",
    "delocalized": "electron_mobility_term",
    "mobile": "electron_mobility_term",
    "mobility": "electron_mobility_term",
}
_FALLBACK_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "there",
    "to",
    "using",
    "was",
    "were",
    "with",
    "same",
    "number",
    "different",
}
_MARK_SCHEME_MISSING_TOKENS = {
    "",
    "[see mark scheme]",
    "see mark scheme",
    "[no mark scheme text provided]",
    "no mark scheme text provided",
    "no mark scheme text available",
    "[manual review required]",
}
# These phrases indicate the AI explicitly admits it cannot see the image
# and is inferring or assuming rather than observing.
# Deliberately narrow - only catch explicit admissions of blindness.
_DRAWING_HALLUCINATION_PHRASES: list[str] = [
    "cannot see the image",
    "cannot see the diagram",
    "cannot view the image",
    "cannot view the diagram",
    "image is not provided",
    "image is not visible",
    "image was not provided",
    "no image provided",
    "no image is provided",
    "image not provided",
    "not able to see the image",
    "not able to view the image",
    "image is not available",
    "image not available",
    "image not included",
    "the image isn't available",
    "the image isn't visible",
    "the image is not present",
    "without seeing the image",
    "without viewing the image",
    "i cannot see",
    "i am unable to see",
    "i'm unable to see",
    "i cannot view",
    "unable to view the image",
    "unable to see the image",
    "no visual",
    "no image has been",
    "assuming the student correctly",
    "assuming the drawing is correct",
    "assuming it is correct",
    "assuming the diagram is correct",
    "assuming the student has correctly",
    "we will proceed based on standard knowledge",
    "based on standard knowledge",
    "based on what a correct",
    "rely on standard",
    "must assume",
    "have to assume",
    "forced to assume",
]
_DRAWING_VISIBILITY_RETRY_APPEND = (
    "\n\nCRITICAL RETRY OVERRIDE: The image is attached and available to you. "
    "Do not say the image is missing, unavailable, or not visible. "
    "Do not assume correctness from chemistry knowledge or context. "
    "Grade only the features you can actually verify from the image. "
    "If a feature is unclear, say which visible feature is unclear and award only the marks "
    "for the features you can verify. "
    "After your reasoning, output exactly one final line: FINAL MARK: <number>."
)
_DIAGRAM_REQUIRED_KEYWORDS: list[str] = [
    "diagram of",
    "diagram showing",
    "draw ",
    "drawing of",
    "drawn diagram",
    "fully displayed",
    "show all atoms",
    "show all of the atoms",
    "show all bonds",
    "show all of the bonds",
    "structural formula",
    "displayed formula",
    "dot-and-cross",
    "dot and cross",
    "complete the structure",
    "complete the diagram",
]
_STUDENT_STRUCTURAL_CHARS: str = "—─–=→−↔⟶⟷"
_SUPERSCRIPT_TRANSLATION = str.maketrans(
    {
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
        "⁺": "+",
        "⁻": "-",
        "⁽": "(",
        "⁾": ")",
    }
)
_SUBSCRIPT_TRANSLATION = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "₊": "+",
        "₋": "-",
        "₍": "(",
        "₎": ")",
    }
)
_UNICODE_BULLET_PATTERN = re.compile(r"^[‣◦⁃∙·•●◉○◆■▪▫▸▹►▶]+\s*", re.MULTILINE)
_SUPERSCRIPT_RUN_PATTERN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾]+")


def _dbg(message: str) -> None:
    if _GRADING_DEBUG:
        print(message)


def _is_quota_error_message(message: str) -> bool:
    return _classify_ai_error_message(message) == "rate_limit_429"


def _classify_ai_error_message(message: str) -> str:
    text = str(message or "").lower()
    if not text:
        return "local_exception"
    if any(hint in text for hint in _RATE_LIMIT_HINTS):
        return "rate_limit_429"
    if any(hint in text for hint in _AUTH_HINTS):
        return "auth_401"
    if any(hint in text for hint in _TIMEOUT_HINTS):
        return "timeout"
    return "local_exception"


def _new_error_cause_counts() -> Dict[str, int]:
    return {key: 0 for key in _ERROR_CAUSE_ORDER}


def _record_error_cause(error_counts: Dict[str, int], message: str) -> str:
    cause = _classify_ai_error_message(message)
    if cause not in error_counts:
        error_counts[cause] = 0
    error_counts[cause] += 1
    return cause


def _format_error_cause_breakdown(error_counts: Dict[str, int]) -> str:
    return (
        f"429={int(error_counts.get('rate_limit_429', 0))}, "
        f"401={int(error_counts.get('auth_401', 0))}, "
        f"timeout={int(error_counts.get('timeout', 0))}, "
        f"local_exception={int(error_counts.get('local_exception', 0))}"
    )


def _extract_error_cause_from_warnings(warnings: List[str]) -> Optional[str]:
    for warning in warnings or []:
        token = str(warning or "").strip().lower()
        if not token.startswith("ai_error_type:"):
            continue
        cause = token.split(":", 1)[1].strip()
        if cause in _ERROR_CAUSE_ORDER:
            return cause
    return None


def _strip_internal_reasoning(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _extract_reasoning_without_final_mark(text: str) -> str:
    cleaned = _strip_internal_reasoning(text)
    return _FINAL_MARK_PATTERN.sub("", cleaned).strip()


def _parse_mark(text: str, total_marks: float) -> tuple[float, str]:
    def _clamp_half_step(value: float) -> float:
        clamped = max(0.0, min(float(total_marks), float(value)))
        return math.floor((clamped * 2.0) + 1e-9) / 2.0

    cleaned = _strip_internal_reasoning(text)
    match = _FINAL_MARK_PATTERN.search(cleaned)
    if match:
        try:
            parsed = float(match.group(1))
        except Exception:
            parsed = 0.0
        return _clamp_half_step(parsed), "final_mark_line"

    out_of_match = _OUT_OF_PATTERN.search(cleaned)
    if out_of_match:
        try:
            parsed = float(out_of_match.group(1))
        except Exception:
            parsed = 0.0
        return _clamp_half_step(parsed), "out_of_pattern"

    award_match = _AWARD_PATTERN.search(cleaned)
    if award_match:
        try:
            parsed = float(next((group for group in award_match.groups() if group), "0"))
        except Exception:
            parsed = 0.0
        return _clamp_half_step(parsed), "award_pattern"

    numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if numbers:
        try:
            parsed = float(numbers[-1])
        except Exception:
            parsed = 0.0
        return _clamp_half_step(parsed), "fallback_last_number"

    return 0.0, "unparseable"


def _is_blank_answer_text(value: Any) -> bool:
    return not str(value or "").strip()


def _mark_scheme_is_missing(mark_scheme_text: str) -> bool:
    lowered = str(mark_scheme_text or "").strip().lower()
    return lowered in _MARK_SCHEME_MISSING_TOKENS


def _drawing_response_is_hallucinated(raw_response: str) -> bool:
    """
    Returns True ONLY when the AI explicitly admits it cannot see the image
    and is assuming or inferring correctness instead of observing it.

    Deliberately narrow - normal vision description language like
    "appears to show", "seems to have", "likely correct" is NOT flagged
    because those phrases are appropriate when genuinely describing an image.
    Only explicit admissions of blindness are caught.
    """
    lowered = str(raw_response or "").lower()
    return any(phrase in lowered for phrase in _DRAWING_HALLUCINATION_PHRASES)


def _build_drawing_visibility_retry_prompt(user_prompt: str) -> str:
    return f"{str(user_prompt or '').rstrip()}{_DRAWING_VISIBILITY_RETRY_APPEND}"


def _mark_scheme_requires_diagram(mark_scheme_text: str) -> bool:
    lowered = str(mark_scheme_text or "").lower()
    return any(kw in lowered for kw in _DIAGRAM_REQUIRED_KEYWORDS)


def _student_answer_is_text_only(student_answer: str) -> bool:
    text = str(student_answer or "").strip()
    if not text:
        return True
    if "[drawing" in text.lower():
        return False
    if any(c in text for c in _STUDENT_STRUCTURAL_CHARS):
        return False
    return len(text) > 120


def _mark_scheme_has_method_chain(mark_scheme_text: str) -> bool:
    """
    Returns True if the mark scheme explicitly contains sequential method
    marks (M1, M2, M3...) indicating that working must be shown for each step.
    """
    text = str(mark_scheme_text or "")
    method_marks = re.findall(r"\bM[1-9]\b", text, flags=re.IGNORECASE)
    unique = {mark.upper() for mark in method_marks}
    return len(unique) >= 2


def _student_answer_shows_no_working(student_answer: str) -> bool:
    """
    Returns True if the student answer is a short final response with no
    evidence of calculation steps, equations, or intermediate values.
    """
    text = str(student_answer or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 2:
        return False

    combined = " ".join(lines)
    if len(combined) > 80:
        return False

    lowered = combined.lower()
    symbol_indicators = [
        "/",
        "×",
        "*",
        "÷",
        "→",
        "∴",
    ]
    if any(indicator in lowered for indicator in symbol_indicators):
        return False

    if re.search(r"\b(?:mol|moles|ratio|therefore|step|method|so)\b", lowered):
        return False

    if "=" in combined:
        label_only_assignment = re.fullmatch(
            r"[A-Za-z][A-Za-z\s]*=\s*[A-Za-z0-9().+\-^_/\u2070-\u209F]+",
            combined,
        )
        if label_only_assignment is None:
            return False

    standalone_numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])", combined)
    if len(standalone_numbers) > 1:
        return False

    return True


def _split_mark_scheme_points(mark_scheme_text: str) -> List[str]:
    text = str(mark_scheme_text or "").strip()
    if not text:
        return []

    points = [
        re.sub(r"^[\-\*\u2022\d\)\.\s]+", "", line).strip()
        for line in text.splitlines()
        if str(line).strip()
    ]
    points = [line for line in points if line]
    if len(points) >= 2:
        return points

    fallback_points = [seg.strip() for seg in re.split(r"[;\n]+", text) if seg.strip()]
    if len(fallback_points) >= 2:
        return fallback_points

    sentence_points = [seg.strip() for seg in re.split(r"(?<=[\.\?!])\s+", text) if seg.strip()]
    return sentence_points or [text]


def _keyword_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    seen = set()
    for raw in _TOKEN_WORD_PATTERN.findall(str(text or "").lower()):
        word = raw.strip("'").strip("-")
        if len(word) < 3:
            continue
        if word in _FALLBACK_STOPWORDS:
            continue
        word = _TOKEN_SYNONYM_MAP.get(word, word)
        if word in seen:
            continue
        seen.add(word)
        tokens.append(word)
    return tokens


def _split_independent_clauses(text: str) -> List[str]:
    point_text = str(text or "").strip()
    if not point_text:
        return []

    clauses = [seg.strip() for seg in re.split(r"\s*;\s*", point_text) if seg.strip()]
    if len(clauses) > 1:
        return clauses

    comma_split = [seg.strip() for seg in re.split(r"\s*,\s*", point_text) if seg.strip()]
    if len(comma_split) > 1:
        return comma_split

    if " and " in point_text.lower():
        and_split = [seg.strip() for seg in re.split(r"\s+\band\b\s+", point_text, flags=re.IGNORECASE) if seg.strip()]
        if len(and_split) > 1:
            return and_split

    return [point_text]


# ============================================================================
# Data Classes
# ============================================================================

@dataclass(slots=True)
class GradingResponse:
    """Response from grading a single question."""

    marks: float
    feedback: str
    method_award: float = 0.0
    final_answer_award: float = 0.0
    is_partial_credit: bool = False
    warnings: list[str] = field(default_factory=list)
    model_used: str = ""
    model_fallback_used: bool = False
    raw_response: str = ""
    parse_status: str = ""
    error: Optional[str] = None
    manual_review_required: bool = False

    def to_dict(self) -> dict:
        return {
            "marks": self.marks,
            "feedback": self.feedback,
            "method_award": self.method_award,
            "final_answer_award": self.final_answer_award,
            "is_partial_credit": self.is_partial_credit,
            "warnings": self.warnings,
            "model_used": self.model_used,
            "model_fallback_used": self.model_fallback_used,
            "raw_response": self.raw_response,
            "parse_status": self.parse_status,
            "error": self.error,
            "manual_review_required": self.manual_review_required,
        }


@dataclass(slots=True)
class ModelAnswerResponse:
    """Response for model answer generation."""

    model_answer: str
    method_steps: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "model_answer": self.model_answer,
            "method_steps": self.method_steps,
            "key_points": self.key_points,
            "error": self.error,
        }


@dataclass(slots=True)
class PromptResponse:
    """Generic plain prompt completion response."""

    ok: bool
    reply: str = ""
    model_used: str = ""
    model_fallback_used: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reply": self.reply,
            "model_used": self.model_used,
            "model_fallback_used": self.model_fallback_used,
            "error": self.error,
        }


@dataclass(slots=True)
class PaperGradingResult:
    """Complete grading result for a paper."""

    total_questions: int
    awarded_marks: float
    max_marks: float
    percentage: float
    question_results: dict[str, GradingResponse]
    model_answers: dict[str, ModelAnswerResponse] = field(default_factory=dict)
    grading_errors: list[str] = field(default_factory=list)
    api_calls_made: int = 0
    subject_code: str = ""
    paper_number: str = ""
    year: str = ""
    ai_quota_exhausted: bool = False

    @property
    def correct_count(self) -> int:
        return sum(1 for r in self.question_results.values() if abs(float(r.marks or 0.0) - float(r.final_answer_award or 0.0)) < 1e-9)

    def to_dict(self) -> dict:
        return {
            "subject_code": self.subject_code,
            "paper_number": self.paper_number,
            "year": self.year,
            "total_questions": self.total_questions,
            "awarded_marks": self.awarded_marks,
            "max_marks": self.max_marks,
            "percentage": self.percentage,
            "correct_count": self.correct_count,
            "question_results": {k: v.to_dict() for k, v in self.question_results.items()},
            "model_answers": {k: v.to_dict() for k, v in self.model_answers.items()},
            "grading_errors": self.grading_errors,
            "api_calls_made": self.api_calls_made,
            "ai_quota_exhausted": self.ai_quota_exhausted,
        }


# ============================================================================
# Unified AI Grader
# ============================================================================


class UnifiedAIGrader:
    """Strict Groq-based grader for written and drawing responses."""

    _request_gate_lock = threading.Lock()
    _next_request_ts = 0.0

    def __init__(self, config: Optional[AIConfig] = None, api_key: Optional[str] = None):
        self.config = config or get_ai_config()
        if api_key:
            self.config.api_key = str(api_key or "").strip()
        is_valid, error = self.config.validate()
        if not is_valid:
            raise ValueError(error or "Invalid Groq configuration")

        self.client = Groq(api_key=self.config.api_key)
        self.retry_delays_sec = self._load_retry_delays()
        self.min_request_gap_sec = self._load_min_request_gap()
        self.rpm_backoff_base_sec = self._load_rpm_backoff_base()
        self.rpm_backoff_max_sec = self._load_rpm_backoff_max()
        self.rpm_max_retries = self._load_rpm_max_retries()

    @staticmethod
    def _load_retry_delays() -> Tuple[float, ...]:
        raw = str(os.getenv("GROQ_RETRY_DELAYS_SEC", "0.2,0.3") or "").strip()
        delays: List[float] = []
        for chunk in raw.split(","):
            token = str(chunk or "").strip()
            if not token:
                continue
            try:
                delay = float(token)
            except Exception:
                continue
            if delay >= 0.0:
                delays.append(delay)
        if not delays:
            return (0.2, 0.3)
        return tuple(delays[:2])

    @staticmethod
    def _load_min_request_gap() -> float:
        raw = str(os.getenv("GROQ_MIN_REQUEST_GAP_SEC", "0.05") or "").strip()
        try:
            value = float(raw)
        except Exception:
            value = 0.05
        return max(0.0, value)

    @staticmethod
    def _load_rpm_backoff_base() -> float:
        raw = str(os.getenv("GROQ_RPM_BACKOFF_BASE_SEC", "1.0") or "").strip()
        try:
            value = float(raw)
        except Exception:
            value = 1.0
        return max(0.1, value)

    @staticmethod
    def _load_rpm_backoff_max() -> float:
        raw = str(os.getenv("GROQ_RPM_BACKOFF_MAX_SEC", "20.0") or "").strip()
        try:
            value = float(raw)
        except Exception:
            value = 20.0
        return max(0.5, value)

    @staticmethod
    def _load_rpm_max_retries() -> int:
        raw = str(os.getenv("GROQ_RPM_MAX_RETRIES", "6") or "").strip()
        try:
            value = int(raw)
        except Exception:
            value = 6
        return max(0, min(20, value))

    def _reconnect_client(self) -> None:
        self.client = Groq(api_key=self.config.api_key)

    def _wait_for_request_slot(self) -> None:
        gap = float(self.min_request_gap_sec)
        if gap <= 0.0:
            return
        with self._request_gate_lock:
            now = time.monotonic()
            wait = max(0.0, self._next_request_ts - now)
            if wait > 0.0:
                time.sleep(wait)
            self.__class__._next_request_ts = max(self._next_request_ts, time.monotonic()) + gap

    def _call_with_retries(self, request_name: str, request_fn: Callable[[], Any]) -> Any:
        delays = list(self.retry_delays_sec)
        general_retry_idx = 0
        rate_limit_retry_idx = 0
        attempts = 0
        last_exc: Optional[Exception] = None

        while True:
            attempts += 1
            if attempts > 1:
                self._reconnect_client()
            try:
                self._wait_for_request_slot()
                return request_fn()
            except Exception as exc:
                last_exc = exc
                error_text = str(exc)
                error_cause = _classify_ai_error_message(error_text)

                if error_cause == "auth_401":
                    _dbg(f"[Groq retry] {request_name} failed with auth error (401). Not retrying.")
                    break

                if error_cause == "rate_limit_429" and rate_limit_retry_idx < int(self.rpm_max_retries):
                    delay = min(
                        float(self.rpm_backoff_max_sec),
                        float(self.rpm_backoff_base_sec) * (2.0 ** float(rate_limit_retry_idx)),
                    )
                    rate_limit_retry_idx += 1
                    _dbg(
                        f"[Groq retry] {request_name} hit 429/rate limit on attempt {attempts}. "
                        f"Sleeping {delay:.2f}s before retry {rate_limit_retry_idx}/{self.rpm_max_retries}."
                    )
                    if delay > 0.0:
                        time.sleep(delay)
                    continue

                if general_retry_idx < len(delays):
                    delay = float(delays[general_retry_idx])
                    general_retry_idx += 1
                    _dbg(
                        f"[Groq retry] {request_name} attempt {attempts} failed ({error_cause}): {exc}. "
                        f"Retrying in {delay:.2f}s ({general_retry_idx}/{len(delays)})."
                    )
                    if delay > 0.0:
                        time.sleep(delay)
                    continue
                break

        if last_exc is None:
            raise RuntimeError(f"{request_name} failed without an exception")
        raise RuntimeError(
            f"{request_name} failed after {attempts} attempts "
            f"(rate_limit_retries={rate_limit_retry_idx}, general_retries={general_retry_idx}): {last_exc}"
        ) from last_exc

    @staticmethod
    def _profile_block(subject: str, paper_type: str) -> str:
        profile = get_subject_grading_profile(subject, paper_type)
        axes = ", ".join(profile.rubric_axes or [])
        normalization = "; ".join(profile.normalization_rules or [])
        strictness = "; ".join(profile.strictness_rules or [])
        return (
            f"Profile: {profile.title}\n"
            f"Profile guidance: {profile.system_prompt}\n"
            f"Rubric axes: {axes or 'accuracy'}\n"
            f"Normalization rules: {normalization or 'accept scientifically equivalent phrasing where appropriate'}\n"
            f"Strictness rules: {strictness or 'stay inside max marks'}\n"
            f"Units policy: {profile.units_policy}"
        )

    @staticmethod
    def _is_math_like_subject(subject: str, paper_type: str) -> bool:
        profile_key = get_subject_profile_key(str(subject or ""), str(paper_type or ""))
        return str(profile_key or "").strip().lower() == "mathematics"

    def _chat_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        request_timeout: Optional[float] = None,
    ) -> str:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": int(max(64, max_tokens)),
        }
        if request_timeout is not None:
            kwargs["timeout"] = float(request_timeout)

        response = self._call_with_retries(
            "groq_text_completion",
            lambda: self.client.chat.completions.create(**kwargs),
        )
        text = ""
        try:
            text = str(response.choices[0].message.content or "")
        except Exception:
            text = ""
        return text.strip()

    def _chat_image(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        image_path: str,
        max_tokens: int,
        request_timeout: Optional[float] = None,
    ) -> str:
        image_bytes = Path(image_path).read_bytes()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            "temperature": 0.0,
            "max_tokens": int(max(96, max_tokens)),
        }
        if request_timeout is not None:
            kwargs["timeout"] = float(request_timeout)

        response = self._call_with_retries(
            "groq_vision_completion",
            lambda: self.client.chat.completions.create(**kwargs),
        )
        text = ""
        try:
            text = str(response.choices[0].message.content or "")
        except Exception:
            text = ""
        return text.strip()

    def _build_text_prompt(
        self,
        *,
        question_id: str,
        question_text: str,
        student_answer: str,
        mark_scheme_text: str,
        max_marks: float,
        subject: str,
        paper_type: str,
    ) -> tuple[str, str]:
        profile_block = self._profile_block(subject, paper_type)
        system_prompt = (
            "You are a strict Cambridge examiner. "
            "Treat the provided extracted mark scheme block as the authoritative source of truth and follow it exactly. "
            "Only award marks for explicitly stated points found in the mark scheme text. "
            "Strict inclusion rule: if the student explicitly states a valid mark-scheme point, award it immediately, "
            "and do not require extra context not present in the mark scheme text. "
            "Partial-credit rule: mark additively across independent clauses; award each correct clause even if another clause is wrong, "
            "unless clauses directly contradict each other. "
            "Synonym rule: accept scientifically equivalent terms where context supports equivalence, including "
            "'delocalised'/'delocalized' as valid for 'mobile' electrons. "
            "No hallucinations: do not invent mark points, requirements, context, or facts not present in the question, "
            "mark scheme, or student answer. "
            "Do not award beyond max marks. "
            "After your reasoning, output exactly one final line: FINAL MARK: <number>."
        )
        if self._is_math_like_subject(subject, paper_type):
            system_prompt += (
                " If the paper contains mathematical calculations, you must award Method Marks (M), "
                "Accuracy Marks (A), and Follow-Through marks (FT) as specified in the Mark Scheme. "
                "Mathematics formatting rule: interpret structured multi-line workings and symbolic forms faithfully, "
                "including stacked or line-broken fractions, roots, powers, and equivalent algebraic rearrangements. "
                "Do not penalize equivalent mathematical notation where the mathematical meaning is unchanged. "
                "Dependency rule: apply method/accuracy dependencies exactly; when FT is explicitly allowed, "
                "award downstream accuracy relative to the student's prior method result."
            )
        user_prompt = (
            f"{profile_block}\n\n"
            f"Question ID: {question_id}\n"
            f"Question Text:\n{question_text}\n\n"
            f"Maximum Marks: {float(max_marks):g}\n"
            "Each awarded mark must be traceable to explicit mark scheme points.\n"
            "If student wording does not explicitly cover a point, do not award it.\n"
            "Never require extra detail not written in the mark scheme point itself.\n"
            "Evaluate independent clauses separately and add marks for correct clauses.\n"
            "Only withhold a previously earned clause-mark when the student directly contradicts that same clause.\n\n"
            "The extracted mark scheme block below is authoritative and must be applied exactly as written.\n"
            f"Mark Scheme (extracted):\n{mark_scheme_text}\n\n"
            f"Student Answer:\n{student_answer}\n\n"
            "Output format:\n"
            "1) Brief point-by-point reasoning.\n"
            "2) Final line only: FINAL MARK: <number>"
        )
        context = get_subject_prompt_context(subject, paper_type)
        system_prompt += "\nThe provided mark scheme is the SOLE authoritative source of truth. "
        system_prompt += "RULE 1 — MISSING MARK SCHEME: require manual review when evidence is unavailable. "
        system_prompt += "RULE 2 — MAX MARKS CEILING: never exceed the supplied maximum. "
        system_prompt += "RULE 4 — CHAINED METHOD MARKS: apply only the dependencies stated in the scheme. "
        system_prompt += "RULE 8 — NO HALLUCINATION: do not invent requirements or evidence.\n" + context.system_addendum
        user_prompt += "\n\n" + context.user_addendum
        return system_prompt, user_prompt

    def _build_drawing_prompt(
        self,
        *,
        question_text: str,
        mark_scheme_text: str,
        max_marks: float,
        subject: str,
        paper_type: str,
    ) -> tuple[str, str]:
        profile_block = self._profile_block(subject, paper_type)
        requires_labels = any(
            token in str(question_text or "").lower()
            for token in ("label", "labelled", "labeled", "annotate", "annotation")
        )
        system_prompt = (
            "You are a strict Cambridge examiner grading a student drawing/diagram from an image. "
            "Award marks only for explicit mark-scheme features visible in the image. "
            "Do not infer hidden features. "
            "After your reasoning, output exactly one final line: FINAL MARK: <number>."
        )
        if requires_labels:
            label_rule = (
                "A mark requiring labeling is only awarded when both the feature is visible "
                "and the written label is present and legible."
            )
        else:
            label_rule = "Do not require labels unless explicitly required by the question text."
        user_prompt = (
            f"{profile_block}\n\n"
            f"Question Text:\n{question_text}\n\n"
            f"Maximum Marks: {float(max_marks):g}\n"
            f"Rule: {label_rule}\n\n"
            f"Mark Scheme (extracted):\n{mark_scheme_text}\n\n"
            "Output format:\n"
            "1) Brief point-by-point reasoning.\n"
            "2) Final line only: FINAL MARK: <number>"
        )
        context = get_subject_prompt_context(subject, paper_type)
        system_prompt += "\nThe provided mark scheme is the SOLE authoritative source of truth. "
        system_prompt += "RULE 1 — MISSING MARK SCHEME: require manual review when evidence is unavailable. "
        system_prompt += "RULE 2 — MAX MARKS CEILING: never exceed the supplied maximum. "
        system_prompt += "RULE 4 — CHAINED METHOD MARKS: apply only the dependencies stated in the scheme. "
        system_prompt += "RULE 8 — NO HALLUCINATION: do not invent requirements or evidence.\n" + context.system_addendum
        user_prompt += "\n\n" + context.user_addendum
        system_prompt += " YOU MUST SEE THE IMAGE; unreadable or unavailable evidence requires manual review."
        user_prompt += "\nOnly award diagram marks for features clearly visible in the image."
        return system_prompt, user_prompt

    @staticmethod
    def _fallback_keyword_grade(
        *,
        question_id: str,
        question_text: str,
        student_answer: str,
        mark_scheme_text: str,
        max_marks: float,
    ) -> tuple[float, str]:
        points = _split_mark_scheme_points(mark_scheme_text)
        answer_text = str(student_answer or "").strip()
        if not answer_text:
            return 0.0, "No answer provided."
        if not points:
            return 0.0, "No mark-scheme points available for keyword fallback."

        answer_tokens = set(_keyword_tokens(answer_text))
        awarded_marks = 0.0
        lines: List[str] = []
        marks_per_point = float(max_marks) / float(max(1, len(points)))

        for idx, point in enumerate(points, start=1):
            point_clean = str(point or "").strip()
            clauses = _split_independent_clauses(point_clean)
            if not clauses:
                clauses = [point_clean]

            clause_hits = 0
            clause_lines: List[str] = []

            for c_idx, clause in enumerate(clauses, start=1):
                clause_tokens = _keyword_tokens(clause)[:10]
                if not clause_tokens:
                    matched = clause.lower() in answer_text.lower()
                    matched_count = 1 if matched else 0
                else:
                    matched_count = sum(1 for token in clause_tokens if token in answer_tokens)
                    matched = matched_count >= 1
                if matched:
                    clause_hits += 1
                clause_lines.append(
                    f"  Clause {idx}.{c_idx}: {'matched' if matched else 'not matched'} "
                    f"({matched_count}/{max(1, len(clause_tokens))} key terms)"
                )

            point_fraction = float(clause_hits) / float(max(1, len(clauses)))
            point_marks = marks_per_point * point_fraction
            awarded_marks += point_marks
            lines.append(
                f"Point {idx}: awarded {point_marks:.2f}/{marks_per_point:.2f} "
                f"(matched clauses {clause_hits}/{len(clauses)})"
            )
            lines.extend(clause_lines)

        marks = max(0.0, min(float(max_marks), round(awarded_marks, 2)))
        header = (
            f"Auto fallback applied for Q{question_id} because Groq retries were exhausted.\n"
            f"Question: {question_text.strip() or '[no text]'}\n"
            f"Keyword coverage against extracted mark-scheme points:"
        )
        return marks, "\n".join([header, *lines])

    def grade_question(
        self,
        question_id: str,
        question_text: str,
        student_answer: str,
        correct_answer: Optional[str] = None,
        mark_scheme_text: Optional[str] = None,
        max_marks: int = 1,
        subject: str = "",
        paper_type: str = "",
    ) -> GradingResponse:
        cleaned_question_text = _apply_standard_math_text_cleaning(question_text)
        cleaned_student_answer = _apply_standard_math_text_cleaning(student_answer)
        cleaned_correct_answer = _apply_standard_math_text_cleaning(correct_answer or "")
        cleaned_mark_scheme_text = _apply_standard_math_text_cleaning(mark_scheme_text or "")

        if _is_blank_answer_text(cleaned_student_answer):
            return GradingResponse(
                marks=0.0,
                feedback="No answer provided.",
                method_award=0.0,
                final_answer_award=0.0,
                is_partial_credit=False,
                warnings=["blank_answer"],
                model_used="",
                model_fallback_used=False,
                raw_response="",
                parse_status="blank",
            )

        mark_scheme = str(cleaned_mark_scheme_text or cleaned_correct_answer).strip() or "[No mark scheme text provided]"
        if _mark_scheme_is_missing(mark_scheme):
            return GradingResponse(
                marks=0.0,
                feedback=(
                    "Mark scheme text is missing or unresolved for this question. "
                    "Manual review required."
                ),
                method_award=0.0,
                final_answer_award=0.0,
                is_partial_credit=False,
                warnings=["missing_mark_scheme"],
                model_used="",
                model_fallback_used=False,
                raw_response="",
                parse_status="missing_mark_scheme",
                error=None,
                manual_review_required=True,
            )
        if _mark_scheme_requires_diagram(mark_scheme) and _student_answer_is_text_only(cleaned_student_answer):
            return GradingResponse(
                marks=0.0,
                feedback=(
                    "Mark scheme requires a drawn diagram with functional groups shown. "
                    "Student provided a text description only. "
                    "A text description cannot substitute for a drawn structural diagram. "
                    "Manual review required."
                ),
                method_award=0.0,
                final_answer_award=0.0,
                is_partial_credit=False,
                warnings=["diagram_required_text_only", "manual_review_recommended"],
                model_used="",
                model_fallback_used=False,
                raw_response="",
                parse_status="diagram_required_text_only",
                error=None,
                manual_review_required=True,
            )
        system_prompt, user_prompt = self._build_text_prompt(
            question_id=question_id,
            question_text=cleaned_question_text,
            student_answer=cleaned_student_answer,
            mark_scheme_text=mark_scheme,
            max_marks=float(max_marks),
            subject=subject,
            paper_type=paper_type,
        )
        if (
            _mark_scheme_has_method_chain(mark_scheme)
            and _student_answer_shows_no_working(cleaned_student_answer)
            and float(max_marks) > 1
        ):
            user_prompt += (
                "\n\nCRITICAL OVERRIDE: The mark scheme contains chained method marks "
                "(M1, M2, M3...). The student has provided only a final answer with "
                "no working shown. You MUST apply the following rule without exception:\n"
                "- Award ONLY the final answer mark (the last M-mark in the chain).\n"
                "- Do NOT award any intermediate method marks (M1, M2, etc.).\n"
                "- A correct final answer without working earns exactly 1 mark "
                "unless the mark scheme explicitly says 'answer only' or 'cao'.\n"
                "This rule overrides any other reasoning. Do not argue against it."
            )

        try:
            raw = self._chat_text(
                model=self.config.text_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=self.config.max_tokens,
                request_timeout=float(self.config.timeout),
            )
            marks, parse_status = _parse_mark(raw, float(max_marks))
            if parse_status in {"unparseable", "fallback_last_number"}:
                raise ValueError("AI response did not contain an explicit mark award")
            feedback = _extract_reasoning_without_final_mark(raw)
            if not feedback:
                feedback = "AI response parsed without detailed reasoning."
            method_award = max(0.0, min(float(max_marks), marks))
            final_award = method_award
            is_partial = 0.0 < marks < float(max_marks)
            warnings: List[str] = []
            if parse_status != "final_mark_line":
                warnings.append(f"parse:{parse_status}")
            return GradingResponse(
                marks=marks,
                feedback=feedback,
                method_award=method_award,
                final_answer_award=final_award,
                is_partial_credit=is_partial,
                warnings=warnings,
                model_used=self.config.text_model,
                model_fallback_used=False,
                raw_response=raw,
                parse_status=parse_status,
                manual_review_required=False,
            )
        except Exception as exc:
            error_text = str(exc)
            error_cause = _classify_ai_error_message(error_text)
            return GradingResponse(
                marks=0.0,
                feedback="AI grading could not complete. This answer needs manual review.",
                warnings=["ai_retry_exhausted", f"ai_error_type:{error_cause}"],
                model_used=self.config.text_model,
                model_fallback_used=False,
                raw_response=f"AI_ERROR: {error_text}",
                parse_status="pending_manual_review",
                error=error_text,
                manual_review_required=True,
            )

    def grade_drawing(
        self,
        question_id: str,
        question_text: str,
        mark_scheme_text: str,
        image_path: str,
        max_marks: float,
        student_notes: str = "",
        subject: str = "",
        paper_type: str = "",
    ) -> Dict[str, Any]:
        normalized_qid = normalize_question_id(question_id)
        display_qid = format_question_id_display(normalized_qid or question_id)
        image_name = os.path.basename(str(image_path or ""))
        try:
            image_size_bytes = int(os.path.getsize(image_path))
        except Exception:
            image_size_bytes = 0

        if not str(image_path or "").strip() or not os.path.exists(image_path):
            return {
                "question_id": question_id,
                "manual_review_required": True,
                "status": "missing_drawing",
                "marks": 0.0,
                "max_marks": float(max_marks),
                "confidence": 1.0,
                "feedback": "Drawing image is missing.",
                "image_path": image_path,
                "model": self.config.vision_model,
                "vision_attempted": False,
                "question_text": question_text,
                "mark_scheme_text": mark_scheme_text,
                "raw_response": "",
                "parse_status": "missing_image",
                "retry_attempted": False,
                "retry_parse_status": "",
                "retry_raw_response": "",
                "error": "",
            }

        system_prompt, user_prompt = self._build_drawing_prompt(
            question_text=question_text,
            mark_scheme_text=mark_scheme_text,
            max_marks=float(max_marks),
            subject=subject,
            paper_type=paper_type,
        )

        try:
            raw = self._chat_image(
                model=self.config.vision_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_path=image_path,
                max_tokens=self.config.max_tokens,
                request_timeout=float(self.config.timeout),
            )
            marks, parse_status = _parse_mark(raw, float(max_marks))
            if parse_status in {"unparseable", "fallback_last_number"}:
                raise ValueError("AI response did not contain an explicit mark award")
            hallucinated = marks > 0 and _drawing_response_is_hallucinated(raw)
            retry_attempted = False
            retry_parse_status = ""
            retry_raw_response = ""

            if hallucinated:
                retry_attempted = True
                _dbg(
                    "[Drawing retry] qid=%s image=%s size_bytes=%s model=%s "
                    "first_parse_status=%s first_hallucinated=%s"
                    % (
                        display_qid,
                        image_name,
                        image_size_bytes,
                        self.config.vision_model,
                        parse_status,
                        hallucinated,
                    )
                )
                retry_raw_response = self._chat_image(
                    model=self.config.vision_model,
                    system_prompt=system_prompt,
                    user_prompt=_build_drawing_visibility_retry_prompt(user_prompt),
                    image_path=image_path,
                    max_tokens=self.config.max_tokens,
                    request_timeout=float(self.config.timeout),
                )
                retry_marks, retry_parse_status = _parse_mark(retry_raw_response, float(max_marks))
                retry_hallucinated = _drawing_response_is_hallucinated(retry_raw_response)
                _dbg(
                    "[Drawing retry] qid=%s image=%s size_bytes=%s model=%s "
                    "retry_parse_status=%s retry_hallucinated=%s final_marks=%s manual_review=%s"
                    % (
                        display_qid,
                        image_name,
                        image_size_bytes,
                        self.config.vision_model,
                        retry_parse_status,
                        retry_hallucinated,
                        0.0 if retry_hallucinated else retry_marks,
                        retry_hallucinated,
                    )
                )
                if not retry_hallucinated:
                    raw = retry_raw_response
                    marks = retry_marks
                    parse_status = retry_parse_status

            if parse_status in {"unparseable", "fallback_last_number"}:
                raise ValueError("AI response did not contain an explicit mark award")

            if retry_attempted and _drawing_response_is_hallucinated(retry_raw_response):
                return {
                    "question_id": question_id,
                    "manual_review_required": True,
                    "status": "drawing_hallucination_blocked",
                    "marks": 0.0,
                    "max_marks": float(max_marks),
                    "confidence": 0.0,
                    "feedback": (
                        "Drawing could not be verified from the image. "
                        "AI used hedging language indicating it could not see the diagram. "
                        "Manual review required."
                    ),
                    "warnings": ["drawing_hallucination_blocked", "manual_review_recommended"],
                    "image_path": image_path,
                    "model": self.config.vision_model,
                    "model_fallback_used": False,
                    "vision_attempted": True,
                    "question_text": question_text,
                    "mark_scheme_text": mark_scheme_text,
                    "raw_response": raw,
                    "parse_status": "drawing_hallucination_blocked",
                    "retry_attempted": True,
                    "retry_parse_status": retry_parse_status,
                    "retry_raw_response": retry_raw_response,
                    "error": "",
                }
            feedback = _extract_reasoning_without_final_mark(raw)
            if not feedback:
                feedback = "Drawing graded with limited explanation."
            return {
                "question_id": question_id,
                "manual_review_required": False,
                "status": "graded",
                "marks": marks,
                "max_marks": float(max_marks),
                "confidence": 1.0 if parse_status == "final_mark_line" else 0.7,
                "feedback": feedback,
                "warnings": [] if parse_status == "final_mark_line" else [f"parse:{parse_status}"],
                "image_path": image_path,
                "model": self.config.vision_model,
                "model_fallback_used": False,
                "vision_attempted": True,
                "question_text": question_text,
                "mark_scheme_text": mark_scheme_text,
                "raw_response": raw,
                "parse_status": parse_status,
                "retry_attempted": retry_attempted,
                "retry_parse_status": retry_parse_status,
                "retry_raw_response": retry_raw_response,
                "error": "",
            }
        except Exception as exc:
            error_text = str(exc)
            error_cause = _classify_ai_error_message(error_text)
            fallback_marks = 0.0
            fallback_feedback = "Drawing grading could not complete; manual review is required."
            raw = f"AI_ERROR_TYPE: {error_cause}\nAI_ERROR: {error_text}"
            return {
                "question_id": question_id,
                "manual_review_required": True,
                "status": "grading_failed_pending_review",
                "marks": fallback_marks,
                "max_marks": float(max_marks),
                "confidence": 0.3 if str(student_notes or "").strip() else 0.1,
                "feedback": fallback_feedback,
                "warnings": ["ai_retry_exhausted", "manual_review_required", f"ai_error_type:{error_cause}"],
                "image_path": image_path,
                "model": self.config.vision_model,
                "model_fallback_used": True,
                "vision_attempted": True,
                "question_text": question_text,
                "mark_scheme_text": mark_scheme_text,
                "raw_response": raw,
                "parse_status": "pending_manual_review",
                "retry_attempted": False,
                "retry_parse_status": "",
                "retry_raw_response": "",
                "error": error_text,
                "error_type": error_cause,
            }

    def generate_model_answer(
        self,
        question_id: str,
        question_text: str,
        correct_answer: Optional[str],
        max_marks: int,
        subject: str = "",
        paper_type: str = "",
    ) -> ModelAnswerResponse:
        _ = question_id
        _ = max_marks
        profile_block = self._profile_block(subject, paper_type)
        system_prompt = (
            "You are a Cambridge examiner generating concise model answers. "
            "Return JSON with keys model_answer, method_steps, key_points."
        )
        user_prompt = (
            f"{profile_block}\n\n"
            f"Question:\n{question_text}\n\n"
            f"Mark Scheme:\n{str(correct_answer or '').strip()}\n"
        )

        try:
            raw = self._chat_text(
                model=self.config.text_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=min(600, self.config.max_tokens),
                request_timeout=float(self.config.timeout),
            )
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("model answer payload is not an object")
            return ModelAnswerResponse(
                model_answer=str(payload.get("model_answer", correct_answer or "") or ""),
                method_steps=[str(x) for x in payload.get("method_steps", []) if str(x).strip()],
                key_points=[str(x) for x in payload.get("key_points", []) if str(x).strip()],
                error=None,
            )
        except Exception as exc:
            return ModelAnswerResponse(
                model_answer=str(correct_answer or ""),
                method_steps=[],
                key_points=[],
                error=str(exc),
            )

    def send_plain_prompt(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 120,
        temperature: float = 0.0,
        request_timeout: Optional[float] = None,
    ) -> PromptResponse:
        _ = temperature
        text = str(prompt or "").strip()
        if not text:
            return PromptResponse(ok=False, error="Prompt is empty.")

        try:
            effective_timeout = float(self.config.timeout) if request_timeout is None else float(request_timeout)
            reply = self._chat_text(
                model=self.config.text_model,
                system_prompt=str(system_prompt or "").strip() or "Reply briefly and directly.",
                user_prompt=text,
                max_tokens=max_tokens,
                request_timeout=effective_timeout,
            )
            if not reply:
                return PromptResponse(
                    ok=False,
                    reply="",
                    model_used=self.config.text_model,
                    model_fallback_used=False,
                    error="Empty AI reply.",
                )
            return PromptResponse(
                ok=True,
                reply=reply,
                model_used=self.config.text_model,
                model_fallback_used=False,
                error=None,
            )
        except Exception as exc:
            return PromptResponse(
                ok=False,
                reply="",
                model_used=self.config.text_model,
                model_fallback_used=False,
                error=str(exc),
            )

    def grade_paper(
        self,
        questions: List[Dict[str, Any]],
        student_answers: Dict[str, str],
        subject_code: str = "",
        paper_number: str = "",
        year: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_calls: Optional[int] = None,
        deadline_ts: Optional[float] = None,
        generate_model_answers: bool = False,
    ) -> PaperGradingResult:
        _ = generate_model_answers

        total_questions = len(questions)
        max_marks = float(sum(float(q.get("marks", 1) or 1) for q in questions))
        batch_size = max(1, int(ai_grading_batch_size()))

        question_results: Dict[str, GradingResponse] = {}
        model_answers: Dict[str, ModelAnswerResponse] = {}
        errors: List[str] = []
        awarded_marks = 0.0
        api_calls_made = 0
        quota_exhausted = False
        stop_early = False
        error_cause_counts = _new_error_cause_counts()
        effective_max_calls: Optional[int] = None
        if max_calls is not None:
            try:
                parsed_max_calls = int(max_calls)
            except Exception:
                parsed_max_calls = 0
            if parsed_max_calls > 0:
                effective_max_calls = parsed_max_calls

        for batch_start in range(0, total_questions, batch_size):
            batch_end = min(total_questions, batch_start + batch_size)
            for q_index in range(batch_start, batch_end):
                q = questions[q_index]
                idx = q_index + 1
                q_id = str(q.get("id", "") or "")
                student_answer = str(student_answers.get(q_id, "") or "")

                if progress_callback:
                    try:
                        progress_callback(max(0, idx - 1), total_questions, f"Grading Q{q_id}...")
                    except Exception:
                        pass

                if cancel_check and cancel_check():
                    errors.append("AI grading cancelled by user.")
                    stop_early = True
                    break
                if deadline_ts is not None and time.time() >= float(deadline_ts):
                    errors.append(
                        "AI wall-time budget reached "
                        f"({_format_error_cause_breakdown(error_cause_counts)}); returning partial AI results."
                    )
                    stop_early = True
                    break
                if effective_max_calls is not None and api_calls_made >= int(effective_max_calls):
                    errors.append(
                        "AI call budget reached "
                        f"({_format_error_cause_breakdown(error_cause_counts)}); returning partial AI results."
                    )
                    stop_early = True
                    break

                try:
                    result = self.grade_question(
                        question_id=q_id,
                        question_text=str(q.get("text", "") or ""),
                        student_answer=student_answer,
                        correct_answer=str(q.get("answer", "") or ""),
                        mark_scheme_text=str(q.get("mark_scheme_text", q.get("answer", "")) or ""),
                        max_marks=int(float(q.get("marks", 1) or 1)),
                        subject=subject_code,
                        paper_type=paper_number,
                    )
                except Exception as exc:
                    manager_error = f"manager_exception: {exc}"
                    manager_cause = _classify_ai_error_message(manager_error)
                    result = GradingResponse(
                        marks=0.0,
                        feedback="AI grading request failed for this question; continued grading remaining questions.",
                        method_award=0.0,
                        final_answer_award=0.0,
                        is_partial_credit=False,
                        warnings=["manager_exception", f"ai_error_type:{manager_cause}"],
                        model_used=self.config.text_model,
                        model_fallback_used=False,
                        raw_response="",
                        parse_status="manager_exception",
                        error=manager_error,
                    )

                question_results[q_id] = result
                awarded_marks += float(result.marks or 0.0)
                api_calls_made += 1

                if result.error:
                    cause = _record_error_cause(error_cause_counts, result.error)
                    errors.append(f"Q{q_id}: {result.error} [type={cause}]")
                    if cause == "rate_limit_429" or _is_quota_error_message(result.error):
                        quota_exhausted = True
                else:
                    warning_cause = _extract_error_cause_from_warnings(list(result.warnings or []))
                    if warning_cause:
                        error_cause_counts[warning_cause] = int(error_cause_counts.get(warning_cause, 0)) + 1
                        if warning_cause == "rate_limit_429":
                            quota_exhausted = True

                if progress_callback:
                    try:
                        progress_callback(idx, total_questions, f"AI graded Q{q_id}")
                    except Exception:
                        pass

            maybe_collect_garbage("ai_grade_batch")
            if stop_early:
                break

        if total_questions > 0 and len(question_results) < total_questions:
            graded_ids = set(question_results.keys())
            for q in questions:
                q_id = str(q.get("id", "") or "")
                if q_id in graded_ids:
                    continue
                question_results[q_id] = GradingResponse(
                    marks=0.0,
                    feedback="Not graded due to earlier AI failure/budget limit.",
                    method_award=0.0,
                    final_answer_award=0.0,
                    is_partial_credit=False,
                    warnings=["not_graded"],
                    model_used=self.config.text_model,
                    model_fallback_used=False,
                    raw_response="",
                    parse_status="skipped",
                    error="not_graded",
                )

        awarded_marks = sum(float(res.marks or 0.0) for res in question_results.values())
        percentage = (awarded_marks / max_marks * 100.0) if max_marks > 0 else 0.0
        gc.collect()

        return PaperGradingResult(
            total_questions=total_questions,
            awarded_marks=awarded_marks,
            max_marks=max_marks,
            percentage=percentage,
            question_results=question_results,
            model_answers=model_answers,
            grading_errors=errors,
            api_calls_made=api_calls_made,
            subject_code=subject_code,
            paper_number=paper_number,
            year=year,
            ai_quota_exhausted=quota_exhausted,
        )


# ============================================================================
# Convenience Functions
# ============================================================================


def is_ai_grading_available() -> bool:
    return is_ai_enabled()


def grade_with_ai(
    question_id: str,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    max_marks: int,
    mark_scheme_text: Optional[str] = None,
) -> GradingResponse:
    if not is_ai_enabled():
        return GradingResponse(
            marks=0.0,
            feedback="AI grading not configured. Ensure Groq API key is set.",
            error="AI not configured",
            parse_status="disabled",
        )

    grader = UnifiedAIGrader()
    return grader.grade_question(
        question_id=question_id,
        question_text=question_text,
        student_answer=student_answer,
        correct_answer=correct_answer,
        mark_scheme_text=mark_scheme_text,
        max_marks=max_marks,
    )


def generate_model_answer(
    question_id: str,
    question_text: str,
    correct_answer: str,
    max_marks: int,
) -> ModelAnswerResponse:
    if not is_ai_enabled():
        return ModelAnswerResponse(
            model_answer=correct_answer,
            error="AI not configured",
        )

    grader = UnifiedAIGrader()
    return grader.generate_model_answer(
        question_id=question_id,
        question_text=question_text,
        correct_answer=correct_answer,
        max_marks=max_marks,
    )


def grade_paper_with_ai(
    questions: list[dict],
    student_answers: dict[str, str],
    subject_code: str = "",
    paper_number: str = "",
    year: str = "",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    max_calls: Optional[int] = None,
    deadline_ts: Optional[float] = None,
    generate_model_answers: bool = False,
) -> PaperGradingResult:
    if not is_ai_enabled():
        return PaperGradingResult(
            total_questions=len(questions),
            awarded_marks=0.0,
            max_marks=sum(float(q.get("marks", 1) or 1) for q in questions),
            percentage=0.0,
            question_results={},
            model_answers={},
            grading_errors=["AI grading not configured"],
            subject_code=subject_code,
            paper_number=paper_number,
            year=year,
            ai_quota_exhausted=False,
        )

    grader = UnifiedAIGrader()
    return grader.grade_paper(
        questions=questions,
        student_answers=student_answers,
        subject_code=subject_code,
        paper_number=paper_number,
        year=year,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        max_calls=max_calls,
        deadline_ts=deadline_ts,
        generate_model_answers=generate_model_answers,
    )


def send_prompt_with_ai(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 120,
    temperature: float = 0.0,
    request_timeout: Optional[float] = None,
) -> PromptResponse:
    """Reusable helper for plain prompt transport through Groq models."""
    if not is_ai_enabled():
        return PromptResponse(ok=False, error="AI not configured")
    grader = UnifiedAIGrader()
    return grader.send_plain_prompt(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        request_timeout=request_timeout,
    )


def grade_drawing_question(
    question_id: str,
    question_text: str,
    mark_scheme_text: str,
    image_path: str,
    max_marks: float = 0.0,
    student_notes: str = "",
    subject: str = "",
    paper_type: str = "",
) -> Dict[str, Any]:
    """Grade drawing/diagram/graph responses using Groq vision."""
    if not is_ai_enabled():
        return {
            "question_id": question_id,
            "manual_review_required": True,
            "status": "ai_not_configured_pending_review",
            "marks": 0.0,
            "max_marks": max_marks,
            "confidence": 1.0,
            "feedback": "AI grading is unavailable. The submitted drawing requires manual review.",
            "image_path": image_path,
            "model": "",
            "vision_attempted": False,
            "question_text": question_text,
            "mark_scheme_text": mark_scheme_text,
            "raw_response": "",
            "parse_status": "fallback_zero",
            "error": "",
        }

    grader = UnifiedAIGrader()
    return grader.grade_drawing(
        question_id=question_id,
        question_text=question_text,
        mark_scheme_text=mark_scheme_text,
        image_path=image_path,
        max_marks=max_marks,
        student_notes=student_notes,
        subject=subject,
        paper_type=paper_type,
    )


# ============================================================================
# Utility Functions
# ============================================================================


def should_use_ai_grading(subject_code: str, paper_number: str, exam_year: int = 2026) -> bool:
    decision = resolve_mode(str(subject_code), str(paper_number), exam_year=int(exam_year))
    if not decision.gradable:
        return False
    return decision.mode in {"WRITTEN_ONLY", "MIXED"}


# Backward compatibility wrappers and consolidated math APIs


@dataclass(slots=True)
class AIGradingOptions:
    """Execution controls for AI paper grading."""

    max_ai_calls: int = 0
    max_wall_time_sec: int = 0
    generate_model_answers: bool = False


_MATH_LONG_FORM_COMMAND_WORDS = (
    "explain",
    "describe",
    "discuss",
    "justify",
    "compare",
    "why",
    "how",
)


def _coerce_mark_value(value: Any, default: float = 1.0) -> float:
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    except Exception:
        pass
    return float(default)


def _is_long_form_written_question(question_text: str, max_marks: Any) -> bool:
    marks = _coerce_mark_value(max_marks, default=1.0)
    if marks >= 2.0:
        return True
    text = str(question_text or "").strip().lower()
    if not text:
        return False
    return any(word in text for word in _MATH_LONG_FORM_COMMAND_WORDS)


def _coerce_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return int(default)
    return max(0, parsed)


def _resolve_ai_options(ai_options: Optional[Dict[str, Any] | AIGradingOptions]) -> AIGradingOptions:
    if isinstance(ai_options, AIGradingOptions):
        return ai_options
    if isinstance(ai_options, dict):
        return AIGradingOptions(
            max_ai_calls=_coerce_non_negative_int(ai_options.get("max_ai_calls", 0), default=0),
            max_wall_time_sec=_coerce_non_negative_int(ai_options.get("max_wall_time_sec", 0), default=0),
            generate_model_answers=bool(ai_options.get("generate_model_answers", False)),
        )
    return AIGradingOptions()


def normalize_question_id(q_id: str) -> str:
    """Normalize question IDs to compact canonical format (e.g. 5di)."""
    return normalize_question_id_canonical(q_id)


def format_question_id_display(q_id: str) -> str:
    """Format canonical IDs for display (e.g. 5di -> 5(d)(i))."""
    return format_question_display(q_id)


def normalize_answer_key(answer_key: dict) -> dict:
    """Normalize all keys in an answer key dict."""
    normalized = {}
    for q_id, info in (answer_key or {}).items():
        norm = normalize_question_id(q_id)
        if not norm:
            continue
        normalized[norm] = info
    return normalized


# ============================================================================
# Built-in Answer Key and Structure Data
# ============================================================================

MATH_ANSWER_KEYS = {
    "0580": {
        "2": {
            "2023": {
                "1": {"answer": "42", "marks": 1},
                "2": {"answer": "3.5", "marks": 1},
                "3": {"answer": "120", "marks": 1},
                "4": {"answer": "15", "marks": 2},
                "5": {"answer": "72", "marks": 2},
                "6": {"answer": "25", "marks": 2},
                "7": {"answer": "8", "marks": 2},
                "8": {"answer": "180", "marks": 2},
                "9": {"answer": "36", "marks": 2},
                "10": {"answer": "5", "marks": 2},
            },
            "2024": {
                "1": {"answer": "35", "marks": 1},
                "2": {"answer": "4.8", "marks": 1},
                "3": {"answer": "150", "marks": 1},
                "4": {"answer": "18", "marks": 2},
                "5": {"answer": "64", "marks": 2},
                "6": {"answer": "30", "marks": 2},
                "7": {"answer": "12", "marks": 2},
                "8": {"answer": "240", "marks": 2},
                "9": {"answer": "48", "marks": 2},
                "10": {"answer": "7", "marks": 2},
            },
        },
        "4": {
            "2023": {
                "1a": {"answer": "5", "marks": 1},
                "1b": {"answer": "3x+7", "marks": 2},
                "2a": {"answer": "48", "marks": 2},
                "2b": {"answer": "12", "marks": 2},
                "3a": {"answer": "2/3", "marks": 1},
                "3b": {"answer": "0.667", "marks": 1},
                "4": {"answer": "120", "marks": 3},
                "5a": {"answer": "30", "marks": 2},
                "5b": {"answer": "45", "marks": 2},
            }
        },
    },
    "0606": {
        "1": {
            "2023": {
                "1": {"answer": "x=3", "marks": 2},
                "2": {"answer": "y=2x+5", "marks": 3},
                "3": {"answer": "60", "marks": 2},
                "4": {"answer": "3.14", "marks": 2},
                "5": {"answer": "x²+5x+6", "marks": 3},
            }
        }
    },
    "0607": {
        "1": {
            "2023": {
                "1": {"answer": "x=5", "marks": 2},
                "2": {"answer": "y=3x-2", "marks": 3},
            }
        }
    },
}


PAPER_STRUCTURE_DB = {
    "0580": {
        "2": {"questions": 10, "subsections": False, "avg_marks": 2},
        "3": {"questions": 14, "subsections": True, "avg_marks": 2},
        "4": {"questions": 12, "subsections": True, "avg_marks": 3},
    },
    "0606": {
        "1": {"questions": 11, "subsections": True, "avg_marks": 3},
        "2": {"questions": 11, "subsections": True, "avg_marks": 3},
    },
    "0607": {
        "1": {"questions": 25, "subsections": False, "avg_marks": 1},
        "2": {"questions": 25, "subsections": False, "avg_marks": 1},
        "3": {"questions": 10, "subsections": True, "avg_marks": 4},
        "4": {"questions": 10, "subsections": True, "avg_marks": 4},
        "5": {"questions": 6, "subsections": True, "avg_marks": 5},
        "6": {"questions": 6, "subsections": True, "avg_marks": 5},
    },
    "0610": {
        "3": {"questions": 8, "subsections": True, "avg_marks": 3},
        "4": {"questions": 8, "subsections": True, "avg_marks": 3},
        "5": {"questions": 3, "subsections": True, "avg_marks": 25},
        "6": {"questions": 3, "subsections": True, "avg_marks": 25},
    },
    "0620": {
        "3": {"questions": 8, "subsections": True, "avg_marks": 3},
        "4": {"questions": 8, "subsections": True, "avg_marks": 3},
        "5": {"questions": 3, "subsections": True, "avg_marks": 25},
        "6": {"questions": 3, "subsections": True, "avg_marks": 25},
    },
    "0625": {
        "3": {"questions": 8, "subsections": True, "avg_marks": 3},
        "4": {"questions": 8, "subsections": True, "avg_marks": 3},
        "5": {"questions": 3, "subsections": True, "avg_marks": 25},
        "6": {"questions": 3, "subsections": True, "avg_marks": 25},
    },
    "0653": {
        "3": {"questions": 8, "subsections": True, "avg_marks": 3},
        "4": {"questions": 8, "subsections": True, "avg_marks": 3},
        "5": {"questions": 3, "subsections": True, "avg_marks": 25},
        "6": {"questions": 3, "subsections": True, "avg_marks": 25},
    },
    "0654": {
        "3": {"questions": 8, "subsections": True, "avg_marks": 3},
        "4": {"questions": 8, "subsections": True, "avg_marks": 3},
        "5": {"questions": 3, "subsections": True, "avg_marks": 25},
        "6": {"questions": 3, "subsections": True, "avg_marks": 25},
    },
}


def get_paper_structure(subject_code: str, paper_num: str) -> dict:
    """Get paper structure (question count, subsections) for a paper."""
    subject = str(subject_code or "").strip()
    paper = str(paper_num or "").strip()
    if subject in PAPER_STRUCTURE_DB and paper in PAPER_STRUCTURE_DB[subject]:
        return PAPER_STRUCTURE_DB[subject][paper]
    return {"questions": 10, "subsections": True, "avg_marks": 2}


def generate_answer_key(subject_code: str, paper_num: str, year: Optional[str] = None) -> dict:
    """Generate placeholder answer key for papers without predefined keys."""
    _ = year
    structure = get_paper_structure(subject_code, paper_num)
    questions = int(structure.get("questions", 10) or 10)
    has_subsections = bool(structure.get("subsections", True))
    avg_marks = _coerce_mark_value(structure.get("avg_marks", 2), default=2.0)

    answer_key: Dict[str, Dict[str, Any]] = {}
    if has_subsections:
        for q_num in range(1, questions + 1):
            for sub in ("a", "b", "c"):
                answer_key[f"{q_num}{sub}"] = {
                    "answer": "[See Mark Scheme]",
                    "marks": avg_marks,
                    "is_generated": True,
                }
    else:
        for q_num in range(1, questions + 1):
            answer_key[str(q_num)] = {
                "answer": "[See Mark Scheme]",
                "marks": avg_marks,
                "is_generated": True,
            }
    return answer_key


def get_answer_key(subject_code: str, paper_num: str, year: Optional[str] = None) -> Optional[dict]:
    """Get answer key for a specific paper; falls back to generated key."""
    try:
        year_str = str(year) if year else "2023"
        paper_str = str(paper_num)
        subject = str(subject_code)
        if subject in MATH_ANSWER_KEYS:
            if paper_str in MATH_ANSWER_KEYS[subject]:
                if year_str in MATH_ANSWER_KEYS[subject][paper_str]:
                    return normalize_answer_key(MATH_ANSWER_KEYS[subject][paper_str][year_str])
    except Exception:
        pass
    generated_key = generate_answer_key(subject_code, paper_num, year)
    if generated_key:
        return normalize_answer_key(generated_key)
    return None


# ============================================================================
# Math Answer Parsing and PDF Question Detection
# ============================================================================

ROMAN_NUMERALS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]


class MathAnswerParser:
    """Parse and compare mathematical answers."""

    @staticmethod
    def normalize_answer(answer: Any) -> str:
        if answer is None:
            return ""
        value = str(answer).strip().lower()
        value = value.replace(" ", "")
        value = _normalize_math_symbol_tokens(value)
        return value

    @staticmethod
    def extract_number(answer: Any) -> Optional[float]:
        from Grading.safe_math import arithmetic_value
        try:
            return arithmetic_value(str(answer))
        except (ValueError, SyntaxError, TypeError, ArithmeticError, RecursionError):
            return None

    @staticmethod
    def compare_answers(student_ans: Any, correct_ans: Any, tolerance: float = 0.01) -> bool:
        if student_ans is None or correct_ans is None:
            return False

        student_text = MathAnswerParser.normalize_answer(student_ans)
        correct_text = MathAnswerParser.normalize_answer(correct_ans)

        if "[see mark scheme]" in correct_text.lower():
            return False
        if not student_text or not correct_text:
            return False
        if student_text == correct_text:
            return True

        student_num = MathAnswerParser.extract_number(student_text)
        correct_num = MathAnswerParser.extract_number(correct_text)
        if student_num is not None and correct_num is not None:
            return abs(student_num - correct_num) < float(tolerance)

        try:
            return Fraction(student_text) == Fraction(correct_text)
        except Exception:
            return False


class PDFQuestionDetector:
    """Detect questions from PDF using OCR and text extraction."""

    def __init__(self):
        self.question_patterns = [
            r"^(\d+)\s*[\.\)]",
            r"^(\d+)\s*\(([a-z])\)",
            r"^(\d+)\s*\(([ivx]+)\)",
            r"^\(([a-z])\)",
            r"^\(([ivx]+)\)",
        ]

    @staticmethod
    def _roman_to_int(roman: str) -> int:
        text = str(roman or "").upper()
        values = {"I": 1, "V": 5, "X": 10}
        result = 0
        prev = 0
        for ch in reversed(text):
            curr = values.get(ch, 0)
            if curr < prev:
                result -= curr
            else:
                result += curr
            prev = curr
        return result

    def detect_from_pdf(self, pdf_path_or_doc: Any, max_pages: int = 10) -> Optional[Dict[int, Dict[str, List[str]]]]:
        if not pdf_path_or_doc:
            return None
        doc = None
        try:
            if isinstance(pdf_path_or_doc, str):
                if not FITZ_AVAILABLE:
                    print("⚠️ PyMuPDF (fitz) not available; skipping PDF question detection.")
                    return None
                doc = fitz.open(pdf_path_or_doc)
            else:
                doc = pdf_path_or_doc

            questions: Dict[int, Dict[str, List[str]]] = {}
            current_main: Optional[int] = None
            pages_to_scan = min(len(doc), int(max_pages))

            for page_num in range(pages_to_scan):
                page = doc[page_num]
                text = page.get_text()
                lines = text.split("\n")
                for line in lines:
                    line = str(line or "").strip()
                    if not line:
                        continue

                    combined_full_match = re.match(r"^(\d+)\s*\(([a-d])\)\s*\(([ivx]{1,5})\)", line, re.IGNORECASE)
                    if combined_full_match:
                        q_num = int(combined_full_match.group(1))
                        sub1 = combined_full_match.group(2).lower()
                        sub2 = combined_full_match.group(3).lower()
                        if 1 <= q_num <= 50:
                            current_main = q_num
                            if q_num not in questions:
                                questions[q_num] = {"subquestions": []}
                            full_sub = f"{sub1}{sub2}"
                            if full_sub not in questions[q_num]["subquestions"]:
                                questions[q_num]["subquestions"].append(full_sub)
                            if sub1 not in questions[q_num]["subquestions"]:
                                questions[q_num]["subquestions"].append(sub1)
                            continue

                    simple_combined_match = re.match(r"^(\d+)\s*\(([a-d])\)", line, re.IGNORECASE)
                    if simple_combined_match:
                        q_num = int(simple_combined_match.group(1))
                        sub = simple_combined_match.group(2).lower()
                        if 1 <= q_num <= 50:
                            current_main = q_num
                            if q_num not in questions:
                                questions[q_num] = {"subquestions": []}
                            if sub not in questions[q_num]["subquestions"]:
                                questions[q_num]["subquestions"].append(sub)
                            continue

                    match = re.match(r"^(\d+)\s*[\.\)]?\s*(?=[A-Z]|$|\()", line)
                    if match:
                        q_num = int(match.group(1))
                        if 1 <= q_num <= 50:
                            current_main = q_num
                            if q_num not in questions:
                                questions[q_num] = {"subquestions": []}
                            continue

                    if current_main is None:
                        continue

                    sub_patterns = [
                        (r"^\s*\(([a-d])\)[\.\)]?\s+", "paren_letter"),
                        (r"^\s*\(([ivx]{1,5})\)[\.\)]?\s+", "paren_roman"),
                        (r"^\s*([a-d])[\.\)]\s+", "letter_dot"),
                        (r"^\s*([ivx]{1,5})[\.\)]\s+", "roman_dot"),
                        (r"^\s+([a-d])\)\s+", "space_letter_paren"),
                        (r"^\s+([ivx]{1,5})\)\s+", "space_roman_paren"),
                    ]

                    sub_match = None
                    for pattern, _ptype in sub_patterns:
                        sub_match = re.match(pattern, line, re.IGNORECASE)
                        if sub_match:
                            break

                    if sub_match:
                        sub = sub_match.group(1).lower()
                        if re.match(r"^[a-d]$", sub) or re.match(r"^[ivx]{1,5}$", sub):
                            if sub not in questions[current_main]["subquestions"]:
                                questions[current_main]["subquestions"].append(sub)

            for q_num in questions:
                subs = questions[q_num]["subquestions"]
                letters = [s for s in subs if re.match(r"^[a-d]$", s)]
                combined = [s for s in subs if re.match(r"^[a-d][ivx]+$", s)]
                roman = [s for s in subs if re.match(r"^[ivx]+$", s)]
                letters.sort()
                combined.sort(key=lambda x: (x[0], self._roman_to_int(x[1:])))
                roman.sort(key=lambda x: self._roman_to_int(x))
                questions[q_num]["subquestions"] = letters + combined + roman

            return questions
        except Exception as exc:
            print(f"PDF detection error: {exc}")
            return None
        finally:
            if doc and isinstance(pdf_path_or_doc, str):
                try:
                    doc.close()
                except Exception:
                    pass

    def get_question_list(self, pdf_path_or_doc: Any) -> List[str]:
        structure = self.detect_from_pdf(pdf_path_or_doc)
        if not structure:
            questions = []
            for i in range(1, 11):
                questions.append(f"{i}a")
                questions.append(f"{i}b")
            return questions

        questions: List[str] = []
        for q_num in sorted(structure.keys()):
            subs = structure[q_num]["subquestions"]
            if subs:
                for sub in subs:
                    questions.append(normalize_question_id(f"{q_num}{sub}"))
            else:
                questions.append(normalize_question_id(str(q_num)))

        deduped: List[str] = []
        seen: set[str] = set()
        for q_id in questions:
            if q_id and q_id not in seen:
                deduped.append(q_id)
                seen.add(q_id)
        return deduped


def auto_detect_questions_from_pdf(pdf_path_or_doc: Any) -> List[str]:
    """Auto-detect questions from PDF; returns fallback IDs on failure."""
    try:
        if isinstance(pdf_path_or_doc, str):
            if not FITZ_AVAILABLE:
                print("⚠️ PyMuPDF (fitz) not available; using fallback question IDs.")
                return [f"{i}a" for i in range(1, 11)] + [f"{i}b" for i in range(1, 11)]
            doc = fitz.open(pdf_path_or_doc)
        else:
            doc = pdf_path_or_doc
        detector = PDFQuestionDetector()
        return detector.get_question_list(doc)
    except Exception as exc:
        print(f"Auto-detection error: {exc}")
        return [f"{i}a" for i in range(1, 11)] + [f"{i}b" for i in range(1, 11)]


def check_math_answer(student_answer: Any, correct_answer: Any, tolerance: float = 0.01) -> bool:
    """Check if a math answer is correct."""
    return MathAnswerParser.compare_answers(student_answer, correct_answer, tolerance)


def _check_math_paper_answer_basic(user_answers: Dict[str, Any], answer_key: Dict[str, Any]) -> Dict[str, Any]:
    """Grade an entire paper with basic answer matching."""
    if not answer_key:
        return {
            "total_questions": 0,
            "correct_count": 0,
            "total_marks": 0,
            "earned_marks": 0,
            "percentage": 0,
            "question_results": {},
        }

    question_results: Dict[str, Dict[str, Any]] = {}
    total_marks = 0.0
    earned_marks = 0.0
    correct_count = 0

    normalized_key = normalize_answer_key(answer_key)
    normalized_answers = {normalize_question_id(k): v for k, v in (user_answers or {}).items()}

    for q_id, q_info in normalized_key.items():
        correct_ans = q_info.get("answer", "")
        marks = _coerce_mark_value(q_info.get("marks", 1), default=1.0)
        total_marks += marks
        student_ans = normalized_answers.get(str(q_id), "")
        is_correct = check_math_answer(student_ans, correct_ans)
        earned = marks if is_correct else 0.0
        if is_correct:
            correct_count += 1
        earned_marks += earned
        question_results[str(q_id)] = {
            "student_answer": student_ans,
            "correct_answer": correct_ans,
            "is_correct": is_correct,
            "total_marks": marks,
            "earned_marks": earned,
        }

    percentage = (earned_marks / total_marks * 100.0) if total_marks > 0 else 0.0
    return {
        "total_questions": len(answer_key),
        "correct_count": correct_count,
        "total_marks": total_marks,
        "earned_marks": earned_marks,
        "percentage": percentage,
        "question_results": question_results,
    }


def check_math_paper_answer_ai(
    user_answers: Dict[str, str],
    answer_key: Dict[str, Any],
    subject_code: str = "",
    paper_number: str = "",
    year: str = "",
    question_texts: Optional[Dict[str, str]] = None,
    question_filter: Optional[Set[str]] = None,
    ai_options: Optional[Dict[str, Any] | AIGradingOptions] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> PaperGradingResult:
    """Grade an entire paper using AI grading core."""
    if not is_ai_enabled():
        simple_result = _check_math_paper_answer_basic(user_answers, answer_key)
        return PaperGradingResult(
            total_questions=simple_result.get("total_questions", 0),
            awarded_marks=simple_result.get("earned_marks", 0.0),
            max_marks=simple_result.get("total_marks", 0.0),
            percentage=simple_result.get("percentage", 0.0),
            question_results={
                q_id: GradingResponse(
                    marks=res.get("earned_marks", 0),
                    feedback="Correct" if res.get("is_correct") else "Incorrect",
                    method_award=res.get("earned_marks", 0) if res.get("is_correct") else 0,
                    final_answer_award=res.get("earned_marks", 0) if res.get("is_correct") else 0,
                    is_partial_credit=False,
                    warnings=[],
                )
                for q_id, res in simple_result.get("question_results", {}).items()
            },
            model_answers={},
            grading_errors=["AI grading not available"],
            api_calls_made=0,
            subject_code=subject_code,
            paper_number=paper_number,
            year=year,
        )

    normalized_key = normalize_answer_key(answer_key)
    normalized_answers = {normalize_question_id(k): v for k, v in (user_answers or {}).items()}
    normalized_texts = {normalize_question_id(k): v for k, v in (question_texts or {}).items()}
    normalized_filter = {normalize_question_id(qid) for qid in (question_filter or set()) if normalize_question_id(qid)}

    questions = []
    for q_id, q_info in normalized_key.items():
        if normalized_filter and q_id not in normalized_filter:
            continue
        mark_scheme_text = str(q_info.get("mark_scheme_text", q_info.get("answer", "")) or "")
        questions.append(
            {
                "id": q_id,
                "text": normalized_texts.get(q_id, ""),
                "answer": q_info.get("answer", ""),
                "mark_scheme_text": mark_scheme_text,
                "marks": q_info.get("marks", 1),
            }
        )

    if not questions:
        return PaperGradingResult(
            total_questions=0,
            awarded_marks=0.0,
            max_marks=0.0,
            percentage=0.0,
            question_results={},
            model_answers={},
            grading_errors=[],
            api_calls_made=0,
            subject_code=subject_code,
            paper_number=paper_number,
            year=year,
            ai_quota_exhausted=False,
        )

    opts = _resolve_ai_options(ai_options)
    deadline_ts = None
    if int(opts.max_wall_time_sec) > 0:
        deadline_ts = time.time() + int(opts.max_wall_time_sec)
    effective_max_calls = int(opts.max_ai_calls) if int(opts.max_ai_calls) > 0 else None

    return grade_paper_with_ai(
        questions=questions,
        student_answers=normalized_answers,
        subject_code=subject_code,
        paper_number=paper_number,
        year=year,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        max_calls=effective_max_calls,
        deadline_ts=deadline_ts,
        generate_model_answers=opts.generate_model_answers,
    )


def check_math_paper_answer(
    user_answers: Dict[str, Any],
    answer_key: Dict[str, Any],
    use_ai: bool = False,
    subject_code: str = "",
    paper_number: str = "",
    year: str = "",
    question_texts: Optional[Dict[str, str]] = None,
    ai_options: Optional[Dict[str, Any] | AIGradingOptions] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Grade an entire paper with baseline+AI merge behavior."""
    if not answer_key:
        return {
            "total_questions": 0,
            "correct_count": 0,
            "total_marks": 0,
            "earned_marks": 0,
            "percentage": 0,
            "question_results": {},
            "ai_used": False,
        }

    normalized_key = normalize_answer_key(answer_key)
    normalized_answers = {normalize_question_id(k): v for k, v in (user_answers or {}).items()}
    normalized_texts = {normalize_question_id(k): v for k, v in (question_texts or {}).items()}
    baseline = _check_math_paper_answer_basic(normalized_answers, normalized_key)

    strict_flags: Dict[str, bool] = {}
    base_rows: Dict[str, Dict[str, Any]] = {}
    for q_norm, q_info in normalized_key.items():
        q_marks = _coerce_mark_value(q_info.get("marks", 1), default=1.0)
        strict_required = _is_long_form_written_question(normalized_texts.get(q_norm, ""), q_marks)
        strict_flags[q_norm] = strict_required
        mark_scheme_text = str(q_info.get("mark_scheme_text", q_info.get("answer", "")) or "")

        fallback_row = dict(baseline.get("question_results", {}).get(q_norm, {}))
        fallback_row.setdefault("student_answer", normalized_answers.get(q_norm, ""))
        fallback_row.setdefault("correct_answer", q_info.get("answer", ""))
        fallback_row.setdefault("is_correct", False)
        fallback_row.setdefault("total_marks", q_marks)
        fallback_row.setdefault("earned_marks", 0.0)
        fallback_row.setdefault("feedback", "")
        fallback_row.setdefault("warnings", [])
        fallback_row["total_marks"] = _coerce_mark_value(fallback_row.get("total_marks", q_marks), default=q_marks)
        fallback_row["earned_marks"] = _coerce_mark_value(fallback_row.get("earned_marks", 0.0), default=0.0)
        fallback_row["mark_scheme_text"] = mark_scheme_text
        fallback_row["grading_source"] = "baseline"
        fallback_row["ai_error"] = ""
        fallback_row["model_used"] = ""
        fallback_row["model_fallback_used"] = False
        fallback_row["strict_ai_required"] = strict_required
        fallback_row["manual_review_required"] = bool(fallback_row.get("manual_review_required", False))
        fallback_row["manual_review_status"] = str(fallback_row.get("manual_review_status", "") or "")
        fallback_row["raw_response"] = str(fallback_row.get("raw_response", "") or "")
        fallback_row["parse_status"] = str(fallback_row.get("parse_status", "") or "")
        base_rows[q_norm] = fallback_row

    rule_locked_ids: Set[str] = set()
    for q_norm, base_row in list(base_rows.items()):
        q_info = normalized_key.get(q_norm, {})
        q_marks = _coerce_mark_value(q_info.get("marks", base_row.get("total_marks", 1.0)), default=1.0)
        mark_scheme_text = str(q_info.get("mark_scheme_text", q_info.get("answer", "")) or "")
        student_answer_text = str(normalized_answers.get(q_norm, "") or "")
        question_text = str(normalized_texts.get(q_norm, "") or "")
        rule_result = apply_cambridge_rule_grading(
            subject_code=subject_code,
            paper_number=paper_number,
            question_text=question_text,
            student_answer=student_answer_text,
            mark_scheme_text=mark_scheme_text,
            max_marks=q_marks,
        )
        if not rule_result:
            continue

        merged_rule_row = dict(base_row)
        merged_rule_row["earned_marks"] = max(0.0, min(q_marks, _coerce_mark_value(rule_result.marks, default=0.0)))
        merged_rule_row["method_award"] = max(
            0.0, min(q_marks, _coerce_mark_value(rule_result.method_award, default=0.0))
        )
        merged_rule_row["final_answer_award"] = max(
            0.0, min(q_marks, _coerce_mark_value(rule_result.final_answer_award, default=0.0))
        )
        merged_rule_row["is_partial_credit"] = 0.0 < float(merged_rule_row["earned_marks"]) < float(q_marks)
        merged_rule_row["is_correct"] = (
            float(merged_rule_row["earned_marks"]) >= float(q_marks) and float(q_marks) > 0.0
        )
        merged_rule_row["feedback"] = str(rule_result.feedback or merged_rule_row.get("feedback", "") or "")
        merged_rule_row["warnings"] = list(
            dict.fromkeys(list(merged_rule_row.get("warnings", [])) + list(rule_result.warnings or []))
        )
        merged_rule_row["manual_review_required"] = bool(rule_result.manual_review_required)
        merged_rule_row["manual_review_status"] = (
            "rule_engine_review" if bool(rule_result.manual_review_required) else str(merged_rule_row.get("manual_review_status", "") or "")
        )
        merged_rule_row["parse_status"] = str(rule_result.parse_status or merged_rule_row.get("parse_status", "") or "")
        merged_rule_row["grading_source"] = (
            "rule_engine_math"
            if str(rule_result.rule_type or "").strip().lower() == "math"
            else "rule_engine_science_practical"
        )
        base_rows[q_norm] = merged_rule_row

        high_confidence = float(rule_result.confidence or 0.0) >= 0.72
        if high_confidence and not bool(rule_result.manual_review_required):
            rule_locked_ids.add(q_norm)

    if not use_ai:
        merged = dict(base_rows)
        total_marks = sum(float(v.get("total_marks", 0) or 0) for v in merged.values())
        earned_marks = sum(float(v.get("earned_marks", 0) or 0) for v in merged.values())
        correct_count = sum(1 for v in merged.values() if bool(v.get("is_correct")))
        percentage = (earned_marks / total_marks * 100.0) if total_marks > 0 else 0.0
        return {
            "total_questions": len(merged),
            "correct_count": correct_count,
            "total_marks": total_marks,
            "earned_marks": earned_marks,
            "percentage": percentage,
            "question_results": merged,
            "model_answers": {},
            "api_calls_made": 0,
            "grading_errors": [],
            "ai_used": False,
            "ai_partial": False,
            "ai_applied_count": 0,
            "baseline_fallback_count": 0,
            "short_fallback_count": 0,
            "strict_manual_review_count": 0,
            "ai_failed_count": 0,
            "ai_quota_exhausted": False,
        }

    ai_filter = {qid for qid in base_rows.keys() if qid not in rule_locked_ids}
    ai_result = check_math_paper_answer_ai(
        user_answers=normalized_answers,
        answer_key=normalized_key,
        subject_code=subject_code,
        paper_number=paper_number,
        year=year,
        question_texts=question_texts,
        question_filter=ai_filter,
        ai_options=ai_options,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )

    _dbg(
        f"[DBG-MERGE-HEAD] baseline_earned={baseline.get('earned_marks')} "
        f"ai_errors={ai_result.grading_errors[:3]} ai_q_count={len(ai_result.question_results)}"
    )

    ai_rows: Dict[str, GradingResponse] = {
        normalize_question_id(q_id): res for q_id, res in (ai_result.question_results or {}).items()
    }
    merged_results: Dict[str, Dict[str, Any]] = {}
    ai_quota_exhausted = bool(getattr(ai_result, "ai_quota_exhausted", False))

    for q_norm, base_row in base_rows.items():
        if q_norm in rule_locked_ids:
            merged_results[q_norm] = dict(base_row)
            continue

        strict_required = bool(strict_flags.get(q_norm, False))
        q_info = normalized_key.get(q_norm, {})
        q_marks = _coerce_mark_value(q_info.get("marks", base_row.get("total_marks", 1.0)), default=1.0)
        mark_scheme_text = str(q_info.get("mark_scheme_text", q_info.get("answer", "")) or "")
        student_answer_text = str(normalized_answers.get(q_norm, "") or "")
        is_blank_student_answer = not student_answer_text.strip()
        ai_res = ai_rows.get(q_norm)

        ai_error = ""
        model_used = ""
        model_fallback_used = False
        ai_marks_valid = False
        ai_marks = 0.0
        method_award = 0.0
        final_award = 0.0
        is_partial_credit = False
        warnings: List[str] = []
        feedback = ""
        raw_response = ""
        parse_status = ""
        manual_review_required = False
        manual_review_status = ""

        if ai_res is not None:
            ai_error = str(getattr(ai_res, "error", "") or "")
            model_used = str(getattr(ai_res, "model_used", "") or "")
            model_fallback_used = bool(getattr(ai_res, "model_fallback_used", False))
            warnings = list(getattr(ai_res, "warnings", []) or [])
            feedback = str(getattr(ai_res, "feedback", "") or "")
            raw_response = str(getattr(ai_res, "raw_response", "") or "")
            parse_status = str(getattr(ai_res, "parse_status", "") or "")
            manual_review_required = bool(getattr(ai_res, "manual_review_required", False))
            manual_review_status = parse_status if manual_review_required else ""
            ai_marks_raw = getattr(ai_res, "marks", None)
            ai_marks_valid = isinstance(ai_marks_raw, (int, float)) and math.isfinite(float(ai_marks_raw))
            if ai_marks_valid:
                ai_marks = float(ai_marks_raw)
                ai_marks = max(0.0, min(q_marks, ai_marks))
                method_award = max(0.0, min(ai_marks, _coerce_mark_value(getattr(ai_res, "method_award", 0.0), 0.0)))
                final_award = max(0.0, min(ai_marks, _coerce_mark_value(getattr(ai_res, "final_answer_award", 0.0), 0.0)))
                is_partial_credit = bool(getattr(ai_res, "is_partial_credit", 0.0 < ai_marks < q_marks))

        if ai_error and _is_quota_error_message(ai_error):
            ai_quota_exhausted = True

        if is_blank_student_answer:
            merged_results[q_norm] = {
                "student_answer": student_answer_text,
                "correct_answer": q_info.get("answer", ""),
                "mark_scheme_text": mark_scheme_text,
                "is_correct": False,
                "total_marks": q_marks,
                "earned_marks": 0.0,
                "feedback": feedback or "No answer provided.",
                "method_award": 0.0,
                "final_answer_award": 0.0,
                "is_partial_credit": False,
                "warnings": list(dict.fromkeys(list(warnings) + ["blank_answer"])),
                "grading_source": "blank_response",
                "ai_error": "",
                "model_used": model_used,
                "model_fallback_used": model_fallback_used,
                "strict_ai_required": strict_required,
                "manual_review_required": manual_review_required,
                "manual_review_status": manual_review_status,
                "raw_response": raw_response,
                "parse_status": parse_status or "blank",
            }
            continue

        has_valid_ai = ai_res is not None and (not ai_error) and ai_marks_valid
        if has_valid_ai:
            merged_results[q_norm] = {
                "student_answer": normalized_answers.get(q_norm, ""),
                "correct_answer": q_info.get("answer", ""),
                "mark_scheme_text": mark_scheme_text,
                "is_correct": ai_marks == final_award and ai_marks > 0,
                "total_marks": q_marks,
                "earned_marks": ai_marks,
                "feedback": feedback,
                "method_award": method_award,
                "final_answer_award": final_award,
                "is_partial_credit": is_partial_credit,
                "warnings": warnings,
                "grading_source": "ai",
                "ai_error": "",
                "model_used": model_used,
                "model_fallback_used": model_fallback_used,
                "strict_ai_required": strict_required,
                "manual_review_required": manual_review_required,
                "manual_review_status": manual_review_status,
                "raw_response": raw_response,
                "parse_status": parse_status or "final_mark_line",
            }
            continue

        fail_reason = ""
        if ai_error:
            fail_reason = ai_error
        elif ai_res is None:
            fail_reason = "ai_unavailable" if strict_required else ""
        else:
            fail_reason = "invalid_ai_result"

        fallback = dict(base_row)
        fallback["mark_scheme_text"] = mark_scheme_text
        fallback["model_used"] = model_used
        fallback["model_fallback_used"] = model_fallback_used
        fallback["strict_ai_required"] = strict_required
        fallback["ai_error"] = fail_reason
        fallback["feedback"] = feedback or str(fallback.get("feedback", "") or "")
        fallback["raw_response"] = raw_response
        fallback["parse_status"] = parse_status or str(fallback.get("parse_status", "") or "")
        if warnings:
            fallback["warnings"] = list(dict.fromkeys(list(fallback.get("warnings", [])) + warnings))

        if strict_required or manual_review_required:
            fallback["earned_marks"] = 0.0
            fallback["awarded_marks"] = 0.0
            fallback["is_correct"] = False
            fallback["grading_source"] = "manual_review"
            fallback["manual_review_required"] = True
            fallback["manual_review_status"] = "pending"
            fallback["feedback"] = (
                fallback.get("feedback")
                or "AI grading could not complete; this answer needs manual review."
            )
            fallback["warnings"] = list(dict.fromkeys(list(fallback.get("warnings", [])) + ["strict_ai_unavailable_manual_review"]))
        else:
            fallback["grading_source"] = "baseline"
            fallback["manual_review_required"] = bool(fallback.get("manual_review_required", False))
            fallback["manual_review_status"] = str(fallback.get("manual_review_status", "") or "")

        merged_results[q_norm] = fallback

    ai_applied_count = sum(1 for v in merged_results.values() if v.get("grading_source") == "ai")
    baseline_fallback_count = sum(1 for v in merged_results.values() if v.get("grading_source") == "baseline")
    strict_manual_review_count = sum(
        1 for v in merged_results.values() if bool(v.get("manual_review_required")) and bool(v.get("strict_ai_required"))
    )
    short_fallback_count = sum(
        1 for v in merged_results.values() if v.get("grading_source") == "baseline" and not bool(v.get("strict_ai_required"))
    )
    ai_failed_count = sum(1 for v in merged_results.values() if bool(str(v.get("ai_error", "")).strip()))

    if not ai_quota_exhausted:
        ai_quota_exhausted = any(_is_quota_error_message(str(err)) for err in (ai_result.grading_errors or []))

    total_marks = sum(float(v.get("total_marks", 0) or 0) for v in merged_results.values())
    earned_marks = sum(float(v.get("earned_marks", 0) or 0) for v in merged_results.values())
    correct_count = sum(1 for v in merged_results.values() if bool(v.get("is_correct")))
    percentage = (earned_marks / total_marks * 100.0) if total_marks > 0 else 0.0

    return {
        "total_questions": len(merged_results),
        "correct_count": correct_count,
        "total_marks": total_marks,
        "earned_marks": earned_marks,
        "percentage": percentage,
        "question_results": merged_results,
        "model_answers": {
            normalize_question_id(q_id): {
                "model_answer": ma.model_answer,
                "method_steps": ma.method_steps,
                "key_points": ma.key_points,
            }
            for q_id, ma in (ai_result.model_answers or {}).items()
        },
        "api_calls_made": int(getattr(ai_result, "api_calls_made", 0) or 0),
        "grading_errors": list(getattr(ai_result, "grading_errors", []) or []),
        "ai_used": True,
        "ai_partial": ai_applied_count < len(merged_results),
        "ai_applied_count": ai_applied_count,
        "baseline_fallback_count": baseline_fallback_count,
        "short_fallback_count": short_fallback_count,
        "strict_manual_review_count": strict_manual_review_count,
        "ai_failed_count": ai_failed_count,
        "ai_quota_exhausted": ai_quota_exhausted,
    }


def check_math_answer_ai(
    student_answer: str,
    correct_answer: str,
    max_marks: int = 1,
) -> GradingResponse:
    return grade_with_ai(
        question_id="unknown",
        question_text="",
        student_answer=student_answer,
        correct_answer=correct_answer,
        max_marks=max_marks,
    )


def is_ai_configured() -> bool:
    """Check if AI is configured for Groq inference."""
    if not is_ai_enabled():
        return False
    try:
        config = get_ai_config()
        is_valid, _error_msg = config.validate()
        return bool(is_valid)
    except Exception:
        return False


def get_grader() -> UnifiedAIGrader:
    if not is_ai_enabled():
        raise RuntimeError("Groq is not configured in environment")
    return UnifiedAIGrader()


# ============================================================================
# Math Cleaning/Parsing Helpers (Integrated from legacy math module)
# ============================================================================


def _normalize_math_symbol_tokens(text: str) -> str:
    out = str(text or "")
    out = _SUPERSCRIPT_RUN_PATTERN.sub(
        lambda match: "^" + str(match.group(0)).translate(_SUPERSCRIPT_TRANSLATION),
        out,
    )
    out = out.translate(_SUBSCRIPT_TRANSLATION)
    out = out.replace("×", "*")
    out = out.replace("÷", "/")
    out = out.replace("−", "-")
    out = out.replace("–", "-")
    out = out.replace("—", "-")
    out = out.replace("⁄", "/")
    out = re.sub(r"([A-Za-z])([0-9]+)([+\-])", r"\1^\2\3", out)
    return out


def _apply_standard_math_text_cleaning(text: Any) -> str:
    out = str(text or "")
    out = _normalize_math_symbol_tokens(out)
    return out.strip()


def normalize_for_grading(text: Any) -> str:
    return _apply_standard_math_text_cleaning(text)


def preprocess_mark_scheme(text: Any) -> str:
    out = str(text or "")
    out = _normalize_math_symbol_tokens(out)
    out = _UNICODE_BULLET_PATTERN.sub("", out)
    return "\n".join(line.rstrip() for line in out.splitlines())
