"""
Exam Mode Module for Past Paper Studio (PySide6)
"""

from __future__ import annotations

import logging
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from Core.download_service import download_pdf, fetch_bytes
from Core.runtime_tuning import file_buffer_size_bytes
from Core.pdf_service import isolated_pdf
from Core.background_tasks import run_io
from Core.exam_session import ExamSessionState
from UI.document_geometry import backing_scale, MAX_BACKING_PIXELS, local_point, snapped_angle, ruler_tick_step
try:
    import shiboken6
except Exception:  # pragma: no cover - optional runtime dependency fallback
    shiboken6 = None  # type: ignore[assignment]
from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, QPoint, QPointF, QRect, QRectF, QSize, QStringListModel, Qt, QTimer, QObject, Signal, QThread, QUrl, QSettings, QStandardPaths
from PySide6.QtGui import QAction, QBrush, QColor, QCursor, QDesktopServices, QTextCharFormat, QTextCursor, QTextDocument, QFont, QImage, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPaintEvent, QPainterPath, QPen, QPixmap, QPolygonF, QShortcut, QWheelEvent
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QColorDialog, QCompleter, QDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit, QComboBox, QCheckBox, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QMenu, QGraphicsDropShadowEffect, QScrollArea, QFileDialog, QSlider, QStackedWidget, QSizePolicy, QSpinBox, QSplitter, QTextBrowser, QTextEdit, QToolButton, QVBoxLayout, QWidget

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    MULTIMEDIA_AVAILABLE = True
except Exception:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    MULTIMEDIA_AVAILABLE = False

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except Exception:
    WEBENGINE_AVAILABLE = False

try:
    from Core import pdf_service as fitz  # PyMuPDF
    PDF_AVAILABLE = True
except Exception:
    PDF_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except Exception:
    PDFPLUMBER_AVAILABLE = False

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:
    Image = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

from Utils.gui_utils import (
    Colors,
    ConfigManager,
    ExamAttemptManager,
    LoadingDialog,
    load_groq_api_key,
    load_groq_text_model,
    load_groq_vision_model,
    is_groq_configured,
    groq_missing_warning_message,
    should_show_groq_startup_warning,
    save_groq_settings,
    show_download_complete_dialog,
    show_error,
    show_info,
    show_warning,
)
from Data.exam_data import (
    get_exam_duration,
    get_mcq_count,
    get_paper_type_from_subject,
    parse_duration_minutes_from_front_page_text,
    parse_total_marks_from_front_page_text,
)
from Data.paper_structures import (
    extract_paper_code,
    get_paper_structure,
    generate_question_ids_from_structure,
    calculate_marks_from_structure,
)
from Grading.ai_grading import (
    AIGradingOptions,
    check_math_answer,
    check_math_paper_answer,
    get_answer_key,
    is_ai_grading_available,
    is_ai_configured,
    should_use_ai_grading,
    auto_detect_questions_from_pdf,
    normalize_question_id,
    format_question_id_display,
    grade_drawing_question,
)
from Grading.math_paper_extractor import extract_math_mark_scheme, is_math_subject_code
from Grading.paper_choice_resolver import parse_choice_structure, resolve_choice_selection
from Grading.grade_threshold_service import interpret_grade_thresholds
from Utils.question_id_mapper import (
    QuestionIDMapper,
    MappingReport,
    QuestionLeaf,
    parse_question_id,
    normalize_question_id_canonical,
    format_question_display,
)
from Core.paper_mode_router import PaperModeDecision, resolve_mode
from Data.subjects_structure import infer_exam_year
from Utils.unified_question_extractor import UnifiedQuestionExtractor, detect_section_type
from UI.scientific_calculator import ScientificCalculatorWidget
from UI.static_theme_surface import StaticThemeSurface
from Utils.periodic_locator import find_periodic_table_page, build_page_snippets
from Grading.grading_reporter import write_grading_report
from UI.floating_settings_window import FloatingSettingsWindow
from UI.font_system import DEFAULT_FONT_OPTION, discover_available_ui_fonts, sanitize_font_choice
from UI.theme import get_theme_manager, ThemeManager
from Data.user_documentation import build_user_documentation_markdown
from Core.ocr_service import ocr_image_to_data

# ---------------------------------------------------------------------------
# Grading Debug and Warning Helpers
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

_AUDIO_STREAM_BASE_URL = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
_AUDIO_STREAM_BASE_URLS = [
    "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload",
    "https://pastpapers.co/cie/files",
    "https://www.pastpapers.co/cie/files",
]
_AUDIO_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "audio/*,*/*;q=0.8",
}
_FILE_BUFFER_BYTES = file_buffer_size_bytes()


def _input_border_color() -> str:
    base = _mix_hex(str(Colors.PRIMARY_HOVER), str(Colors.ACCENT_CYAN), 0.42)
    return _mix_hex(base, str(Colors.BG_MEDIUM), 0.36)


def _input_focus_glow_color() -> str:
    return _mix_hex(_input_border_color(), Colors.TEXT_WHITE, 0.24)


def _contrast_text_for_bg(bg_hex: str) -> str:
    return Colors.contrast_text_for_bg(bg_hex)


def _mix_hex(start_hex: str, end_hex: str, ratio: float) -> str:
    start = QColor(str(start_hex or "#000000"))
    end = QColor(str(end_hex or "#000000"))
    t = max(0.0, min(1.0, float(ratio)))
    red = int(start.red() + (end.red() - start.red()) * t)
    green = int(start.green() + (end.green() - start.green()) * t)
    blue = int(start.blue() + (end.blue() - start.blue()) * t)
    return QColor(red, green, blue).name().upper()


def _relative_luminance(color_hex: str) -> float:
    color = QColor(str(color_hex or "#000000"))
    if not color.isValid():
        color = QColor("#000000")

    def _srgb_to_linear(channel: int) -> float:
        value = max(0.0, min(255.0, float(channel))) / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    r = _srgb_to_linear(color.red())
    g = _srgb_to_linear(color.green())
    b = _srgb_to_linear(color.blue())
    return (0.2126 * r) + (0.7152 * g) + (0.0722 * b)


def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l_fg = _relative_luminance(fg_hex)
    l_bg = _relative_luminance(bg_hex)
    lighter = max(l_fg, l_bg)
    darker = min(l_fg, l_bg)
    return (lighter + 0.05) / (darker + 0.05)


def _muted_text_for_bg(bg_hex: str) -> str:
    return _mix_hex(_contrast_text_for_bg(bg_hex), bg_hex, 0.45)


def _input_surface_bg() -> str:
    base = str(Colors.BG_LIGHT)
    tint = _mix_hex(str(Colors.ACCENT_CYAN), str(Colors.BG_MEDIUM), 0.45)
    target = _mix_hex(base, tint, 0.05)
    return _mix_hex(target, str(Colors.BG_CARD), 0.16)

_GRADING_DEBUG = str(os.getenv("GRADING_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}


def _dbg(message: str) -> None:
    if _GRADING_DEBUG:
        print(message)


def _is_quota_error_message(message: str) -> bool:
    text = (message or "").lower()
    if not text:
        return False
    quota_hints = (
        "429",
        "resource_exhausted",
        "quota exceeded",
        "quota_exceeded",
        "quota",
        "rate limit",
        "rate-limit",
        "insufficient_quota",
        "generate_content_free_tier",
    )
    return any(hint in text for hint in quota_hints)


def _summarize_grading_warning(errors: List[str]) -> str:
    if not errors:
        return ""
    for err in errors:
        text = str(err).strip()
        if "budget reached" in text.lower():
            return text if len(text) <= 220 else f"{text[:220]}..."
    if any(_is_quota_error_message(err) for err in errors):
        return "AI quota exceeded; grading continued with baseline fallback."
    first = str(errors[0]).strip()
    return first if len(first) <= 220 else f"{first[:220]}..."


def _is_placeholder_answer(answer: Any) -> bool:
    text = str(answer or "").strip().lower()
    if not text:
        return True
    placeholders = (
        "[see mark scheme]",
        "see mark scheme",
        "refer to mark scheme",
        "answers will vary",
        "varied answers",
        "n/a",
    )
    return any(p in text for p in placeholders)


_OPTIONAL_CHOICE_HINTS = (
    "answer one",
    "choose one",
    "choose any one",
    "either",
    "one of the following",
    "select one",
    "write about one",
)


def _is_optional_choice_question(question_text: str, subject_code: str = "", paper_num: Any = "") -> bool:
    text = str(question_text or "").strip().lower()
    if not text:
        return False
    if any(h in text for h in _OPTIONAL_CHOICE_HINTS):
        return True

    subj = str(subject_code or "").strip()
    paper = str(paper_num or "").strip()

    # English First Language writing prompts frequently provide multiple options.
    if subj == "0500" and paper.startswith("2"):
        style_hints = ("descriptive", "narrative", "argumentative", "composition", "write")
        if any(h in text for h in style_hints):
            return True

    return False


# ---------------------------------------------------------------------------
# Drawing Detection
# ---------------------------------------------------------------------------

DRAWING_PATTERNS: List[Tuple[re.Pattern[str], float, str]] = [
    (re.compile(r"\bdraw\b", re.IGNORECASE), 0.75, "contains 'draw'"),
    (re.compile(r"\bsketch\b", re.IGNORECASE), 0.75, "contains 'sketch'"),
    (re.compile(r"\bplot\b", re.IGNORECASE), 0.8, "contains 'plot'"),
    (re.compile(r"\bgraph\b", re.IGNORECASE), 0.7, "contains 'graph'"),
    (re.compile(r"\bdiagram\b", re.IGNORECASE), 0.75, "contains 'diagram'"),
    (re.compile(r"\bdot[-\s]*and[-\s]*cross\b", re.IGNORECASE), 0.95, "contains 'dot-and-cross'"),
    (re.compile(r"\bdot[-\s]*cross\b", re.IGNORECASE), 0.9, "contains 'dot-cross'"),
    (re.compile(r"\belectron(?:ic)?\s+configuration\b", re.IGNORECASE), 0.75, "contains 'electron configuration'"),
    (re.compile(r"\bionic\s+bond(?:ing)?\b", re.IGNORECASE), 0.7, "contains 'ionic bonding'"),
    (re.compile(r"\blabel(?:led)?\b", re.IGNORECASE), 0.6, "contains 'label'"),
    (re.compile(r"\bconstruct\b", re.IGNORECASE), 0.75, "contains 'construct'"),
    (re.compile(r"show\s+on\s+the\s+grid", re.IGNORECASE), 0.85, "contains 'show on the grid'"),
    (re.compile(r"complete\s+the\s+graph", re.IGNORECASE), 0.8, "contains 'complete the graph'"),
]

TABLE_PATTERNS: List[Tuple[re.Pattern[str], float, str]] = [
    (re.compile(r"\bcomplete\b.{0,60}\btable\b", re.IGNORECASE), 0.9, "contains 'complete ... table'"),
    (re.compile(r"\bfill(?:\s+in)?\b.{0,60}\btable\b", re.IGNORECASE), 0.9, "contains 'fill ... table'"),
    (re.compile(r"\btick\b.{0,60}\btable\b", re.IGNORECASE), 0.85, "contains 'tick ... table'"),
    (re.compile(r"\btick\b.{0,24}\bbox(?:es)?\b", re.IGNORECASE), 0.85, "contains 'tick ... box(es)'"),
    (re.compile(r"\bput\s+a\s+tick\b", re.IGNORECASE), 0.8, "contains 'put a tick'"),
    (re.compile(r"table\s+below", re.IGNORECASE), 0.7, "contains 'table below'"),
    (re.compile(r"in\s+the\s+table", re.IGNORECASE), 0.45, "contains 'in the table'"),
]


_GRAPH_WORD_PATTERN = re.compile(r"\bgraph\b", re.IGNORECASE)
_TABLE_WORD_PATTERN = re.compile(r"\btable\b", re.IGNORECASE)
_TICK_INTENT_PATTERN = re.compile(r"\btick\b|\bcheck\s*mark\b|\bcheck\b.{0,24}\bbox(?:es)?\b", re.IGNORECASE)


def _table_intent_score(question_text: str) -> Tuple[float, List[str]]:
    text = str(question_text or "")
    if not text.strip():
        return 0.0, []
    score = 0.0
    reasons: List[str] = []
    for pattern, weight, reason in TABLE_PATTERNS:
        if pattern.search(text):
            score += weight
            reasons.append(reason)
    if _TABLE_WORD_PATTERN.search(text):
        score += 0.15
        reasons.append("contains 'table'")
    return min(1.0, score), reasons


def _has_tick_intent(question_text: str) -> bool:
    return bool(_TICK_INTENT_PATTERN.search(str(question_text or "")))


def detect_response_type(question_text: str, threshold: float = 0.7) -> Tuple[str, float, str]:
    """Infer expected response type from question text."""
    text = (question_text or "").strip()
    if not text:
        return "text", 0.0, "empty question text"

    draw_score = 0.0
    draw_reasons: List[str] = []
    table_score, table_reasons = _table_intent_score(text)
    has_graph_word = bool(_GRAPH_WORD_PATTERN.search(text))
    has_table_word = bool(_TABLE_WORD_PATTERN.search(text))

    for pattern, weight, reason in DRAWING_PATTERNS:
        if pattern.search(text):
            draw_score += weight
            draw_reasons.append(reason)

    if has_graph_word and has_table_word:
        draw_score += 0.25
        draw_reasons.append("contains graph+table context")
    if re.search(r"\bdiagram\b", text, re.IGNORECASE) and re.search(r"\blabel(?:led)?\b", text, re.IGNORECASE):
        draw_score += 0.2
        draw_reasons.append("contains diagram+label context")

    draw_confidence = min(1.0, draw_score)
    table_confidence = min(1.0, table_score)

    # If graph language is present, keep drawing mode even with table cues.
    if draw_confidence >= threshold:
        return "drawing", draw_confidence, "; ".join(draw_reasons) or "drawing keywords detected"
    if table_confidence >= threshold and not has_graph_word:
        return "table", table_confidence, "; ".join(table_reasons) or "table keywords detected"

    if draw_confidence > 0:
        return "text", draw_confidence, "; ".join(draw_reasons)
    if table_confidence > 0:
        return "text", table_confidence, "; ".join(table_reasons)
    return "text", 0.0, "no strong drawing/table keywords"


# ---------------------------------------------------------------------------
# Question Text Extraction
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExtractionResult:
    question_ids_leaf: List[str] = field(default_factory=list)
    question_texts: Dict[str, str] = field(default_factory=dict)
    question_mark_hints: Dict[str, float] = field(default_factory=dict)
    question_pages: Dict[str, int] = field(default_factory=dict)
    hierarchy_tree: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    question_items: List[QuestionLeaf] = field(default_factory=list)
    debug_events: List[str] = field(default_factory=list)
    confidence_summary: Dict[str, float] = field(default_factory=dict)


class QuestionTextExtractor:
    """Extract hierarchical question structures from Cambridge-style PDFs."""

    MAX_MAIN_QUESTION = 40
    ROMAN_SET = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}

    def __init__(self):
        self.debug_logs: List[str] = []

    def extract_questions_from_pdf(self, pdf_path: str, max_pages: int = 50) -> Dict[str, str]:
        """Backward-compatible wrapper returning only question text map."""
        return self.extract_with_structure(pdf_path, max_pages=max_pages).question_texts

    @isolated_pdf
    def extract_with_structure(self, pdf_path: str, max_pages: int = 50) -> ExtractionResult:
        if not PDF_AVAILABLE:
            self._log("PyMuPDF not available for text extraction")
            return ExtractionResult()

        self.debug_logs = []
        doc = None
        try:
            doc = fitz.open(pdf_path)
            best_result = ExtractionResult()
            best_tokens: List[Dict[str, Any]] = []

            base_candidates = [
                ("fitz_dict", lambda: self._collect_line_tokens(doc, max_pages)),
                ("fitz_words", lambda: self._collect_line_tokens_words(doc, max_pages)),
            ]
            for candidate_name, collect in base_candidates:
                candidate_tokens = collect()
                parsed = self._parse_candidate_tokens(candidate_name, candidate_tokens)
                if not parsed:
                    continue
                if self._prefer_candidate(best_result, parsed):
                    best_result = parsed
                    best_tokens = list(candidate_tokens)

            if self._should_use_ocr_fallback(best_result):
                self._log("Primary extraction low-confidence; trying OCR fallback candidates")
                deep_candidates = [
                    (
                        "ocr_paddle_fast",
                        lambda: self._collect_line_tokens_ocr_raster(
                            doc,
                            max_pages,
                            scales=(2.0,),
                            include_autocontrast=False,
                        ),
                    ),
                    (
                        "ocr_paddle_enhanced",
                        lambda: self._collect_line_tokens_ocr_raster(
                            doc,
                            max_pages,
                            scales=(2.0, 2.8),
                            include_autocontrast=True,
                        ),
                    ),
                    ("pdfplumber", lambda: self._collect_line_tokens_pdfplumber(pdf_path, max_pages)),
                ]
                for candidate_name, collect in deep_candidates:
                    if not self._should_use_ocr_fallback(best_result):
                        break
                    candidate_tokens = collect()
                    parsed = self._parse_candidate_tokens(candidate_name, candidate_tokens)
                    if not parsed:
                        continue
                    if self._prefer_candidate(best_result, parsed):
                        best_result = parsed
                        best_tokens = list(candidate_tokens)

            if self._should_use_ocr_fallback(best_result):
                recovered = self._recover_minimal_main_result(best_tokens)
                if recovered and self._prefer_candidate(best_result, recovered):
                    best_result = recovered
                    self._log(
                        f"Low-confidence recovery selected ({len(best_result.question_ids_leaf)} main-question leaves)"
                    )

            self._log(f"Extracted {len(best_result.question_ids_leaf)} leaf questions")
            return best_result
        except Exception as e:
            self._log(f"Error extracting question structure: {e}")
            return ExtractionResult(debug_events=list(self.debug_logs))
        finally:
            if doc is not None:
                doc.close()

    @staticmethod
    def _should_use_ocr_fallback(result: ExtractionResult) -> bool:
        leaf_count = len(getattr(result, "question_ids_leaf", []) or [])
        confidence = getattr(result, "confidence_summary", {}) or {}
        marker_accept = float(confidence.get("marker_acceptance", 0.0) or 0.0)
        overall = float(confidence.get("overall", 0.0) or 0.0)
        if leaf_count < 3:
            return True
        if marker_accept < 0.42:
            return True
        if overall < 0.4:
            return True
        return False

    @staticmethod
    def _result_quality_score(result: Optional[ExtractionResult]) -> float:
        if not result:
            return 0.0
        confidence = getattr(result, "confidence_summary", {}) or {}
        marker_accept = float(confidence.get("marker_acceptance", 0.0) or 0.0)
        overall = float(confidence.get("overall", 0.0) or 0.0)
        leaf_count = len(getattr(result, "question_ids_leaf", []) or [])
        count_score = min(1.0, float(leaf_count) / 45.0)
        return (0.50 * marker_accept) + (0.35 * overall) + (0.15 * count_score)

    @classmethod
    def _prefer_candidate(cls, current: ExtractionResult, challenger: ExtractionResult) -> bool:
        current_count = len(getattr(current, "question_ids_leaf", []) or [])
        challenger_count = len(getattr(challenger, "question_ids_leaf", []) or [])
        if challenger_count <= 0:
            return False
        if current_count <= 0:
            return True

        current_conf = getattr(current, "confidence_summary", {}) or {}
        challenger_conf = getattr(challenger, "confidence_summary", {}) or {}
        current_accept = float(current_conf.get("marker_acceptance", 0.0) or 0.0)
        challenger_accept = float(challenger_conf.get("marker_acceptance", 0.0) or 0.0)

        if challenger_count > current_count:
            return True
        if challenger_count >= max(1, current_count - 2) and challenger_accept >= current_accept + 0.08:
            return True

        current_score = cls._result_quality_score(current)
        challenger_score = cls._result_quality_score(challenger)
        if challenger_count >= max(1, int(current_count * 0.7)) and challenger_score >= current_score + 0.12:
            return True
        return False

    def _parse_candidate_tokens(self, candidate_name: str, tokens: List[Dict[str, Any]]) -> Optional[ExtractionResult]:
        if not tokens:
            self._log(f"{candidate_name}: 0 tokens")
            return None
        parsed = self._parse_tokens(tokens)
        confidence = getattr(parsed, "confidence_summary", {}) or {}
        marker_accept = float(confidence.get("marker_acceptance", 0.0) or 0.0)
        overall = float(confidence.get("overall", 0.0) or 0.0)
        quality = self._result_quality_score(parsed)
        self._log(
            f"{candidate_name}: leaves={len(parsed.question_ids_leaf)} marker_accept={marker_accept:.3f} "
            f"overall={overall:.3f} score={quality:.3f}"
        )
        return parsed

    def _collect_line_tokens(self, doc, max_pages: int) -> List[Dict[str, Any]]:
        tokens: List[Dict[str, Any]] = []
        pages_to_scan = min(len(doc), max_pages)
        for page_num in range(pages_to_scan):
            page = doc[page_num]
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    raw_text = "".join(span.get("text", "") for span in spans).strip()
                    if not raw_text:
                        continue
                    x0 = min(span.get("bbox", [0, 0, 0, 0])[0] for span in spans)
                    y0 = min(span.get("bbox", [0, 0, 0, 0])[1] for span in spans)
                    avg_size = sum(span.get("size", 0.0) * max(1, len(span.get("text", ""))) for span in spans)
                    avg_size /= max(1, sum(max(1, len(span.get("text", ""))) for span in spans))
                    tokens.append(
                        {
                            "page": page_num,
                            "x": float(x0),
                            "y": float(y0),
                            "page_w": page_w,
                            "page_h": page_h,
                            "raw": raw_text,
                            "text": self._clean_text(raw_text),
                            "font_size": float(avg_size),
                        }
                    )
        tokens.sort(key=lambda t: (t["page"], t["y"], t["x"]))
        return tokens

    def _collect_line_tokens_words(self, doc, max_pages: int) -> List[Dict[str, Any]]:
        tokens: List[Dict[str, Any]] = []
        pages_to_scan = min(len(doc), max_pages)
        for page_num in range(pages_to_scan):
            page = doc[page_num]
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)
            try:
                words = page.get_text("words", sort=True)
            except Exception:
                words = []
            if not words:
                continue

            line_map: Dict[Tuple[int, int], Dict[str, Any]] = {}
            for word in words:
                try:
                    x0, y0, _x1, _y1, raw, block_no, line_no, _word_no = word
                except Exception:
                    continue
                cleaned = self._clean_text(str(raw or ""))
                if not cleaned:
                    continue
                key = (int(block_no), int(line_no))
                slot = line_map.setdefault(
                    key,
                    {
                        "x": float(x0),
                        "y": float(y0),
                        "parts": [],
                    },
                )
                slot["x"] = min(float(slot.get("x", x0)), float(x0))
                slot["y"] = min(float(slot.get("y", y0)), float(y0))
                slot["parts"].append(cleaned)

            for slot in line_map.values():
                joined = self._clean_text(" ".join(slot.get("parts", [])))
                if not joined:
                    continue
                tokens.append(
                    {
                        "page": page_num,
                        "x": float(slot.get("x", 0.0)),
                        "y": float(slot.get("y", 0.0)),
                        "page_w": page_w,
                        "page_h": page_h,
                        "raw": joined,
                        "text": joined,
                        "font_size": 10.0,
                    }
                )

        tokens.sort(key=lambda t: (t["page"], t["y"], t["x"]))
        return tokens

    def _collect_line_tokens_ocr_raster(
        self,
        doc,
        max_pages: int,
        *,
        scales: Tuple[float, ...] = (2.0,),
        include_autocontrast: bool = False,
    ) -> List[Dict[str, Any]]:
        tokens: List[Dict[str, Any]] = []
        scale_values = tuple(
            float(scale)
            for scale in (scales or ())
            if isinstance(scale, (int, float)) and float(scale) > 0.2
        )
        if not scale_values:
            scale_values = (2.0,)

        pages_to_scan = min(len(doc), max_pages)
        for page_num in range(pages_to_scan):
            page = doc[page_num]
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)
            tokens.extend(
                self._collect_page_tokens_from_ocr_raster(
                    page,
                    page_num,
                    page_w,
                    page_h,
                    scales=scale_values,
                    include_autocontrast=include_autocontrast,
                )
            )
        tokens.sort(key=lambda t: (t["page"], t["y"], t["x"]))
        return tokens

    def _collect_line_tokens_ocr(self, doc, max_pages: int) -> List[Dict[str, Any]]:
        tokens = self._collect_line_tokens_ocr_raster(
            doc,
            max_pages,
            scales=(2.0,),
            include_autocontrast=False,
        )
        if tokens:
            return tokens
        return self._collect_line_tokens_ocr_raster(
            doc,
            max_pages,
            scales=(2.0, 2.8),
            include_autocontrast=True,
        )

    @staticmethod
    def _ocr_binary_threshold(image: Any) -> int:
        try:
            histogram = list(image.histogram() or [])
        except Exception:
            histogram = []
        if len(histogram) < 256:
            return 160
        total = sum(int(count) for count in histogram[:256])
        if total <= 0:
            return 160
        weighted = sum(idx * int(count) for idx, count in enumerate(histogram[:256]))
        mean = weighted / max(1, total)
        return max(96, min(192, int(round(mean * 0.92))))

    def _build_ocr_image_variants(
        self,
        base_image: Any,
        *,
        include_autocontrast: bool,
    ) -> List[Tuple[str, Any, float]]:
        variants: List[Tuple[str, Any, float]] = [("base", base_image, 15.0)]
        if not include_autocontrast or ImageOps is None:
            return variants

        try:
            grayscale = ImageOps.autocontrast(ImageOps.grayscale(base_image))
        except Exception:
            return variants

        variants.append(("autocontrast", grayscale.convert("RGB"), 12.0))

        if ImageFilter is not None:
            try:
                sharpened = grayscale.filter(ImageFilter.SHARPEN).convert("RGB")
                variants.append(("sharpened", sharpened, 10.0))
            except Exception:
                pass

        threshold = self._ocr_binary_threshold(grayscale)
        try:
            binary = grayscale.point(lambda px, t=threshold: 255 if px >= t else 0, mode="1").convert("RGB")
            variants.append(("binary", binary, 8.0))
        except Exception:
            pass

        try:
            inverted = ImageOps.invert(grayscale)
            inverted_binary = inverted.point(
                lambda px, t=threshold: 255 if px >= t else 0,
                mode="1",
            ).convert("RGB")
            variants.append(("inverted_binary", inverted_binary, 8.0))
        except Exception:
            pass
        return variants

    @staticmethod
    def _ocr_token_variant_score(token: Dict[str, Any]) -> Tuple[float, int, int]:
        text = re.sub(r"\s+", " ", str(token.get("text", "") or "").strip())
        confidence = float(token.get("ocr_confidence", -1.0) or -1.0)
        alnum_count = sum(1 for ch in text if ch.isalnum())
        return (confidence, alnum_count, len(text))

    @classmethod
    def _prefer_ocr_token_variant(cls, current: Dict[str, Any], challenger: Dict[str, Any]) -> bool:
        return cls._ocr_token_variant_score(challenger) > cls._ocr_token_variant_score(current)

    def _collect_page_tokens_from_ocr_raster(
        self,
        page: Any,
        page_num: int,
        page_w: float,
        page_h: float,
        *,
        scales: Tuple[float, ...] = (2.0,),
        include_autocontrast: bool = False,
    ) -> List[Dict[str, Any]]:
        if Image is None:
            return []
        candidates: Dict[Tuple[int, int], Dict[str, Any]] = {}
        scales_to_try = tuple(
            float(scale)
            for scale in (scales or ())
            if isinstance(scale, (int, float)) and float(scale) > 0.2
        ) or (2.0,)

        for scale in scales_to_try:
            try:
                matrix = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                base_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            except Exception:
                continue

            for _variant_name, image_variant, conf_floor in self._build_ocr_image_variants(
                base_image,
                include_autocontrast=include_autocontrast,
            ):
                try:
                    data = ocr_image_to_data(image_variant, lang="eng")
                except Exception:
                    continue

                line_tokens = self._collect_page_tokens_from_ocr_data(
                    data,
                    scale=scale,
                    page_num=page_num,
                    page_w=page_w,
                    page_h=page_h,
                    conf_floor=conf_floor,
                )
                for token in line_tokens:
                    token_text = self._clean_text(str(token.get("text", "")))
                    if not token_text:
                        continue
                    key = (
                        int(round(float(token.get("x", 0.0)) / 3.0)),
                        int(round(float(token.get("y", 0.0)) / 3.0)),
                    )
                    existing = candidates.get(key)
                    if existing is None:
                        candidates[key] = token
                        continue
                    if self._prefer_ocr_token_variant(existing, token):
                        candidates[key] = token

        return sorted(candidates.values(), key=lambda item: (item["page"], item["y"], item["x"]))

    def _collect_page_tokens_from_ocr_data(
        self,
        data: Dict[str, List[Any]],
        *,
        scale: float,
        page_num: int,
        page_w: float,
        page_h: float,
        conf_floor: float = 15.0,
    ) -> List[Dict[str, Any]]:
        count = len(data.get("text", []) or [])

        def _build_tokens(min_confidence: float) -> List[Dict[str, Any]]:
            lines: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
            for idx in range(count):
                text = self._clean_text(str((data.get("text", []) or [""])[idx]))
                if not text:
                    continue
                try:
                    conf = float((data.get("conf", []) or ["-1"])[idx])
                except Exception:
                    conf = -1.0
                if conf >= 0.0 and conf < float(min_confidence):
                    continue

                left = float((data.get("left", []) or [0])[idx]) / max(0.1, float(scale))
                top = float((data.get("top", []) or [0])[idx]) / max(0.1, float(scale))
                block = int((data.get("block_num", []) or [0])[idx])
                line = int((data.get("line_num", []) or [0])[idx])
                para = int((data.get("par_num", []) or [0])[idx])
                if line <= 0:
                    line = int(round(top / 8.0))

                key = (block, para, line)
                slot = lines.setdefault(
                    key,
                    {
                        "x": left,
                        "y": top,
                        "parts": [],
                        "page": page_num,
                        "page_w": page_w,
                        "page_h": page_h,
                    },
                )
                slot["x"] = min(float(slot.get("x", left)), left)
                slot["y"] = min(float(slot.get("y", top)), top)
                slot["parts"].append((left, text, conf))

            page_tokens: List[Dict[str, Any]] = []
            for slot in lines.values():
                parts = sorted(slot.get("parts", []), key=lambda row: float(row[0]))
                text = self._clean_text(" ".join(str(word) for _, word, _conf in parts))
                if not text:
                    continue
                confidences = [float(conf) for _left, _word, conf in parts if float(conf) >= 0.0]
                avg_conf = sum(confidences) / len(confidences) if confidences else -1.0
                page_tokens.append(
                    {
                        "page": int(slot["page"]),
                        "x": float(slot["x"]),
                        "y": float(slot["y"]),
                        "page_w": float(slot["page_w"]),
                        "page_h": float(slot["page_h"]),
                        "raw": text,
                        "text": text,
                        "font_size": 10.0,
                        "ocr_confidence": avg_conf,
                    }
                )
            page_tokens.sort(key=lambda item: (item["page"], item["y"], item["x"]))
            return page_tokens

        strict_tokens = _build_tokens(float(conf_floor))
        if len(strict_tokens) >= 2 or float(conf_floor) <= 0.0:
            return strict_tokens

        relaxed_floor = 0.0 if float(conf_floor) <= 8.0 else max(0.0, float(conf_floor) - 10.0)
        relaxed_tokens = _build_tokens(relaxed_floor)
        if len(relaxed_tokens) > len(strict_tokens):
            return relaxed_tokens
        return strict_tokens

    def _collect_line_tokens_pdfplumber(self, pdf_path: str, max_pages: int) -> List[Dict[str, Any]]:
        if not PDFPLUMBER_AVAILABLE:
            return []
        tokens: List[Dict[str, Any]] = []
        try:
            with pdfplumber.open(pdf_path) as pdf_doc:
                for page_num, page in enumerate(pdf_doc.pages[:max_pages]):
                    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                    if not words:
                        continue
                    line_map: Dict[int, Dict[str, Any]] = {}
                    for word in words:
                        text = self._clean_text(str(word.get("text", "")))
                        if not text:
                            continue
                        top = float(word.get("top", 0.0) or 0.0)
                        key = int(round(top))
                        slot = line_map.setdefault(
                            key,
                            {
                                "x": float(word.get("x0", 0.0) or 0.0),
                                "y": top,
                                "parts": [],
                            },
                        )
                        slot["x"] = min(float(slot.get("x", 0.0)), float(word.get("x0", 0.0) or 0.0))
                        slot["parts"].append(text)

                    for slot in line_map.values():
                        joined = self._clean_text(" ".join(slot.get("parts", [])))
                        if not joined:
                            continue
                        tokens.append(
                            {
                                "page": page_num,
                                "x": float(slot.get("x", 0.0)),
                                "y": float(slot.get("y", 0.0)),
                                "page_w": float(page.width),
                                "page_h": float(page.height),
                                "raw": joined,
                                "text": joined,
                                "font_size": 10.0,
                            }
                        )
        except Exception:
            return []
        tokens.sort(key=lambda t: (t["page"], t["y"], t["x"]))
        return tokens

    def _recover_minimal_main_result(self, tokens: List[Dict[str, Any]]) -> Optional[ExtractionResult]:
        if not tokens:
            return None
        filtered_tokens = [t for t in tokens if not self._is_header_or_footer_token(t)]
        if not filtered_tokens:
            return None

        threshold = self._derive_main_marker_x_threshold(filtered_tokens)
        ids: List[str] = []
        texts: Dict[str, str] = {}
        mark_hints: Dict[str, float] = {}
        pages: Dict[str, int] = {}
        seen: set[str] = set()
        current_main: Optional[int] = None

        for idx, token in enumerate(filtered_tokens):
            raw_text = str(token.get("text", "") or "").strip()
            if not raw_text:
                continue

            lower = raw_text.lower()
            main_match = self._match_main_marker_text(lower)
            if not main_match:
                continue
            q_num, tail = main_match
            if self._tail_starts_with_sub_marker(tail):
                continue
            if not self._is_likely_main_marker_token(token, threshold):
                continue
            if not self._is_valid_main_number(q_num, current_main):
                continue
            if not self._has_main_context(filtered_tokens, idx, tail):
                continue

            qid = str(q_num)
            if qid in seen:
                current_main = q_num
                continue
            seen.add(qid)
            current_main = q_num
            ids.append(qid)
            pages[qid] = int(token.get("page", 0)) + 1
            if self._has_question_content(tail) or self._has_expression_content(tail):
                cleaned_tail, mark_hint = self._extract_terminal_mark_hint(tail)
                texts[qid] = cleaned_tail or tail
                if isinstance(mark_hint, (int, float)) and float(mark_hint) > 0:
                    mark_hints[qid] = float(mark_hint)
            else:
                texts[qid] = f"Question {format_question_display(qid)}"

        if not ids:
            return None

        recovered = ExtractionResult()
        recovered.question_ids_leaf = ids
        recovered.question_texts = texts
        recovered.question_mark_hints = mark_hints
        recovered.question_pages = pages
        recovered.hierarchy_tree = self._build_hierarchy_tree(ids, pages)
        recovered.question_items = self._build_question_items(ids, texts, pages)
        recovered.debug_events = list(self.debug_logs)
        recovered.confidence_summary = {
            "overall": 0.35,
            "marker_acceptance": 0.45,
            "detected_leaf_count": float(len(ids)),
        }
        return recovered

    def _parse_tokens(self, tokens: List[Dict[str, Any]]) -> ExtractionResult:
        result = ExtractionResult()
        if not tokens:
            result.debug_events = list(self.debug_logs)
            result.confidence_summary = {"overall": 0.0, "coverage": 0.0}
            return result

        marker_events = 0
        accepted_markers = 0

        current_main: Optional[int] = None
        current_part: Optional[str] = None
        current_part_x: Optional[float] = None
        current_leaf: Optional[str] = None

        question_parts: Dict[str, List[str]] = {}
        question_pages: Dict[str, int] = {}
        seen_ids: List[str] = []

        filtered_tokens = [t for t in tokens if not self._is_header_or_footer_token(t)]
        main_marker_x_threshold = self._derive_main_marker_x_threshold(filtered_tokens)
        self._log(
            f"Question parse pass: {len(filtered_tokens)} tokens, main-marker threshold x<={main_marker_x_threshold:.1f}"
        )

        def start_leaf(qid: str, token: Dict[str, Any], initial_text: str = ""):
            nonlocal current_leaf, accepted_markers
            qid_norm = normalize_question_id(qid)
            if not qid_norm:
                return
            current_leaf = qid_norm
            accepted_markers += 1
            if qid_norm not in question_parts:
                question_parts[qid_norm] = []
                seen_ids.append(qid_norm)
                question_pages[qid_norm] = int(token["page"]) + 1
            if initial_text:
                question_parts[qid_norm].append(initial_text)

        for idx, token in enumerate(filtered_tokens):
            text = token["text"]
            if not text:
                continue
            lower = text.lower()

            # Combined markers: 10(a)(ii), 10(a)
            combo_sub = re.match(r"^(\d{1,2})\s*\(([a-z])\)\s*\(([ivx1l]{1,5})\)\s*(.*)$", lower)
            if combo_sub:
                marker_events += 1
                q_num = int(combo_sub.group(1))
                part = combo_sub.group(2)
                sub = self._normalize_roman_subpart_marker(combo_sub.group(3))
                tail = combo_sub.group(4).strip()
                if sub in self.ROMAN_SET and self._is_valid_main_number(q_num, current_main):
                    current_main = q_num
                    current_part = part
                    current_part_x = token["x"]
                    start_leaf(f"{q_num}{part}{sub}", token, tail)
                    self._log(f"Nested marker: {q_num}({part})({sub})")
                    continue

            # OCR variant without parens around the part letter, e.g. 1a(i)
            combo_sub_compact = re.match(r"^(\d{1,2})\s*([a-z])\s*\(([ivx1l]{1,5})\)\s*(.*)$", lower)
            if combo_sub_compact:
                marker_events += 1
                q_num = int(combo_sub_compact.group(1))
                part = combo_sub_compact.group(2)
                sub = self._normalize_roman_subpart_marker(combo_sub_compact.group(3))
                tail = combo_sub_compact.group(4).strip()
                if sub in self.ROMAN_SET and self._is_valid_main_number(q_num, current_main):
                    current_main = q_num
                    current_part = part
                    current_part_x = token["x"]
                    start_leaf(f"{q_num}{part}{sub}", token, tail)
                    self._log(f"Nested marker (compact): {q_num}{part}({sub})")
                    continue

            combo_part = re.match(r"^(\d{1,2})\s*\(([a-z])\)\s*(.*)$", lower)
            if combo_part:
                marker_events += 1
                q_num = int(combo_part.group(1))
                part = combo_part.group(2)
                tail = combo_part.group(3).strip()
                if self._is_valid_main_number(q_num, current_main):
                    current_main = q_num
                    current_part = part
                    current_part_x = token["x"]
                    start_leaf(f"{q_num}{part}", token, tail)
                    self._log(f"Part marker: {q_num}({part})")
                    continue

            combo_part_loose = re.match(r"^(\d{1,2})\s+([a-z])(?:\s+|[.)]\s*)(.*)$", text)
            if combo_part_loose:
                marker_events += 1
                q_num = int(combo_part_loose.group(1))
                part = combo_part_loose.group(2)
                tail = combo_part_loose.group(3).strip()
                if (
                    self._is_valid_main_number(q_num, current_main)
                    and self._is_likely_loose_part_marker_tail(tail)
                    and self._has_main_context(filtered_tokens, idx, tail)
                ):
                    current_main = q_num
                    current_part = part
                    current_part_x = token["x"]
                    start_leaf(f"{q_num}{part}", token, tail)
                    self._log(f"Part marker (loose OCR): {q_num}({part})")
                    continue

            # Main question marker (adaptive margin + monotonic progression)
            main_match = self._match_main_marker_text(lower)
            if main_match:
                _q_num, _tail = main_match
                if self._tail_starts_with_sub_marker(_tail):
                    main_match = None
            if main_match and self._is_likely_main_marker_token(token, main_marker_x_threshold):
                marker_events += 1
                q_num, tail = main_match
                if self._is_valid_main_number(q_num, current_main) and self._has_main_context(
                    filtered_tokens, idx, tail
                ):
                    current_main = q_num
                    current_part = None
                    current_part_x = None
                    # Start a main-level leaf even when tail is empty; if child parts are detected
                    # later, parent leaves are pruned during finalization.
                    start_leaf(
                        str(current_main),
                        token,
                        tail if (self._has_question_content(tail) or self._has_expression_content(tail)) else "",
                    )
                    self._log(f"Main question detected: {current_main} (p{token['page'] + 1})")
                    continue

            # OCR variant: a(i) / a (i) for first subpart line.
            loose_part_sub = re.match(r"^([a-z])\s*\(([ivx1l]{1,5})\)\s*(.*)$", lower)
            if loose_part_sub and current_main is not None:
                marker_events += 1
                part = loose_part_sub.group(1)
                sub = self._normalize_roman_subpart_marker(loose_part_sub.group(2))
                tail = loose_part_sub.group(3).strip()
                if sub in self.ROMAN_SET:
                    current_part = part
                    current_part_x = token["x"]
                    start_leaf(f"{current_main}{part}{sub}", token, tail)
                    self._log(f"Sub-part marker (loose): {current_main}{part}({sub})")
                    continue

            # Standalone (a)/(i) markers
            paren_marker = re.match(r"^\(([a-zivx1l]{1,5})\)\s*(.*)$", lower)
            if paren_marker and current_main is not None:
                marker_events += 1
                raw_marker = str(paren_marker.group(1) or "").strip().lower()
                marker = self._normalize_roman_subpart_marker(raw_marker)
                tail = paren_marker.group(2).strip()
                is_roman = marker in self.ROMAN_SET

                if is_roman and current_part is not None and (
                    current_part_x is None or token["x"] >= current_part_x + 8
                ):
                    start_leaf(f"{current_main}{current_part}{marker}", token, tail)
                    self._log(f"Sub-part marker: {current_main}({current_part})({marker})")
                    continue

                if len(marker) == 1 and marker.isalpha():
                    # Disambiguate (i): if indented under existing part, treat as roman;
                    # otherwise treat as part letter.
                    if marker in self.ROMAN_SET and current_part is not None and (
                        current_part_x is None or token["x"] >= current_part_x + 8
                    ):
                        start_leaf(f"{current_main}{current_part}{marker}", token, tail)
                    else:
                        current_part = marker
                        current_part_x = token["x"]
                        start_leaf(f"{current_main}{current_part}", token, tail)
                    continue

            # Continuation text for current leaf
            if current_leaf and self._is_text_continuation(text):
                if self._is_likely_boundary_to_next_main(
                    token,
                    current_main=current_main,
                    main_marker_x_threshold=main_marker_x_threshold,
                ):
                    self._log(
                        f"Boundary hold: stopped appending to {current_leaf} at token '{text[:48]}' (p{token['page'] + 1})"
                    )
                    continue
                question_parts.setdefault(current_leaf, []).append(text)

        # Finalize texts + remove non-leaf parents
        parent_with_children = set()
        for qid in question_parts.keys():
            parts = parse_question_id(qid)
            if parts.main is not None and parts.part and parts.subpart:
                parent_with_children.add(f"{parts.main}({parts.part})")
            if parts.main is not None and parts.part:
                parent_with_children.add(str(parts.main))
            elif parts.main is not None and parts.subpart:
                parent_with_children.add(str(parts.main))

        final_ids: List[str] = []
        final_texts: Dict[str, str] = {}
        final_hints: Dict[str, float] = {}
        final_pages: Dict[str, int] = {}
        for qid in seen_ids:
            if qid in parent_with_children and any(
                child.startswith(qid) and child != qid for child in question_parts.keys()
            ):
                continue
            text, mark_hint = self._finalize_text(question_parts.get(qid, []))
            final_ids.append(qid)
            final_texts[qid] = text or f"Question {format_question_display(qid)}"
            if isinstance(mark_hint, (int, float)) and float(mark_hint) > 0:
                final_hints[qid] = float(mark_hint)
            final_pages[qid] = question_pages.get(qid, 1)

        result.question_ids_leaf = final_ids
        result.question_texts = final_texts
        result.question_mark_hints = final_hints
        result.question_pages = final_pages
        result.hierarchy_tree = self._build_hierarchy_tree(final_ids, final_pages)
        result.question_items = self._build_question_items(final_ids, final_texts, final_pages)
        result.debug_events = list(self.debug_logs)

        coverage = 0.0
        if marker_events:
            coverage = accepted_markers / marker_events
        overall = min(1.0, 0.35 + (0.65 * min(1.0, len(final_ids) / 45.0)))
        result.confidence_summary = {
            "overall": round(overall, 3),
            "marker_acceptance": round(coverage, 3),
            "detected_leaf_count": float(len(final_ids)),
        }
        return result

    def _derive_main_marker_x_threshold(self, tokens: List[Dict[str, Any]]) -> float:
        if not tokens:
            return 96.0
        page_width = float(tokens[0].get("page_w", 600.0) or 600.0)
        fallback = max(72.0, min(136.0, page_width * 0.18))

        x_candidates: List[float] = []
        for token in tokens:
            matched = self._match_main_marker_text(token.get("text", ""))
            if not matched:
                continue
            q_num, _tail = matched
            if 1 <= int(q_num) <= self.MAX_MAIN_QUESTION:
                x_candidates.append(float(token.get("x", 0.0)))

        if not x_candidates:
            return fallback

        x_candidates.sort()
        baseline = x_candidates[0]
        pivot = x_candidates[int((len(x_candidates) - 1) * 0.35)]
        spread = max(16.0, page_width * 0.03)
        threshold = max(baseline + spread, pivot + 8.0)
        threshold = min(fallback, threshold)
        return max(52.0, threshold)

    @staticmethod
    def _tail_starts_with_sub_marker(tail: str) -> bool:
        sample = str(tail or "").strip().lower()
        if not sample:
            return False
        if re.match(r"^\([a-zivx1l]{1,5}\)", sample):
            return True
        # OCR variant where the part letter loses parentheses: a(i)
        if re.match(r"^[a-z]\s*\([ivx1l]{1,5}\)", sample):
            return True
        return False

    @staticmethod
    def _is_likely_loose_part_marker_tail(tail: str) -> bool:
        sample = str(tail or "").strip()
        if not sample:
            return True
        if sample[0] in {"+", "*", "/", "^", "="}:
            return False
        if re.fullmatch(r"[-+*/^%=().\d\s]+", sample):
            return False
        return True

    def _normalize_roman_subpart_marker(self, marker: str) -> str:
        sample = str(marker or "").strip().lower()
        if not sample:
            return ""
        normalized = sample.replace("1", "i").replace("l", "i")
        if re.fullmatch(r"[ivx]{1,5}", normalized) and normalized in self.ROMAN_SET:
            return normalized
        return sample

    def _match_main_marker_text(self, text: str) -> Optional[Tuple[int, str]]:
        sample = str(text or "").strip().lower()
        if not sample:
            return None
        if re.fullmatch(r"\d{4}", sample):
            return None
        # Avoid algebra terms like "2x + 1" being treated as new question markers.
        if re.match(r"^\d{1,2}[a-z]", sample) and "(" not in sample:
            return None
        match = re.match(r"^(\d{1,2})(?:\s*[.)]\s*|\s+)?(.*)$", sample)
        if not match:
            return None
        q_num = int(match.group(1))
        if q_num < 1 or q_num > self.MAX_MAIN_QUESTION:
            return None
        tail = (match.group(2) or "").strip()
        return q_num, tail

    def _is_likely_main_marker_token(
        self,
        token: Dict[str, Any],
        main_marker_x_threshold: float,
    ) -> bool:
        if not self._match_main_marker_text(token.get("text", "")):
            return False
        x = float(token.get("x", 0.0) or 0.0)
        page_width = float(token.get("page_w", 600.0) or 600.0)
        margin = max(8.0, min(22.0, page_width * 0.03))
        return x <= (float(main_marker_x_threshold) + margin)

    def _is_likely_boundary_to_next_main(
        self,
        token: Dict[str, Any],
        *,
        current_main: Optional[int],
        main_marker_x_threshold: float,
    ) -> bool:
        if current_main is None:
            return False
        if not self._is_likely_main_marker_token(token, main_marker_x_threshold):
            return False
        matched = self._match_main_marker_text(token.get("text", ""))
        if not matched:
            return False
        q_num, _tail = matched
        if q_num <= current_main:
            return False
        return self._is_valid_main_number(q_num, current_main)

    def _has_main_context(self, tokens: List[Dict[str, Any]], idx: int, tail: str) -> bool:
        if tail and (self._has_question_content(tail) or self._has_expression_content(tail)):
            return True
        current = tokens[idx]
        page = current["page"]
        for j in range(idx + 1, min(idx + 8, len(tokens))):
            nxt = tokens[j]
            if nxt["page"] != page:
                break
            text = nxt["text"].lower()
            if re.match(r"^\([a-zivx]{1,5}\)", text):
                return True
            if self._has_question_content(text) or self._has_expression_content(text):
                return True
        return False

    def _is_valid_main_number(self, candidate: int, current_main: Optional[int]) -> bool:
        if candidate < 1 or candidate > self.MAX_MAIN_QUESTION:
            return False
        if current_main is None:
            return True
        return current_main <= candidate <= current_main + 8

    def _build_hierarchy_tree(self, question_ids: List[str], pages: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
        tree: Dict[str, Dict[str, Any]] = {}
        for qid in question_ids:
            parts = parse_question_id(qid)
            if parts.main is None:
                continue
            main_key = str(parts.main)
            main_node = tree.setdefault(main_key, {"page": pages.get(qid, 1), "parts": {}})
            if parts.part:
                part_node = main_node["parts"].setdefault(parts.part, {"page": pages.get(qid, 1), "subparts": []})
                if parts.subpart:
                    if parts.subpart not in part_node["subparts"]:
                        part_node["subparts"].append(parts.subpart)
            elif "_main" not in main_node:
                main_node["_main"] = qid
        return tree

    def _build_question_items(
        self, question_ids: List[str], texts: Dict[str, str], pages: Dict[str, int]
    ) -> List[QuestionLeaf]:
        items: List[QuestionLeaf] = []
        for qid in question_ids:
            parts = parse_question_id(qid)
            question_text = texts.get(qid, "")
            response_type, confidence, reason = detect_response_type(question_text)
            level = 0
            parent_id: Optional[str] = None
            if parts.part:
                level = 1
                parent_id = str(parts.main) if parts.main is not None else None
            if parts.part and parts.subpart:
                level = 2
                parent_id = f"{parts.main}{parts.part}" if parts.main is not None else None
            items.append(
                QuestionLeaf(
                    canonical_id=qid,
                    display_id=format_question_display(qid),
                    main=parts.main,
                    part=parts.part,
                    subpart=parts.subpart,
                    page=pages.get(qid),
                    text=question_text,
                    parent_id=parent_id,
                    level=level,
                    response_type=response_type,
                    requires_manual_review=response_type == "drawing",
                    manual_review_reason=reason if response_type == "drawing" else "",
                    section_type=detect_section_type(question_text, mode="MIXED"),
                )
            )
        return items

    def _is_text_continuation(self, text: str) -> bool:
        if not text:
            return False
        low = text.lower().strip()
        if re.fullmatch(r"\[(?:\d+|total\s*:\s*\d+)\]", low):
            return True
        if re.fullmatch(r"[\d\s\+\-\*/=:\.]+", low) and len(low) <= 3:
            return False
        if re.fullmatch(r"[\\.·]{6,}", low):
            return False
        return True

    def _clean_text(self, text: str) -> str:
        cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text or "")
        cleaned = cleaned.replace("\u00a0", " ")
        cleaned = cleaned.replace("�", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _parse_mark_hint_value(raw_value: str) -> Optional[float]:
        try:
            parsed = int(str(raw_value or "").strip())
        except Exception:
            return None
        if 0 <= parsed <= 25:
            return float(parsed)
        return None

    def _extract_terminal_mark_hint(self, text: str) -> Tuple[str, Optional[float]]:
        sample = str(text or "").strip()
        if not sample:
            return "", None

        # Prefer explicit trailing mark notation used in Cambridge papers.
        explicit_patterns: List[re.Pattern[str]] = [
            re.compile(r"\s*\[\s*(\d{1,2})\s*(?:marks?)?\s*\]\s*$", re.IGNORECASE),
            re.compile(r"\s*\(\s*(\d{1,2})\s*marks?\s*\)\s*$", re.IGNORECASE),
            re.compile(r"\s+\b(\d{1,2})\s*marks?\s*$", re.IGNORECASE),
        ]
        for pattern in explicit_patterns:
            match = pattern.search(sample)
            if not match:
                continue
            hint = self._parse_mark_hint_value(match.group(1))
            if hint is None:
                continue
            stripped = sample[: match.start()].strip()
            return stripped, hint

        # Avoid treating plain trailing "(ii)" / "(a)" as marks.
        return sample, None

    def _finalize_text(self, lines: List[str]) -> Tuple[str, Optional[float]]:
        text = " ".join(x for x in lines if x).strip()
        text = re.sub(r"[\\.·]{8,}", " ", text)
        text = re.sub(r"\bpermission to reproduce items.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[\s*turn over\s*\]\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*\[\s*total\s*:\s*\d+\s*\]\s*$", "", text, flags=re.IGNORECASE)
        text, hint = self._extract_terminal_mark_hint(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text, hint

    def _has_question_content(self, content: str) -> bool:
        if not content:
            return False
        if len(content) < 3:
            return False
        if not re.search(r"[a-z]", content.lower()):
            return False
        if re.search(r"copyright|uc\s*les|cambridge|igcse|a\s*level", content, re.IGNORECASE):
            return False
        return True

    def _has_expression_content(self, content: str) -> bool:
        sample = str(content or "").strip()
        if not sample:
            return False
        if re.fullmatch(r"\d{1,2}", sample):
            return False
        if re.search(r"\d+\.\d+", sample):
            return True
        if re.search(r"[=+\-*/^()%]", sample) and re.search(r"\d", sample):
            return True
        if re.search(r"\b(?:sqrt|sin|cos|tan|log)\b", sample, re.IGNORECASE):
            return True
        return False

    def _is_header_or_footer_token(self, token: Dict[str, Any]) -> bool:
        text = token.get("text", "")
        lower = text.lower()
        x = float(token.get("x", 0))
        y = float(token.get("y", 0))
        page_w = float(token.get("page_w", 600))
        page_h = float(token.get("page_h", 840))

        if y > page_h - 55:
            return True
        if y < 55 and re.fullmatch(r"\d{1,3}", lower) and (page_w * 0.4) <= x <= (page_w * 0.6):
            return True

        skip_patterns = [
            r"^page\s+\d+",
            r"^©\s*\d{4}",
            r"^ucles\s+\d{4}",
            r"^cambridge\b",
            r"^turn\s+over",
            r"^blank\s+page",
            r"^answer\s+all\s+questions",
            r"^write\s+your\s+answer",
            r"^for\s+examiner",
            r"^instructions?\s+to\s+candidates",
            r"^additional\s+materials",
            r"^\d{4}\s*/\s*\d{2}",
            r"^\d{4}/\d{2}",
            r"^\d+\s*(?:hour|minute|min|second)",
            r"^subject\s+code",
            r"^published$",
        ]
        return any(re.match(p, lower) for p in skip_patterns)

    def _log(self, message: str) -> None:
        self.debug_logs.append(message)
        print(f"[QuestionTextExtractor] {message}")


# ---------------------------------------------------------------------------
# PDF Viewer
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PDFRulerState:
    visible: bool = False
    center: QPointF = field(default_factory=lambda: QPointF(0.0, 0.0))
    length_px: float = 360.0
    thickness_px: float = 34.0
    angle_deg: float = 0.0
    pixels_per_mm: float = 72.0 / 25.4


class PDFRulerOverlayWidget(QWidget):
    """Paint-only overlay for the movable ruler guide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._state = PDFRulerState()
        self._interaction_mode: str = ""

    def set_state(self, state: PDFRulerState, interaction_mode: str = "") -> None:
        self._state = PDFRulerState(
            visible=bool(state.visible),
            center=QPointF(float(state.center.x()), float(state.center.y())),
            length_px=float(state.length_px),
            thickness_px=float(state.thickness_px),
            angle_deg=float(state.angle_deg) % 360.0,
            pixels_per_mm=float(state.pixels_per_mm),
        )
        self._interaction_mode = str(interaction_mode or "")
        self.setVisible(bool(self._state.visible))
        if self.isVisible():
            self.update()

    @staticmethod
    def _ruler_handle_local_point(length_px: float) -> QPointF:
        return QPointF((float(length_px) * 0.5) + 24.0, 0.0)

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)
        state = self._state
        if not state.visible:
            return

        length_px = max(1.0, float(state.length_px or 0.0))
        thickness_px = max(16.0, min(96.0, float(state.thickness_px or 0.0)))
        center = QPointF(float(state.center.x()), float(state.center.y()))

        body_base = QColor(240, 244, 248, 205)
        body_border = QColor(_mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.34))
        tick_color = QColor("#111111")
        label_color = QColor("#000000")
        handle_border = QColor(_mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.22))
        handle_fill = QColor(_mix_hex(Colors.BG_LIGHT, Colors.ACCENT_CYAN, 0.16))

        if self._interaction_mode == "drag":
            body_border = QColor(_mix_hex(Colors.ACCENT_CYAN, Colors.TEXT_LIGHT, 0.28))
        elif self._interaction_mode == "rotate":
            handle_border = QColor(_mix_hex(Colors.ACCENT_CYAN, Colors.TEXT_LIGHT, 0.30))
            handle_fill = QColor(_mix_hex(Colors.ACCENT_CYAN, Colors.BG_LIGHT, 0.34))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.translate(center)
        painter.rotate(float(state.angle_deg))

        ruler_rect = QRectF(-length_px * 0.5, -thickness_px * 0.5, length_px, thickness_px)
        painter.setPen(QPen(body_border, 1.6))
        painter.setBrush(QBrush(body_base))
        painter.drawRoundedRect(ruler_rect, 7.0, 7.0)

        tick_pen = QPen(tick_color, 1.0)
        painter.setPen(tick_pen)
        mm_step = ruler_tick_step(state.pixels_per_mm)
        step_px = state.pixels_per_mm * mm_step
        tick_count = int(length_px / step_px)
        for idx in range(tick_count + 1):
            x = ruler_rect.left() + (idx * step_px)
            if x > ruler_rect.right():
                break
            mm = idx * mm_step
            if mm % 10 == 0:
                tick_len = thickness_px * 0.64
            elif mm % 5 == 0:
                tick_len = thickness_px * 0.48
            else:
                tick_len = thickness_px * 0.34
            painter.drawLine(QPointF(x, ruler_rect.top()), QPointF(x, ruler_rect.top() + tick_len))

        label_font = painter.font()
        label_font.setPointSize(max(7, min(11, int(round(thickness_px * 0.3)))))
        painter.setFont(label_font)
        painter.setPen(QPen(label_color, 1.0))
        label_step = max(10, mm_step * 10)
        for mm in range(0, int(length_px / state.pixels_per_mm) + 1, label_step):
            x = ruler_rect.left() + (mm * state.pixels_per_mm)
            if x > ruler_rect.right():
                break
            value = str(mm // 10)
            label_rect = QRectF(x - 9.0, ruler_rect.top() + (thickness_px * 0.52), 18.0, thickness_px * 0.42)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, value)
        painter.drawText(QRectF(ruler_rect.right()-24, ruler_rect.bottom()-15,24,14), 'cm')

        handle_center = self._ruler_handle_local_point(length_px)
        painter.setPen(QPen(handle_border, 1.3))
        painter.drawLine(QPointF(ruler_rect.right(), 0.0), handle_center)
        painter.setBrush(QBrush(handle_fill))
        painter.drawEllipse(handle_center, 11.0, 11.0)
        painter.setPen(QPen(QColor(_contrast_text_for_bg(handle_fill.name())), 1.2))
        painter.drawEllipse(handle_center, 4.0, 4.0)


class PDFCentimeterScaleOverlayWidget(QWidget):
    """Paint-only overlay that shows a zoom-calibrated centimeter scale."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._pixels_per_cm: float = 0.0
        self._span_cm: int = 0

    def set_scale_metrics(self, pixels_per_cm: float, span_cm: int, visible: bool) -> None:
        self._pixels_per_cm = max(0.0, float(pixels_per_cm or 0.0))
        self._span_cm = max(0, int(span_cm or 0))
        should_show = bool(visible) and self._pixels_per_cm > 0.0 and self._span_cm > 0
        self.setVisible(should_show)
        if should_show:
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._pixels_per_cm <= 0.0 or self._span_cm <= 0:
            return

        width = max(1, self.width())
        height = max(1, self.height())
        left_margin = 14.0
        right_margin = 18.0
        bottom_margin = 14.0
        if width <= (left_margin + right_margin + 40.0) or height <= 40:
            return

        px_per_cm = float(self._pixels_per_cm)
        px_per_mm = px_per_cm / 10.0
        total_px = px_per_cm * float(self._span_cm)
        max_total_px = max(0.0, float(width) - left_margin - right_margin)
        if total_px <= 0.0 or max_total_px <= 0.0:
            return
        if total_px > max_total_px:
            total_px = max_total_px

        baseline_y = float(height) - bottom_margin
        start_x = left_margin
        end_x = start_x + total_px

        panel_rect = QRectF(start_x - 8.0, baseline_y - 27.0, total_px + 30.0, 33.0)
        baseline_color = QColor("#000000")
        tick_color = QColor("#000000")
        label_color = QColor("#000000")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Keep the scale readable over both dark and light paper backgrounds.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 170))
        painter.drawRoundedRect(panel_rect, 5.0, 5.0)

        painter.setPen(QPen(baseline_color, 1.4))
        painter.drawLine(QPointF(start_x, baseline_y), QPointF(end_x, baseline_y))

        tick_count = int(round((total_px / max(1e-6, px_per_mm))))
        painter.setPen(QPen(tick_color, 1.0))
        for idx in range(tick_count + 1):
            x = start_x + (float(idx) * px_per_mm)
            if x > (end_x + 0.25):
                break
            if idx % 10 == 0:
                tick_len = 16.0
            elif idx % 5 == 0:
                tick_len = 11.0
            else:
                tick_len = 7.0
            painter.drawLine(QPointF(x, baseline_y), QPointF(x, baseline_y - tick_len))

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(label_color, 1.0))
        for cm in range(self._span_cm + 1):
            x = start_x + (float(cm) * px_per_cm)
            if x > (end_x + 0.25):
                break
            label_rect = QRectF(x - 9.0, baseline_y - 27.0, 18.0, 11.0)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, str(cm))

        unit_rect = QRectF(end_x + 4.0, baseline_y - 15.0, 24.0, 12.0)
        painter.drawText(unit_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "cm")


class ListeningHeader(QWidget):
    """Inline listening-paper audio controls shown inside the PDF controls row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("listeningHeader")
        self._audio_source: str = ""
        self._duration_ms = 0
        self._scrubbing = False
        self._streaming_mode = False
        self._buffer_percent = 0
        self._awaiting_initial_playback = False
        self._is_buffering = False
        self._resume_position_ms: int = 0
        self._manual_prompt_open = False
        self._last_prompted_source = ""
        self._player: Optional[Any] = None
        self._audio_output: Optional[Any] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.play_pause_btn = QPushButton("Play")
        self.play_pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_pause_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_pause_btn.setMinimumWidth(72)

        self.scrub_slider = QSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setRange(0, 0)
        self.scrub_slider.setTracking(True)

        self.buffer_bar = QProgressBar()
        self.buffer_bar.setFixedWidth(120)
        self.buffer_bar.setRange(0, 100)
        self.buffer_bar.setValue(0)
        self.buffer_bar.setFormat("0%")
        self.buffer_bar.setTextVisible(True)
        self.buffer_bar.hide()

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(104)

        self.sound_warning_label = QLabel("⚠️")
        self.sound_warning_label.setObjectName("listeningSoundWarning")
        self.sound_warning_label.setToolTip("Sound is turned off.")
        self.sound_warning_label.setVisible(False)

        layout.addWidget(self.play_pause_btn, 0)
        layout.addWidget(self.scrub_slider, 1)
        layout.addWidget(self.buffer_bar, 0)
        layout.addWidget(self.time_label, 0)
        layout.addWidget(self.sound_warning_label, 0)

        if MULTIMEDIA_AVAILABLE and QMediaPlayer is not None and QAudioOutput is not None:
            try:
                self._audio_output = QAudioOutput(self)
                self._audio_output.setVolume(1.0)
                self._player = QMediaPlayer(self)
                self._player.setAudioOutput(self._audio_output)
                self._player.positionChanged.connect(self._on_position_changed)
                self._player.durationChanged.connect(self._on_duration_changed)
                self._player.playbackStateChanged.connect(self._on_playback_state_changed)
                self._player.mediaStatusChanged.connect(self._on_media_status_changed)
                self._player.bufferProgressChanged.connect(self._on_buffer_progress_changed)
                self._player.errorOccurred.connect(self._on_error_occurred)
            except Exception:
                self._player = None
                self._audio_output = None

        self.play_pause_btn.clicked.connect(self._toggle_play_pause)
        self.scrub_slider.sliderPressed.connect(self._on_slider_pressed)
        self.scrub_slider.sliderReleased.connect(self._on_slider_released)
        self.scrub_slider.sliderMoved.connect(self._on_slider_moved)

        if self._player is None:
            self.play_pause_btn.setEnabled(False)
            self.scrub_slider.setEnabled(False)
            self.time_label.setText("Audio playback unavailable")

        self.apply_runtime_theme()
        self.refresh_sound_state()

    @staticmethod
    def _is_http_source(source: str) -> bool:
        return str(source or "").strip().lower().startswith(("http://", "https://"))

    @staticmethod
    def _looks_like_missing_cdn_asset(error_text: str) -> bool:
        lowered = str(error_text or "").strip().lower()
        return (
            "404" in lowered
            or "not found" in lowered
            or "invalid media" in lowered
            or "resource error" in lowered
        )

    @staticmethod
    def _is_sound_enabled() -> bool:
        return bool(ConfigManager.get_sound_enabled())

    def _to_media_qurl(self, source: str) -> QUrl:
        text = str(source or "").strip()
        if not text:
            return QUrl()
        if self._is_http_source(text) or text.lower().startswith("file://"):
            return QUrl(text)
        try:
            file_url = Path(text).expanduser().resolve().as_uri()
            return QUrl(file_url)
        except Exception:
            return QUrl(text)

    @staticmethod
    def _format_time(ms: int) -> str:
        total_seconds = max(0, int(ms) // 1000)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _set_time_text(self, position_ms: int, duration_ms: int) -> None:
        self.time_label.setText(f"{self._format_time(position_ms)} / {self._format_time(duration_ms)}")

    def _set_buffer_progress(self, percent: int) -> None:
        pct = max(0, min(100, int(percent)))
        self._buffer_percent = pct
        self.buffer_bar.setValue(pct)
        self.buffer_bar.setFormat(f"{pct}%")
        self.buffer_bar.setVisible(bool(self._streaming_mode and self._is_sound_enabled()))

    def _is_playing(self) -> bool:
        if self._player is None or QMediaPlayer is None:
            return False
        try:
            return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        except Exception:
            return False

    def _refresh_play_pause_button(self) -> None:
        sound_on = self._is_sound_enabled()
        self.sound_warning_label.setVisible(not sound_on)
        if not sound_on:
            self.play_pause_btn.setEnabled(False)
            self.play_pause_btn.setText("Play")
            self.scrub_slider.setEnabled(False)
            self.buffer_bar.setVisible(False)
            return
        if self._player is None:
            self.play_pause_btn.setEnabled(False)
            self.play_pause_btn.setText("Play")
            self.scrub_slider.setEnabled(False)
            return
        if not self._audio_source:
            self.play_pause_btn.setEnabled(False)
            self.play_pause_btn.setText("Play")
            self.scrub_slider.setEnabled(False)
            return
        if self._streaming_mode and self._is_buffering:
            self.play_pause_btn.setText("📡 Buffering...")
            self.scrub_slider.setEnabled(True)
            if self._awaiting_initial_playback and self._buffer_percent <= 0:
                self.play_pause_btn.setEnabled(False)
            else:
                self.play_pause_btn.setEnabled(True)
            return
        self.play_pause_btn.setEnabled(True)
        self.scrub_slider.setEnabled(True)
        self.play_pause_btn.setText("Pause" if self._is_playing() else "Play")

    def _on_playback_state_changed(self, _state: object) -> None:
        if self._is_playing():
            self._awaiting_initial_playback = False
            self._is_buffering = False
        self._refresh_play_pause_button()

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        self.scrub_slider.setRange(0, self._duration_ms)
        current = 0
        if self._player is not None:
            try:
                current = int(self._player.position())
            except Exception:
                current = 0
        if self._resume_position_ms > 0 and self._duration_ms > 0 and self._player is not None:
            target = min(self._duration_ms, max(0, int(self._resume_position_ms)))
            try:
                self._player.setPosition(target)
                current = target
            except Exception:
                pass
            self._resume_position_ms = 0
        self._set_time_text(current, self._duration_ms)

    def _on_position_changed(self, position_ms: int) -> None:
        pos = max(0, int(position_ms))
        if not self._scrubbing:
            blocked = self.scrub_slider.blockSignals(True)
            self.scrub_slider.setValue(pos)
            self.scrub_slider.blockSignals(blocked)
        self._set_time_text(pos, self._duration_ms)

    def _on_media_status_changed(self, _status: object) -> None:
        if self._player is None or QMediaPlayer is None:
            return
        try:
            status = self._player.mediaStatus()
        except Exception:
            status = None
        if status in {
            QMediaPlayer.MediaStatus.LoadingMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.StalledMedia,
        } and self._streaming_mode:
            self._is_buffering = True
            self._refresh_play_pause_button()
            return
        if status in {
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.LoadedMedia,
        } and self._streaming_mode:
            self._awaiting_initial_playback = False
            self._is_buffering = False
            if self._buffer_percent < 100:
                self._set_buffer_progress(100)
            self._refresh_play_pause_button()
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._awaiting_initial_playback = False
            self._is_buffering = False
            self._refresh_play_pause_button()
        if status == QMediaPlayer.MediaStatus.InvalidMedia and self._streaming_mode:
            self._on_error_occurred("Invalid media")

    def _on_buffer_progress_changed(self, value: object) -> None:
        if not self._streaming_mode:
            return
        try:
            progress = float(value)
        except Exception:
            progress = 0.0
        percent = int(max(0.0, min(1.0, progress)) * 100.0)
        self._set_buffer_progress(percent)
        if percent > 0:
            self._awaiting_initial_playback = False
        if not self._is_playing() and percent < 100:
            self._is_buffering = True
        elif percent >= 100:
            self._is_buffering = False
        self._refresh_play_pause_button()

    def _on_error_occurred(self, *args: object) -> None:
        error_text = ""
        for arg in args:
            if isinstance(arg, str) and arg.strip():
                error_text = arg.strip()
                break
        if not error_text and self._player is not None:
            try:
                error_text = str(self._player.errorString() or "").strip()
            except Exception:
                error_text = ""
        message = error_text or "Audio stream error."
        self._awaiting_initial_playback = False
        self._is_buffering = False
        self._refresh_play_pause_button()
        if self._streaming_mode and self._looks_like_missing_cdn_asset(message):
            self.time_label.setText("Audio not found on CDN")
            self._prompt_manual_url_entry()
            return
        self.time_label.setText(message)

    def _prompt_manual_url_entry(self) -> None:
        if not self._is_sound_enabled():
            return
        if self._manual_prompt_open:
            return
        source_key = str(self._audio_source or "").strip()
        if source_key and source_key == self._last_prompted_source:
            return
        self._manual_prompt_open = True
        self._last_prompted_source = source_key
        try:
            manual_url, ok = QInputDialog.getText(
                self,
                "Listening Audio",
                "Audio not found on CDN. Enter URL manually?",
            )
        except Exception:
            self._manual_prompt_open = False
            return
        self._manual_prompt_open = False
        if not ok:
            return
        candidate = str(manual_url or "").strip()
        if not candidate:
            return
        self.load_audio_source(candidate)

    def _on_slider_pressed(self) -> None:
        self._scrubbing = True

    def _on_slider_moved(self, position_ms: int) -> None:
        self._set_time_text(int(position_ms), self._duration_ms)

    def _on_slider_released(self) -> None:
        self._scrubbing = False
        if self._player is None:
            return
        try:
            self._player.setPosition(int(self.scrub_slider.value()))
        except Exception:
            pass

    def _toggle_play_pause(self) -> None:
        if (not self._is_sound_enabled()) or self._player is None or not self._audio_source:
            return
        try:
            state = self._player.playbackState()
        except Exception:
            state = None
        is_playing = bool(
            QMediaPlayer is not None
            and state == QMediaPlayer.PlaybackState.PlayingState
        )
        try:
            if is_playing:
                self._player.pause()
            else:
                self._player.play()
        except Exception:
            pass

    def stop_audio(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
        blocked = self.scrub_slider.blockSignals(True)
        self.scrub_slider.setValue(0)
        self.scrub_slider.blockSignals(blocked)
        self._set_time_text(0, self._duration_ms)
        self._set_buffer_progress(0)
        self._awaiting_initial_playback = False
        self._is_buffering = False
        self._resume_position_ms = 0
        self.buffer_bar.hide()
        self.play_pause_btn.setText("Play")
        self._refresh_play_pause_button()

    def clear_audio(self, message: str = "Audio stream unavailable") -> None:
        self.stop_audio()
        self._audio_source = ""
        self._duration_ms = 0
        self._streaming_mode = False
        self._awaiting_initial_playback = False
        self._is_buffering = False
        self._resume_position_ms = 0
        self.scrub_slider.setRange(0, 0)
        self._set_buffer_progress(0)
        self.buffer_bar.hide()
        self.play_pause_btn.setEnabled(False)
        self.scrub_slider.setEnabled(False)
        if self._player is None:
            self.time_label.setText("Audio playback unavailable")
        else:
            self.time_label.setText(str(message or "Audio stream unavailable"))
            try:
                self._player.setSource(QUrl())
            except Exception:
                pass
        self.refresh_sound_state()

    def load_audio_source(self, audio_source: str) -> bool:
        source = str(audio_source or "").strip()
        if not source:
            self.clear_audio("Audio stream URL unavailable")
            return False
        self.stop_audio()
        self._audio_source = source
        self._duration_ms = 0
        self._streaming_mode = self._is_http_source(source)
        self._awaiting_initial_playback = bool(self._streaming_mode)
        self._is_buffering = bool(self._streaming_mode)
        self._last_prompted_source = ""
        self.scrub_slider.setRange(0, 0)
        self.scrub_slider.setValue(0)
        self._set_time_text(0, 0)
        self._set_buffer_progress(0)
        self._refresh_play_pause_button()

        if self._player is None:
            self.play_pause_btn.setEnabled(False)
            self.scrub_slider.setEnabled(False)
            self.time_label.setText("Audio playback unavailable")
            return True

        try:
            self._player.setSource(self._to_media_qurl(source))
            if self._streaming_mode and self._is_sound_enabled():
                self._player.play()
            self.refresh_sound_state()
            return True
        except Exception:
            self.clear_audio("Could not load audio stream")
            return False

    def set_resume_position_ms(self, position_ms: int) -> None:
        try:
            target = max(0, int(position_ms))
        except Exception:
            target = 0
        if target <= 0:
            self._resume_position_ms = 0
            return
        self._resume_position_ms = target
        if self._player is not None and self._duration_ms > 0:
            seek_to = min(self._duration_ms, self._resume_position_ms)
            try:
                self._player.setPosition(int(seek_to))
                self.scrub_slider.setValue(int(seek_to))
                self._set_time_text(int(seek_to), self._duration_ms)
                self._resume_position_ms = 0
            except Exception:
                pass

    def current_position_ms(self) -> int:
        if self._player is not None:
            try:
                return max(0, int(self._player.position()))
            except Exception:
                pass
        try:
            return max(0, int(self.scrub_slider.value()))
        except Exception:
            return 0

    def current_audio_source(self) -> str:
        return str(self._audio_source or "").strip()

    def refresh_sound_state(self) -> None:
        if not self._is_sound_enabled():
            if self._player is not None:
                try:
                    self._player.stop()
                except Exception:
                    pass
            self._awaiting_initial_playback = False
            self._is_buffering = False
        self._refresh_play_pause_button()

    def apply_runtime_theme(self) -> None:
        panel_bg = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.18)
        panel_border = _mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.22)
        panel_text = _contrast_text_for_bg(panel_bg)
        subtle_text = _mix_hex(panel_text, Colors.TEXT_GRAY, 0.44)
        warning_color = _mix_hex("#FFB703", Colors.TEXT_WHITE, 0.18)

        btn_bg = _mix_hex(Colors.PRIMARY, Colors.BG_LIGHT, 0.08)
        btn_text = _contrast_text_for_bg(btn_bg)
        btn_hover = _mix_hex(btn_bg, Colors.PRIMARY_HOVER, 0.26)
        btn_border = _mix_hex(btn_bg, Colors.BG_DARK, 0.18)

        groove = _mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.22)
        handle = _mix_hex(Colors.ACCENT_CYAN, Colors.PRIMARY, 0.40)
        handle_border = _mix_hex(handle, Colors.BG_DARK, 0.30)
        buffer_chunk = _mix_hex(Colors.ACCENT_CYAN, Colors.PRIMARY_HOVER, 0.38)
        buffer_bg = _mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.30)

        self.setStyleSheet(
            "QWidget#listeningHeader {"
            f"background-color: {panel_bg};"
            f"border: 1px solid {panel_border};"
            "border-radius: 9px;"
            "}"
            "QWidget#listeningHeader QPushButton {"
            f"background-color: {btn_bg};"
            f"color: {btn_text};"
            f"border: 1px solid {btn_border};"
            "border-radius: 7px;"
            "padding: 4px 10px;"
            "font-size: 12px;"
            "font-weight: 700;"
            "min-height: 24px;"
            "}"
            "QWidget#listeningHeader QPushButton:hover:!disabled {"
            f"background-color: {btn_hover};"
            "}"
            "QWidget#listeningHeader QPushButton:disabled {"
            f"background-color: {_mix_hex(btn_bg, Colors.BG_CARD, 0.72)};"
            f"color: {_mix_hex(btn_text, Colors.TEXT_GRAY, 0.72)};"
            f"border: 1px solid {_mix_hex(btn_border, Colors.BG_DARK, 0.40)};"
            "}"
            "QWidget#listeningHeader QLabel {"
            f"color: {subtle_text};"
            "font-size: 11px;"
            "font-weight: 600;"
            "border: none;"
            "background: transparent;"
            "}"
            "QWidget#listeningHeader QLabel#listeningSoundWarning {"
            f"color: {warning_color};"
            "font-size: 13px;"
            "font-weight: 800;"
            "padding-left: 2px;"
            "}"
            "QWidget#listeningHeader QSlider::groove:horizontal {"
            f"background: {groove};"
            "height: 6px;"
            "border-radius: 3px;"
            "}"
            "QWidget#listeningHeader QSlider::handle:horizontal {"
            f"background: {handle};"
            f"border: 1px solid {handle_border};"
            "width: 12px;"
            "margin: -4px 0;"
            "border-radius: 6px;"
            "}"
            "QWidget#listeningHeader QProgressBar {"
            f"background-color: {buffer_bg};"
            f"color: {_contrast_text_for_bg(buffer_bg)};"
            f"border: 1px solid {_mix_hex(buffer_bg, Colors.BG_DARK, 0.24)};"
            "border-radius: 6px;"
            "text-align: center;"
            "font-size: 10px;"
            "padding: 1px;"
            "min-height: 18px;"
            "}"
            "QWidget#listeningHeader QProgressBar::chunk {"
            f"background-color: {buffer_chunk};"
            "border-radius: 5px;"
            "}"
        )
        self.refresh_sound_state()


class PDFViewer(QWidget):
    """Embedded PDF viewer with WebEngine or scrollable pixmap fallback."""

    _GLOBAL_RULER_VISIBLE = True
    _GLOBAL_RULER_SYNCING = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_path: Optional[str] = None
        self.page_count = 0
        self.current_page = 0
        self.zoom_factor = 1.0
        self.doc = None
        self._doc_cache: "OrderedDict[str, Any]" = OrderedDict()
        self._download_cache: Dict[str, str] = {}
        self._max_cached_docs = 3
        # Prefer PyMuPDF for stable page jumping/zoom behavior.
        self.use_pixmap = PDF_AVAILABLE or not WEBENGINE_AVAILABLE
        self._fit_mode = False
        self._fit_width_mode = False
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(100)
        self._zoom_render_timer.timeout.connect(self._finish_zoom_render)
        self._zoom_anchor = None
        self._sharp_pixmap = None
        self._sharp_zoom = 1.0
        self._render_revision = 0
        self._sharp_revision = -1
        self._view_restore_timer = QTimer(self)
        self._view_restore_timer.setSingleShot(True)
        self._view_restore_timer.timeout.connect(self._restore_pending_scroll)
        self._pending_view_restore = None
        self._viewport_geometry_timer = QTimer(self)
        self._viewport_geometry_timer.setSingleShot(True)
        self._viewport_geometry_timer.timeout.connect(self._update_viewport_geometry)
        self._render_cache = OrderedDict()
        self._render_cache_bytes = 0
        self.page_rotations: Dict[int, int] = {}
        self.auto_rotated_pages: set[int] = set()
        self.manual_rotated_pages: set[int] = set()
        self._rotation_warning_shown = False
        self.page_view_mode = "1up"
        self._zoom_shortcuts: List[QShortcut] = []
        self._pinch_last_total_scale = 1.0
        self._ruler_pinch_last_total_scale = 1.0
        self._ruler_pinch_active = False
        self._app_event_filter_installed = False
        self._movable_ruler_enabled = False
        self._ruler_state = PDFRulerState()
        self._ruler_overlay: Optional[PDFRulerOverlayWidget] = None
        self._centimeter_scale_enabled = False
        self._centimeter_scale_overlay: Optional[PDFCentimeterScaleOverlayWidget] = None
        self._a4_width_mm = 210.0
        self._a4_height_mm = 297.0
        self._ruler_interaction_mode = ""
        self._ruler_drag_offset = QPointF(0.0, 0.0)
        self._ruler_initialized = False
        self._ruler_hovered = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setObjectName("pdfViewerRoot")

        self.controls_row = QWidget(self)
        self.controls_row.setObjectName("pdfControlsRow")
        controls = QHBoxLayout(self.controls_row)
        controls.setContentsMargins(6, 4, 6, 4)
        controls.setSpacing(6)
        self.controls_layout = controls
        self.prev_btn = QPushButton("Prev")
        self.prev_btn.clicked.connect(self.prev_page)
        self.page_label = QLabel("0/0")
        self.page_label.setObjectName("pdfPageCountLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(62)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.next_page)

        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("pdfZoomLabel")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(56)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.fit_btn = QPushButton("Fit to Page")
        self.fit_btn.setMinimumWidth(96)
        self.fit_btn.clicked.connect(self.fit_to_page)
        self.rotate_ccw_btn = QPushButton("Rotate -90")
        self.rotate_ccw_btn.setMinimumWidth(94)
        self.rotate_ccw_btn.clicked.connect(self.rotate_current_page_ccw)
        self.rotation_label = QLabel("0°")
        self.rotation_label.setObjectName("pdfRotationLabel")
        self.rotation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rotation_label.setMinimumWidth(38)
        self.rotate_cw_btn = QPushButton("Rotate +90")
        self.rotate_cw_btn.setMinimumWidth(94)
        self.rotate_cw_btn.clicked.connect(self.rotate_current_page_cw)
        self.page_mode_combo = QComboBox()
        self.page_mode_combo.setObjectName("pdfPageModeCombo")
        self.page_mode_combo.addItems(["1 page on screen", "2 pages on screen"])
        self.page_mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.page_mode_combo.setMinimumContentsLength(16)
        self.page_mode_combo.setMinimumWidth(186)
        self.page_mode_combo.setMinimumHeight(32)
        self.page_mode_combo.setStyleSheet(
            "QComboBox#pdfPageModeCombo { padding: 3px 24px 3px 10px; min-height: 22px; } "
            "QComboBox#pdfPageModeCombo::drop-down { width: 22px; border: none; } "
            "QComboBox#pdfPageModeCombo QAbstractItemView { padding: 2px; } "
            "QComboBox#pdfPageModeCombo QAbstractItemView::item { min-height: 22px; padding: 4px 8px; }"
        )
        self.page_mode_combo.view().setMinimumWidth(214)
        self.page_mode_combo.currentTextChanged.connect(self._on_page_mode_changed)
        self.quick_tools_host = QWidget()
        self.quick_tools_host.setObjectName("pdfQuickToolsHost")
        self.quick_tools_layout = QHBoxLayout(self.quick_tools_host)
        self.quick_tools_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_tools_layout.setSpacing(4)
        self._quick_tool_buttons: List[QPushButton] = []
        self.quick_tools_host.setVisible(False)
        self.audio_header = ListeningHeader(self.controls_row)
        self.audio_header.setMinimumWidth(320)
        self.audio_header.setMaximumWidth(540)
        self.audio_header.hide()

        nav_group = QWidget(self.controls_row)
        nav_group.setObjectName("pdfControlGroup")
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setContentsMargins(6, 2, 6, 2)
        nav_layout.setSpacing(4)
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.next_btn)

        zoom_group = QWidget(self.controls_row)
        zoom_group.setObjectName("pdfControlGroup")
        zoom_layout = QHBoxLayout(zoom_group)
        zoom_layout.setContentsMargins(6, 2, 6, 2)
        zoom_layout.setSpacing(4)
        zoom_layout.addWidget(self.zoom_out_btn)
        zoom_layout.addWidget(self.zoom_label)
        zoom_layout.addWidget(self.zoom_in_btn)
        zoom_layout.addWidget(self.fit_btn)

        rotation_group = QWidget(self.controls_row)
        rotation_group.setObjectName("pdfControlGroup")
        rotation_layout = QHBoxLayout(rotation_group)
        rotation_layout.setContentsMargins(6, 2, 6, 2)
        rotation_layout.setSpacing(4)
        self.rotation_label.setToolTip("Current page rotation")
        rotation_layout.addWidget(self.rotate_ccw_btn)
        rotation_layout.addWidget(self.rotation_label)
        rotation_layout.addWidget(self.rotate_cw_btn)

        controls.addWidget(nav_group, 0)
        controls.addWidget(self.audio_header, 0)
        controls.addStretch(1)
        controls.addWidget(zoom_group, 0)
        controls.addWidget(rotation_group, 0)
        controls.addWidget(self.page_mode_combo, 0)
        controls.addWidget(self.quick_tools_host, 0)

        layout.addWidget(self.controls_row)

        # Avoid spinning up QtWebEngine unless we actually need the web fallback renderer.
        self.web_view = QWebEngineView() if (WEBENGINE_AVAILABLE and not self.use_pixmap) else None

        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("pdfImageScroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(QSize(1, 1))
        self.image_scroll.setWidget(self.image_label)

        if self.use_pixmap:
            layout.addWidget(self.image_scroll, 1)
        else:
            layout.addWidget(self.web_view, 1)
            self.page_mode_combo.setEnabled(False)
            self.page_mode_combo.setToolTip("Two-page layout requires the PyMuPDF viewer mode.")
        self._controls_visible = True
        self._floating_indicator_targets: List[QWidget] = []
        self.floating_page_indicator = QLabel("0/0", self)
        self.floating_page_indicator.setObjectName("pdfFloatingPageIndicator")
        self.floating_page_indicator.setStyleSheet(
            "QLabel#pdfFloatingPageIndicator {"
            f"background-color: {Colors.BG_CARD};"
            f"color: {Colors.TEXT_LIGHT};"
            "border: 1px solid rgba(255,255,255,0.18);"
            "border-radius: 10px;"
            "padding: 4px 10px;"
            "font-size: 12px;"
            "font-weight: 600;"
            "}"
        )
        self.floating_page_indicator.hide()
        self._ruler_hide_btn = QToolButton(self)
        self._ruler_hide_btn.setObjectName("pdfRulerToggle")
        self._ruler_hide_btn.setText("×")
        self._ruler_hide_btn.setToolTip("Hide ruler")
        self._ruler_hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ruler_hide_btn.setVisible(False)
        self._ruler_hide_btn.clicked.connect(lambda: self._set_ruler_visible(False))
        self._ruler_hide_btn.installEventFilter(self)
        self._ruler_show_btn = QToolButton(self)
        self._ruler_show_btn.setObjectName("pdfRulerToggle")
        self._ruler_show_btn.setText("Eye")
        self._ruler_show_btn.setToolTip("Show ruler")
        self._ruler_show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ruler_show_btn.setVisible(False)
        self._ruler_show_btn.clicked.connect(lambda: self._set_ruler_visible(True))
        self._ruler_show_btn.installEventFilter(self)
        self._edge_navigation_enabled = False
        self._edge_navigation_hotzone_px = 42
        self._edge_prev_btn = QPushButton("◀", self)
        self._edge_prev_btn.setToolTip("Previous page")
        self._edge_prev_btn.clicked.connect(self.prev_page)
        self._edge_next_btn = QPushButton("▶", self)
        self._edge_next_btn.setToolTip("Next page")
        self._edge_next_btn.clicked.connect(self.next_page)
        edge_style = (
            "QPushButton {"
            "background-color: rgba(10, 15, 28, 150);"
            "color: rgba(226, 232, 240, 230);"
            "border: 1px solid rgba(148, 163, 184, 140);"
            "border-radius: 9px;"
            "padding: 0px;"
            "font-size: 14px;"
            "font-weight: 700;"
            "min-width: 34px;"
            "max-width: 34px;"
            "min-height: 48px;"
            "max-height: 48px;"
            "}"
            "QPushButton:hover:!disabled {"
            "background-color: rgba(30, 41, 59, 195);"
            "border: 1px solid rgba(148, 163, 184, 220);"
            "}"
            "QPushButton:disabled {"
            "background-color: rgba(15, 23, 42, 90);"
            "color: rgba(148, 163, 184, 120);"
            "border: 1px solid rgba(71, 85, 105, 120);"
            "}"
        )
        for edge_btn in [self._edge_prev_btn, self._edge_next_btn]:
            edge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            edge_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            edge_btn.setStyleSheet(edge_style)
            edge_btn.setVisible(False)
            edge_btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            edge_btn.installEventFilter(self)
            edge_btn.raise_()
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setMouseTracking(True)
        self.image_scroll.setMouseTracking(True)
        self.image_scroll.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.image_scroll.viewport().setMouseTracking(True)
        self.image_scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.image_label.setMouseTracking(True)
        self.image_label.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        if isinstance(self.web_view, QWidget):
            self.web_view.setMouseTracking(True)
            self.web_view.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.installEventFilter(self)
        self._register_floating_indicator_target(self)
        self._register_floating_indicator_target(self.image_scroll)
        self._register_floating_indicator_target(self.image_scroll.viewport())
        self._register_floating_indicator_target(self.image_label)
        self._register_floating_indicator_target(self.web_view)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.image_scroll.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self.image_label.grabGesture(Qt.GestureType.PinchGesture)
        if isinstance(self.web_view, QWidget):
            self.web_view.grabGesture(Qt.GestureType.PinchGesture)
        self._install_zoom_shortcuts()
        self._sync_rotation_controls()
        self._position_floating_page_indicator()
        self._position_edge_navigation_buttons()
        self._sync_ruler_overlay_geometry()
        self._sync_ruler_visibility_buttons()

    def set_quick_tool_buttons(self, buttons: List[QPushButton]) -> None:
        while self.quick_tools_layout.count():
            item = self.quick_tools_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                if widget not in buttons:
                    widget.deleteLater()
        self._quick_tool_buttons = []
        for button in buttons:
            if not isinstance(button, QPushButton):
                continue
            button.setParent(self.quick_tools_host)
            self.quick_tools_layout.addWidget(button)
            button.show()
            self._quick_tool_buttons.append(button)
        self.quick_tools_host.setVisible(bool(self._quick_tool_buttons))

    def set_listening_audio(self, audio_source: Optional[str]) -> bool:
        audio_header = getattr(self, "audio_header", None)
        if not isinstance(audio_header, ListeningHeader):
            return False
        source = str(audio_source or "").strip()
        if not source:
            audio_header.hide()
            audio_header.stop_audio()
            return False
        loaded = audio_header.load_audio_source(source)
        audio_header.refresh_sound_state()
        audio_header.setVisible(True)
        return loaded

    def show_listening_audio_unavailable(self, message: str = "Audio stream URL unavailable") -> None:
        audio_header = getattr(self, "audio_header", None)
        if not isinstance(audio_header, ListeningHeader):
            return
        audio_header.clear_audio(message)
        audio_header.refresh_sound_state()
        audio_header.setVisible(True)

    def hide_listening_audio(self) -> None:
        audio_header = getattr(self, "audio_header", None)
        if not isinstance(audio_header, ListeningHeader):
            return
        audio_header.stop_audio()
        audio_header.hide()

    def apply_runtime_theme(self) -> None:
        audio_header = getattr(self, "audio_header", None)
        if isinstance(audio_header, ListeningHeader):
            audio_header.apply_runtime_theme()
            audio_header.refresh_sound_state()
        border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.4)
        shell_bg = _mix_hex(Colors.BG_CARD, Colors.BG_MEDIUM, 0.12)
        controls_bg = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.2)
        controls_border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.5)
        group_bg = _mix_hex(controls_bg, Colors.BG_CARD, 0.22)
        group_border = _mix_hex(controls_border, Colors.BG_DARK, 0.2)
        control_btn_bg = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.18)
        control_btn_hover = _mix_hex(control_btn_bg, Colors.ACCENT_CYAN, 0.2)
        control_btn_text = _contrast_text_for_bg(control_btn_bg)
        control_btn_border = _mix_hex(control_btn_bg, Colors.BG_DARK, 0.26)
        scrollbar_bg = _mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.38)
        scrollbar_handle = _mix_hex(Colors.PRIMARY, Colors.ACCENT_CYAN, 0.3)
        ruler_btn_bg = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.22)
        ruler_btn_hover = _mix_hex(ruler_btn_bg, Colors.ACCENT_CYAN, 0.2)
        ruler_btn_text = _contrast_text_for_bg(ruler_btn_bg)
        self.setStyleSheet(
            "QWidget#pdfViewerRoot {"
            f"background-color: {shell_bg};"
            "}"
            "QWidget#pdfControlsRow {"
            f"background-color: {controls_bg};"
            f"border: 1px solid {controls_border};"
            "border-radius: 10px;"
            "}"
            "QWidget#pdfControlGroup {"
            f"background-color: {group_bg};"
            f"border: 1px solid {group_border};"
            "border-radius: 8px;"
            "}"
            "QWidget#pdfControlsRow QPushButton {"
            f"background-color: {control_btn_bg};"
            f"color: {control_btn_text};"
            f"border: 1px solid {control_btn_border};"
            "border-radius: 8px;"
            "padding: 5px 10px;"
            "min-height: 28px;"
            "font-size: 12px;"
            "font-weight: 600;"
            "}"
            "QWidget#pdfControlsRow QPushButton:hover:!disabled {"
            f"background-color: {control_btn_hover};"
            f"border: 1px solid {_mix_hex(control_btn_border, Colors.ACCENT_CYAN, 0.32)};"
            "}"
            "QWidget#pdfControlsRow QPushButton:disabled {"
            f"background-color: {_mix_hex(control_btn_bg, Colors.BG_CARD, 0.68)};"
            f"color: {_mix_hex(control_btn_text, Colors.TEXT_GRAY, 0.7)};"
            f"border: 1px solid {_mix_hex(control_btn_border, Colors.BG_DARK, 0.4)};"
            "}"
            "QWidget#pdfControlsRow QLabel#pdfPageCountLabel,"
            "QWidget#pdfControlsRow QLabel#pdfZoomLabel,"
            "QWidget#pdfControlsRow QLabel#pdfRotationLabel {"
            f"color: {_muted_text_for_bg(control_btn_bg)};"
            "font-size: 11px;"
            "font-weight: 700;"
            "padding: 0px 4px;"
            "border: none;"
            "background: transparent;"
            "}"
            "QWidget#pdfControlsRow QComboBox#pdfPageModeCombo {"
            f"background-color: {control_btn_bg};"
            f"color: {control_btn_text};"
            f"border: 1px solid {control_btn_border};"
            "border-radius: 8px;"
            "padding: 3px 22px 3px 10px;"
            "min-height: 28px;"
            "}"
            "QScrollArea#pdfImageScroll {"
            f"background-color: {shell_bg};"
            f"border: 2px solid {border};"
            "border-radius: 8px;"
            "}"
            "QLabel { background: transparent; }"
            "QScrollBar:vertical {"
            f"background: {scrollbar_bg};"
            "width: 8px;"
            "border-radius: 4px;"
            "margin: 2px;"
            "}"
            "QScrollBar::handle:vertical {"
            f"background: {scrollbar_handle};"
            "min-height: 22px;"
            "border-radius: 4px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            f"background: {_mix_hex(scrollbar_handle, Colors.TEXT_WHITE, 0.14)};"
            "}"
            "QScrollBar:horizontal {"
            f"background: {scrollbar_bg};"
            "height: 8px;"
            "border-radius: 4px;"
            "margin: 2px;"
            "}"
            "QScrollBar::handle:horizontal {"
            f"background: {scrollbar_handle};"
            "min-width: 22px;"
            "border-radius: 4px;"
            "}"
            "QScrollBar::handle:horizontal:hover {"
            f"background: {_mix_hex(scrollbar_handle, Colors.TEXT_WHITE, 0.14)};"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {"
            "width: 0px; height: 0px;"
            "}"
            "QToolButton#pdfRulerToggle {"
            f"background-color: {ruler_btn_bg};"
            f"color: {ruler_btn_text};"
            f"border: 1px solid {_mix_hex(border, Colors.BG_DARK, 0.28)};"
            "border-radius: 9px;"
            "padding: 4px 8px;"
            "font-size: 10px;"
            "font-weight: 700;"
            "}"
            "QToolButton#pdfRulerToggle:hover {"
            f"background-color: {ruler_btn_hover};"
            "}"
        )
        self.floating_page_indicator.setStyleSheet(
            "QLabel#pdfFloatingPageIndicator {"
            f"background-color: {_mix_hex(Colors.BG_CARD, Colors.BG_MEDIUM, 0.18)};"
            f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};"
            f"border: 1px solid {_mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.56)};"
            "border-radius: 10px;"
            "padding: 3px 8px;"
            "font-size: 11px;"
            "font-weight: 600;"
            "}"
        )
        if isinstance(self.web_view, QWidget):
            self.web_view.setStyleSheet(
                "QWidget {"
                f"border: 2px solid {border};"
                "border-radius: 8px;"
                "}"
            )
        self._sync_ruler_visibility_buttons()

    def set_controls_visible(self, visible: bool) -> None:
        self._controls_visible = bool(visible)
        if self.controls_row is not None:
            self.controls_row.setVisible(self._controls_visible)
        self._sync_ruler_overlay_geometry()
        self._sync_centimeter_scale_overlay_geometry()
        self._sync_ruler_visibility_buttons()

    def set_movable_ruler_enabled(self, enabled: bool) -> None:
        self._movable_ruler_enabled = bool(enabled)
        self._ensure_ruler_overlay()
        if self._movable_ruler_enabled:
            self._ruler_state.visible = bool(self.pdf_path) and bool(PDFViewer._GLOBAL_RULER_VISIBLE)
            self._reset_ruler_if_needed()
        else:
            self._ruler_state.visible = False
            self._ruler_pinch_active = False
            self._end_ruler_interaction(reset_pinch=True)
        self._update_ruler_overlay()
        self._sync_ruler_visibility_buttons()

    def is_movable_ruler_enabled(self) -> bool:
        return bool(self._movable_ruler_enabled)

    def set_centimeter_scale_enabled(self, enabled: bool) -> None:
        self._centimeter_scale_enabled = bool(enabled)
        self._ensure_centimeter_scale_overlay()
        self._update_centimeter_scale_overlay()

    def is_centimeter_scale_enabled(self) -> bool:
        return bool(self._centimeter_scale_enabled)

    def _ensure_centimeter_scale_overlay(self) -> None:
        if self._centimeter_scale_overlay is not None:
            return
        overlay = PDFCentimeterScaleOverlayWidget(self)
        overlay.hide()
        self._centimeter_scale_overlay = overlay

    def _sync_centimeter_scale_overlay_geometry(self) -> None:
        overlay = self._centimeter_scale_overlay
        if overlay is None:
            if not self._centimeter_scale_enabled:
                return
            self._ensure_centimeter_scale_overlay()
            overlay = self._centimeter_scale_overlay
        if overlay is None:
            return
        if not self._centimeter_scale_enabled or not self.pdf_path:
            overlay.hide()
            return
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            overlay.hide()
            return
        top_left = target.mapTo(self, QPoint(0, 0))
        overlay.setGeometry(QRect(top_left, target.size()))
        overlay.setVisible(True)
        if self._ruler_overlay is not None:
            try:
                overlay.stackUnder(self._ruler_overlay)
            except Exception:
                pass

    def _compute_scale_pixels_per_mm(self) -> float:
        # PDF coordinates are points (72 per physical inch), independent of page
        # format. Assuming every page is A4 mismeasures Letter and custom sizes.
        return (72.0 / 25.4) * max(1e-6, float(self.zoom_factor or 1.0))

    def _compute_scale_span_cm(self, pixels_per_mm: float, viewport_width: int) -> int:
        px_per_cm = max(0.0, float(pixels_per_mm) * 10.0)
        if px_per_cm <= 0.0 or viewport_width <= 0:
            return 0

        preferred_cm = 10
        min_cm = 1
        max_cm = 12
        min_visible_px = 120.0
        left_margin = 14.0
        right_margin = 18.0
        usable_width_px = max(0.0, float(viewport_width) - left_margin - right_margin)
        if usable_width_px <= 0.0:
            return 0

        max_by_width = int(math.floor(usable_width_px / px_per_cm))
        if max_by_width < min_cm:
            return 0

        span = preferred_cm
        if (px_per_cm * float(span)) < min_visible_px:
            span = int(math.ceil(min_visible_px / px_per_cm))
        span = max(min_cm, span)
        span = min(span, max_cm, max_by_width)
        return int(max(0, span))

    def _locked_ruler_length_px(self) -> float:
        # Instrument geometry is screen-space; graduations reflect document zoom.
        return 240.0

    def _set_ruler_visible(self, visible: bool) -> None:
        target_visible = bool(visible) and bool(self._movable_ruler_enabled) and bool(self.pdf_path)
        PDFViewer._GLOBAL_RULER_VISIBLE = bool(target_visible)
        self._ruler_state.visible = target_visible
        self._update_ruler_overlay()
        self._sync_global_ruler_visibility()
        self._sync_ruler_visibility_buttons()

    def _sync_global_ruler_visibility(self) -> None:
        if PDFViewer._GLOBAL_RULER_SYNCING:
            return
        root = self.window()
        if root is None:
            return
        PDFViewer._GLOBAL_RULER_SYNCING = True
        try:
            for viewer in root.findChildren(PDFViewer):
                if not isinstance(viewer, PDFViewer) or viewer is self:
                    continue
                should_show = bool(PDFViewer._GLOBAL_RULER_VISIBLE and viewer._movable_ruler_enabled and viewer.pdf_path)
                viewer._ruler_state.visible = should_show
                viewer._update_ruler_overlay()
                viewer._sync_ruler_visibility_buttons()
        finally:
            PDFViewer._GLOBAL_RULER_SYNCING = False

    def _position_ruler_visibility_buttons(self) -> None:
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            return
        top_left = target.mapTo(self, QPoint(0, 0))
        hide_btn = self._ruler_hide_btn
        show_btn = self._ruler_show_btn
        hide_btn.adjustSize()
        show_btn.adjustSize()
        hide_btn.move(
            top_left.x() + int(max(4, min(target.width()-hide_btn.width()-4, self._ruler_state.center.x() + 8))),
            top_left.y() + int(max(4, min(target.height()-hide_btn.height()-4, self._ruler_state.center.y() + 22))),
        )
        show_btn.move(
            top_left.x() + max(6, target.width() - show_btn.width() - 8),
            top_left.y() + max(8, target.height() - show_btn.height() - 10),
        )
        hide_btn.raise_()
        show_btn.raise_()

    def _sync_ruler_visibility_buttons(self) -> None:
        self._position_ruler_visibility_buttons()
        if not self._movable_ruler_enabled or not self.pdf_path:
            self._ruler_hide_btn.setVisible(False)
            self._ruler_show_btn.setVisible(False)
            return
        if self._ruler_state.visible:
            hovering = self._ruler_hovered or self._ruler_hide_btn.underMouse()
            self._ruler_hide_btn.setVisible(True)
            self._ruler_show_btn.setVisible(False)
            return
        self._ruler_hide_btn.setVisible(False)
        self._ruler_show_btn.setVisible(True)

    def _refresh_locked_ruler_length(self) -> None:
        self._ruler_state.length_px = self._locked_ruler_length_px()
        self._ruler_state.thickness_px = 34.0
        self._ruler_state.pixels_per_mm = self._compute_scale_pixels_per_mm()

    def _update_centimeter_scale_overlay(self) -> None:
        self._sync_centimeter_scale_overlay_geometry()
        if self._centimeter_scale_overlay is None:
            return
        if not self._centimeter_scale_enabled or not self.pdf_path:
            self._centimeter_scale_overlay.set_scale_metrics(0.0, 0, False)
            return

        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            self._centimeter_scale_overlay.set_scale_metrics(0.0, 0, False)
            return

        pixels_per_mm = self._compute_scale_pixels_per_mm()
        if not math.isfinite(pixels_per_mm) or pixels_per_mm <= 0.0:
            self._centimeter_scale_overlay.set_scale_metrics(0.0, 0, False)
            return

        span_cm = self._compute_scale_span_cm(pixels_per_mm, target.width())
        if span_cm <= 0:
            self._centimeter_scale_overlay.set_scale_metrics(0.0, 0, False)
            return

        pixels_per_cm = pixels_per_mm * 10.0
        self._centimeter_scale_overlay.set_scale_metrics(pixels_per_cm, span_cm, True)
        self._centimeter_scale_overlay.raise_()
        if self._ruler_overlay is not None and self._ruler_state.visible:
            self._ruler_overlay.raise_()

    def _ensure_ruler_overlay(self) -> None:
        if self._ruler_overlay is not None:
            return
        overlay = PDFRulerOverlayWidget(self)
        overlay.hide()
        self._ruler_overlay = overlay

    def _update_ruler_overlay(self) -> None:
        protractor = getattr(self, '_document_protractor', None)
        if protractor:
            protractor.update_scale()
        self._sync_ruler_overlay_geometry()
        if not self._ruler_overlay:
            return
        if self._movable_ruler_enabled:
            self._refresh_locked_ruler_length()
        self._ruler_overlay.set_state(self._ruler_state, self._ruler_interaction_mode)
        if self._ruler_state.visible:
            self._ruler_overlay.raise_()
        self._sync_ruler_visibility_buttons()

    def _sync_ruler_overlay_geometry(self) -> None:
        if not self._movable_ruler_enabled and not self._ruler_state.visible:
            if self._ruler_overlay is not None:
                self._ruler_overlay.hide()
            self._sync_ruler_visibility_buttons()
            return
        self._ensure_ruler_overlay()
        if not self._ruler_overlay:
            return
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            self._ruler_overlay.hide()
            self._sync_ruler_visibility_buttons()
            return
        top_left = target.mapTo(self, QPoint(0, 0))
        self._ruler_overlay.setGeometry(QRect(top_left, target.size()))
        if self._movable_ruler_enabled:
            self._refresh_locked_ruler_length()
        self._clamp_ruler_center()
        self._ruler_overlay.setVisible(bool(self._ruler_state.visible))
        self._ruler_overlay.raise_()
        self._sync_ruler_visibility_buttons()

    def _reset_ruler_if_needed(self) -> None:
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            return
        if not self._ruler_initialized:
            width = max(1, target.width())
            height = max(1, target.height())
            self._ruler_state.center = QPointF(width * 0.5, height * 0.5)
            self._refresh_locked_ruler_length()
            self._ruler_state.angle_deg = 0.0
            self._ruler_initialized = True
        else:
            self._refresh_locked_ruler_length()
        self._clamp_ruler_center()

    def _ruler_handle_center(self) -> QPointF:
        angle_rad = math.radians(float(self._ruler_state.angle_deg))
        handle_offset = (float(self._ruler_state.length_px) * 0.5) + 24.0
        return QPointF(
            float(self._ruler_state.center.x()) + (math.cos(angle_rad) * handle_offset),
            float(self._ruler_state.center.y()) + (math.sin(angle_rad) * handle_offset),
        )

    def _ruler_hit_test(self, point: QPoint) -> tuple[bool, bool]:
        if not self._movable_ruler_enabled or not self._ruler_state.visible:
            return False, False
        px = float(point.x())
        py = float(point.y())
        center = self._ruler_state.center
        dx = px - float(center.x())
        dy = py - float(center.y())
        rotation = math.radians(float(self._ruler_state.angle_deg))
        cos_a = math.cos(rotation)
        sin_a = math.sin(rotation)
        local_x = (dx * cos_a) + (dy * sin_a)
        local_y = (-dx * sin_a) + (dy * cos_a)

        length_px = max(1.0, float(self._ruler_state.length_px))
        thickness_px = max(16.0, min(96.0, float(self._ruler_state.thickness_px)))
        body_rect = QRectF(-length_px * 0.5, -thickness_px * 0.5, length_px, thickness_px)
        body_hit = body_rect.contains(QPointF(local_x, local_y))

        handle_local = QPointF((length_px * 0.5) + 24.0, 0.0)
        handle_radius = 12.0
        handle_hit = (local_x - handle_local.x()) ** 2 + (local_y - handle_local.y()) ** 2 <= handle_radius ** 2
        if handle_hit:
            body_hit = False
        return body_hit, handle_hit

    def _clamp_ruler_center(self) -> None:
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            return
        width = max(1, target.width())
        height = max(1, target.height())
        margin = 8.0
        x = max(margin, min(float(width) - margin, float(self._ruler_state.center.x())))
        y = max(margin, min(float(height) - margin, float(self._ruler_state.center.y())))
        self._ruler_state.center = QPointF(x, y)

    def _scale_ruler(self, factor: float) -> bool:
        _ = float(factor)
        self._refresh_locked_ruler_length()
        self._clamp_ruler_center()
        self._update_ruler_overlay()
        return False

    def _begin_ruler_interaction(self, interaction_mode: str, point: QPoint) -> None:
        mode = str(interaction_mode or "").strip().lower()
        if mode not in {"drag", "rotate"}:
            return
        self._ruler_interaction_mode = mode
        if mode == "drag":
            self._ruler_drag_offset = QPointF(
                float(self._ruler_state.center.x()) - float(point.x()),
                float(self._ruler_state.center.y()) - float(point.y()),
            )
        else:
            self._ruler_drag_offset = QPointF(0.0, 0.0)
        self._update_ruler_overlay()

    def _update_ruler_interaction(self, point: QPoint) -> None:
        if self._ruler_interaction_mode == "drag":
            self._ruler_state.center = QPointF(
                float(point.x()) + float(self._ruler_drag_offset.x()),
                float(point.y()) + float(self._ruler_drag_offset.y()),
            )
            self._clamp_ruler_center()
            self._update_ruler_overlay()
            return

        if self._ruler_interaction_mode == "rotate":
            center = self._ruler_state.center
            dx = float(point.x()) - float(center.x())
            dy = float(point.y()) - float(center.y())
            if abs(dx) <= 1e-6 and abs(dy) <= 1e-6:
                return
            self._ruler_state.angle_deg = float(math.degrees(math.atan2(dy, dx))) % 360.0
            self._update_ruler_overlay()

    def _end_ruler_interaction(self, reset_pinch: bool = False) -> None:
        self._ruler_interaction_mode = ""
        self._ruler_drag_offset = QPointF(0.0, 0.0)
        if reset_pinch:
            self._ruler_pinch_active = False
            self._ruler_pinch_last_total_scale = 1.0
        self._update_ruler_overlay()

    def _handle_ruler_wheel_scale(self, watched: QObject, event: QWheelEvent) -> bool:
        _ = watched
        _ = event
        return False

    def _handle_ruler_pinch_event(self, watched: QObject, event: object) -> bool:
        _ = watched
        _ = event
        return False

    def _handle_ruler_surface_event(self, watched: QObject, event: QEvent) -> bool:
        if not self._movable_ruler_enabled or not self._ruler_state.visible:
            return False
        etype = event.type()
        if etype in {QEvent.Type.Gesture, QEvent.Type.GestureOverride}:
            return self._handle_ruler_pinch_event(watched, event)
        if etype == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            return self._handle_ruler_wheel_scale(watched, event)
        if etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            point = self._map_event_point_to_target(watched, event)
            body_hit, handle_hit = self._ruler_hit_test(point)
            if handle_hit:
                self._begin_ruler_interaction("rotate", point)
                event.accept()
                return True
            if body_hit:
                self._begin_ruler_interaction("drag", point)
                event.accept()
                return True
            return False
        if etype == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if not self._ruler_interaction_mode:
                return False
            if not bool(event.buttons() & Qt.MouseButton.LeftButton):
                self._end_ruler_interaction()
                return False
            point = self._map_event_point_to_target(watched, event)
            self._update_ruler_interaction(point)
            event.accept()
            return True
        if etype == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton and self._ruler_interaction_mode:
                if self._ruler_interaction_mode == "rotate":
                    angle = self._ruler_state.angle_deg
                    nearest = round(angle / 45.0) * 45.0
                    if abs(nearest-angle) <= 5.0 or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self._ruler_state.angle_deg = nearest % 360
                self._end_ruler_interaction()
                self._update_ruler_overlay()
                event.accept()
                return True
        return False

    def reset_ruler_position(self):
        self._ruler_initialized = False
        self._reset_ruler_if_needed()
        self._update_ruler_overlay()

    def _zoom_bounds(self) -> tuple[float, float]:
        return (0.25, 4.0)

    def _clamp_zoom_factor(self, value: float) -> float:
        low, high = self._zoom_bounds()
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 1.0
        if not math.isfinite(value):
            value = 1.0
        return max(low, min(high, value))

    def _capture_anchor_pdf_point(self, anchor: Optional[QPoint]) -> tuple[float, float, QPoint]:
        viewport = self.image_scroll.viewport()
        fallback = QPoint(max(0, viewport.width() // 2), max(0, viewport.height() // 2))
        if not isinstance(anchor, QPoint):
            point = fallback
        else:
            point = QPoint(int(anchor.x()), int(anchor.y()))
        point.setX(max(0, min(point.x(), max(0, viewport.width()))))
        point.setY(max(0, min(point.y(), max(0, viewport.height()))))

        hbar = self.image_scroll.horizontalScrollBar()
        vbar = self.image_scroll.verticalScrollBar()
        origin = self.image_label.mapTo(viewport, QPoint(0, 0))
        current_zoom = max(1e-6, float(self.zoom_factor))
        point_on_pdf_x = (float(point.x()) - origin.x()) / current_zoom
        point_on_pdf_y = (float(point.y()) - origin.y()) / current_zoom
        return point_on_pdf_x, point_on_pdf_y, point

    def _restore_anchor_pdf_point(self, point_on_pdf_x: float, point_on_pdf_y: float, mouse_pos: QPoint) -> None:
        hbar = self.image_scroll.horizontalScrollBar()
        vbar = self.image_scroll.verticalScrollBar()
        new_zoom = max(1e-6, float(self.zoom_factor))
        new_scroll_left = (float(point_on_pdf_x) * new_zoom) - float(mouse_pos.x())
        new_scroll_top = (float(point_on_pdf_y) * new_zoom) - float(mouse_pos.y())
        hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), int(round(new_scroll_left)))))
        vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), int(round(new_scroll_top)))))

    def _schedule_anchor_recenter(self, point_on_pdf_x: float, point_on_pdf_y: float, mouse_pos: QPoint) -> None:
        # Qt equivalent of requestAnimationFrame: apply one more correction in the next UI frame tick.
        QTimer.singleShot(
            0,
            lambda x=float(point_on_pdf_x), y=float(point_on_pdf_y), p=QPoint(mouse_pos): self._restore_anchor_pdf_point(x, y, p),
        )

    def _apply_zoom_factor(self, target_zoom: float, anchor: Optional[QPoint] = None) -> bool:
        if not self.pdf_path:
            return False
        next_zoom = self._clamp_zoom_factor(target_zoom)
        if abs(next_zoom - float(self.zoom_factor)) < 1e-4:
            self._update_page_label()
            return False

        self._fit_mode = False
        self._fit_width_mode = False
        if self.use_pixmap:
            point_on_pdf_x, point_on_pdf_y, anchor_point = self._capture_anchor_pdf_point(anchor)
            self.zoom_factor = next_zoom
            self._render_revision += 1
            self._pending_view_restore = None
            self._zoom_anchor = (point_on_pdf_x, point_on_pdf_y, anchor_point)
            if self._sharp_pixmap is not None:
                logical_w, logical_h, _, ratio = self._render_dimensions()
                preview = self._sharp_pixmap.scaled(
                    max(1, round(logical_w * ratio)), max(1, round(logical_h * ratio)),
                    Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
                preview.setDevicePixelRatio(ratio)
                self.image_label.setPixmap(preview)
                self.image_label.resize(round(logical_w), round(logical_h))
            self._zoom_render_timer.start()
            self._restore_anchor_pdf_point(point_on_pdf_x, point_on_pdf_y, anchor_point)
            self._update_page_label()
            self._update_centimeter_scale_overlay()
            self._update_ruler_overlay()
            return True

        if self.web_view:
            self.zoom_factor = next_zoom
            self.web_view.setZoomFactor(self.zoom_factor)
            self._update_page_label()
            self._update_centimeter_scale_overlay()
            return True
        return False

    def _finish_zoom_render(self):
        if getattr(self, '_busy__render_pixmap_page', False):
            self._zoom_render_timer.start()
            return
        if self._fit_width_mode:
            self.fit_to_width()
        elif self._fit_mode:
            self.fit_to_page()
        else:
            self._render_pixmap_page()
        if self._zoom_anchor and self._sharp_revision == self._render_revision:
            self._restore_anchor_pdf_point(*self._zoom_anchor)
            self._zoom_anchor = None
        self._update_ruler_overlay()

    def _step_zoom(self, direction: int) -> None:
        if not int(direction):
            return
        step_scale = math.exp(0.09 * (1 if direction > 0 else -1))
        self._apply_zoom_factor(
            float(self.zoom_factor) * step_scale,
            anchor=self._cursor_anchor_point(),
        )

    def _install_zoom_shortcuts(self) -> None:
        if self._zoom_shortcuts:
            return

        def _bind(sequence: str, handler: Callable[[], None]) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)
            self._zoom_shortcuts.append(shortcut)

        for seq in ["Ctrl++", "Ctrl+=", "Ctrl+Plus", "Meta++", "Meta+=", "Meta+Plus"]:
            _bind(seq, lambda direction=1: self._step_zoom(direction))
        for seq in ["Ctrl+-", "Ctrl+Minus", "Meta+-", "Meta+Minus"]:
            _bind(seq, lambda direction=-1: self._step_zoom(direction))

    def set_edge_navigation_enabled(self, enabled: bool) -> None:
        self._edge_navigation_enabled = bool(enabled)
        self._position_edge_navigation_buttons()
        if not self._edge_navigation_enabled:
            self._hide_edge_navigation_buttons()

    def _register_floating_indicator_target(self, widget: Optional[QWidget]) -> None:
        if not isinstance(widget, QWidget):
            return
        widget.setMouseTracking(True)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        widget.installEventFilter(self)
        self._floating_indicator_targets.append(widget)

    def _is_pdf_surface_watched(self, watched: QObject) -> bool:
        if not isinstance(watched, QWidget):
            return False
        try:
            image_scroll = self.image_scroll
            image_label = self.image_label
        except RuntimeError:
            return False
        except Exception:
            image_scroll = None
            image_label = None

        viewport = None
        if image_scroll is not None:
            try:
                viewport = image_scroll.viewport()
            except RuntimeError:
                image_scroll = None
                viewport = None
            except Exception:
                viewport = None

        if watched is image_scroll or watched is viewport or watched is image_label:
            return True
        if image_label is not None:
            try:
                if image_label.isAncestorOf(watched):
                    return True
            except RuntimeError:
                pass

        web_view_widget: Optional[QWidget] = self.web_view if isinstance(self.web_view, QWidget) else None
        if web_view_widget is not None:
            try:
                if watched is web_view_widget or web_view_widget.isAncestorOf(watched):
                    return True
            except RuntimeError:
                return False
        return False

    def _map_event_point_to_target(self, watched: QObject, event: object) -> QPoint:
        target = self._floating_indicator_target_widget()
        if hasattr(event, "position"):
            local_pos = event.position().toPoint()  # type: ignore[attr-defined]
        elif hasattr(event, "centerPoint"):
            center = event.centerPoint()  # type: ignore[attr-defined]
            local_pos = center.toPoint() if hasattr(center, "toPoint") else QPoint(int(center.x()), int(center.y()))
        elif hasattr(event, "pos"):
            local_pos = event.pos()  # type: ignore[attr-defined]
        else:
            local_pos = QPoint(-1, -1)
        if watched is target:
            return local_pos
        try:
            global_pos = watched.mapToGlobal(local_pos)  # type: ignore[arg-type]
            return target.mapFromGlobal(global_pos)
        except Exception:
            return QPoint(max(0, target.width() // 2), max(0, target.height() // 2))

    @staticmethod
    def _has_zoom_modifier(modifiers: Qt.KeyboardModifiers) -> bool:
        mask = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        return bool(modifiers & mask)

    def _handle_modifier_wheel_zoom(self, watched: QObject, event: QWheelEvent) -> bool:
        if not self._has_zoom_modifier(event.modifiers()):
            return False
        angle_y = float(event.angleDelta().y())
        pixel_y = float(event.pixelDelta().y())
        if abs(angle_y) < 0.001 and abs(pixel_y) < 0.001:
            return False
        units = (angle_y / 120.0) if abs(angle_y) >= 0.001 else (pixel_y / 120.0)
        target_zoom = float(self.zoom_factor) * math.exp(units * 0.09)
        anchor = self._map_event_point_to_target(watched, event)
        changed = self._apply_zoom_factor(target_zoom, anchor=anchor)
        if changed:
            event.accept()
        return changed

    def _handle_native_zoom_gesture(self, watched: QObject, event: object) -> bool:
        try:
            gesture_type = event.gestureType()  # type: ignore[attr-defined]
        except Exception:
            return False
        zoom_type = getattr(Qt.NativeGestureType, "ZoomNativeGesture", None)
        if zoom_type is None or gesture_type != zoom_type:
            return False
        try:
            amount = float(event.value())  # type: ignore[attr-defined]
        except Exception:
            return False
        if abs(amount) < 1e-6:
            return False
        target_zoom = float(self.zoom_factor) * math.exp(amount * 0.45)
        anchor = self._map_event_point_to_target(watched, event)
        changed = self._apply_zoom_factor(target_zoom, anchor=anchor)
        if changed and hasattr(event, "accept"):
            event.accept()  # type: ignore[attr-defined]
        return changed

    def _handle_pinch_gesture(self, watched: QObject, event: object) -> bool:
        pinch_gesture_type = getattr(Qt.GestureType, "PinchGesture", None)
        if pinch_gesture_type is None or not hasattr(event, "gesture"):
            return False
        pinch = event.gesture(pinch_gesture_type)  # type: ignore[attr-defined]
        if pinch is None:
            return False
        state = getattr(pinch, "state", lambda: Qt.GestureState.NoGesture)()
        if state == Qt.GestureState.GestureStarted:
            self._pinch_last_total_scale = 1.0
            if hasattr(event, "accept"):
                event.accept()  # type: ignore[attr-defined]
            return True
        if state in {Qt.GestureState.GestureCanceled, Qt.GestureState.GestureFinished}:
            self._pinch_last_total_scale = 1.0
            if hasattr(event, "accept"):
                event.accept()  # type: ignore[attr-defined]
            return True
        try:
            total_scale = float(getattr(pinch, "totalScaleFactor")())
        except Exception:
            try:
                total_scale = float(getattr(pinch, "scaleFactor")())
            except Exception:
                return False
        total_scale = max(1e-6, total_scale)
        last_scale = max(1e-6, float(self._pinch_last_total_scale or 1.0))
        delta = total_scale / last_scale
        self._pinch_last_total_scale = total_scale
        if abs(delta - 1.0) < 1e-6:
            return False
        anchor = self._map_event_point_to_target(watched, pinch)
        changed = self._apply_zoom_factor(float(self.zoom_factor) * delta, anchor=anchor)
        if changed and hasattr(event, "accept"):
            event.accept()  # type: ignore[attr-defined]
        return changed

    def _should_show_floating_indicator(self) -> bool:
        if not self.pdf_path:
            return False
        if self.underMouse():
            return True
        for target in self._floating_indicator_targets:
            try:
                if target is not None and target.underMouse():
                    return True
            except Exception:
                continue
        return False

    def _set_floating_indicator_visible(self, visible: bool) -> None:
        should_show = bool(visible) and bool(self.pdf_path)
        self.floating_page_indicator.setVisible(should_show)
        if should_show:
            self.floating_page_indicator.raise_()
            self._position_floating_page_indicator()

    def _floating_indicator_target_widget(self) -> QWidget:
        if self.use_pixmap:
            viewport = self.image_scroll.viewport() if self.image_scroll else None
            if isinstance(viewport, QWidget):
                return viewport
        if isinstance(self.web_view, QWidget):
            return self.web_view
        return self

    def _cursor_anchor_point(self) -> Optional[QPoint]:
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            return None
        try:
            local_pos = target.mapFromGlobal(QCursor.pos())
        except Exception:
            return None
        if local_pos.x() < 0 or local_pos.y() < 0:
            return None
        if local_pos.x() >= target.width() or local_pos.y() >= target.height():
            return None
        return local_pos

    def _position_floating_page_indicator(self) -> None:
        label = self.floating_page_indicator
        if label is None:
            return
        label.adjustSize()
        target = self._floating_indicator_target_widget()
        top_left = target.mapTo(self, QPoint(0, 0))
        x = top_left.x() + max(8, target.width() - label.width() - 12)
        y = top_left.y() + 10
        label.move(max(4, x), max(4, y))
        self._sync_ruler_overlay_geometry()
        self._sync_centimeter_scale_overlay_geometry()

    def _position_edge_navigation_buttons(self) -> None:
        target = self._floating_indicator_target_widget()
        if not isinstance(target, QWidget):
            return
        top_left = target.mapTo(self, QPoint(0, 0))
        prev = self._edge_prev_btn
        nxt = self._edge_next_btn
        for button in [prev, nxt]:
            button.adjustSize()
        y = top_left.y() + max(0, int((target.height() - prev.height()) / 2))
        prev.move(top_left.x() + 8, y)
        nxt.move(top_left.x() + max(8, target.width() - nxt.width() - 8), y)
        prev.raise_()
        nxt.raise_()
        self._sync_ruler_overlay_geometry()
        self._sync_centimeter_scale_overlay_geometry()

    def _hide_edge_navigation_buttons(self) -> None:
        self._edge_prev_btn.setVisible(False)
        self._edge_next_btn.setVisible(False)

    def _sync_edge_navigation_visibility_from_hover_state(self) -> None:
        if not self._edge_navigation_enabled or not self.pdf_path:
            self._hide_edge_navigation_buttons()
            return
        target = self._floating_indicator_target_widget()
        if target.underMouse() or self._edge_prev_btn.underMouse() or self._edge_next_btn.underMouse():
            self._edge_prev_btn.setVisible(True)
            self._edge_next_btn.setVisible(True)
            self._position_edge_navigation_buttons()
            return
        self._hide_edge_navigation_buttons()

    def _update_edge_navigation_for_point(self, point: QPoint, target: QWidget) -> None:
        if not self._edge_navigation_enabled or not self.pdf_path:
            self._hide_edge_navigation_buttons()
            return
        if point.x() < 0 or point.y() < 0 or point.x() > target.width() or point.y() > target.height():
            self._hide_edge_navigation_buttons()
            return
        self._edge_prev_btn.setVisible(True)
        self._edge_next_btn.setVisible(True)
        self._position_edge_navigation_buttons()

    def _defer_hover_update(self, callback) -> None:
        """Cancel deferred UI work with the viewer, including on older PySide6."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(timer.deleteLater)
        timer.start(0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        # Global fallback path: capture input from inner/native child widgets too.
        if watched in self._floating_indicator_targets and event.type() in (QEvent.Type.Move,QEvent.Type.Resize,QEvent.Type.LayoutRequest):
            self._viewport_geometry_timer.start(0)
        if watched is self and event.type() == getattr(QEvent.Type,'DevicePixelRatioChange',None):
            self._render_revision += 1
            self._zoom_render_timer.start()
        try:
            on_pdf_surface = self._is_pdf_surface_watched(watched)
        except Exception:
            on_pdf_surface = False

        if on_pdf_surface:
            if self._handle_ruler_surface_event(watched, event):
                return True
            etype = event.type()
            if etype == QEvent.Type.GestureOverride:
                if self._handle_pinch_gesture(watched, event):
                    return True
            elif etype == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
                if self._handle_modifier_wheel_zoom(watched, event):
                    return True
            elif etype == QEvent.Type.NativeGesture:
                if self._handle_native_zoom_gesture(watched, event):
                    return True
            elif etype == QEvent.Type.Gesture:
                if self._handle_pinch_gesture(watched, event):
                    return True

        if watched in {self._edge_prev_btn, self._edge_next_btn}:
            etype = event.type()
            if etype in {QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.Show}:
                if self._edge_navigation_enabled and self.pdf_path:
                    if watched is self._edge_prev_btn:
                        self._edge_prev_btn.setVisible(True)
                    if watched is self._edge_next_btn:
                        self._edge_next_btn.setVisible(True)
            elif etype in {QEvent.Type.Leave, QEvent.Type.HoverLeave, QEvent.Type.Hide}:
                self._defer_hover_update(self._sync_edge_navigation_visibility_from_hover_state)
            return super().eventFilter(watched, event)

        if watched in {self._ruler_hide_btn, self._ruler_show_btn}:
            etype = event.type()
            if etype in {QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.Show}:
                self._ruler_hovered = True
                self._sync_ruler_visibility_buttons()
            elif etype in {QEvent.Type.Leave, QEvent.Type.HoverLeave, QEvent.Type.Hide}:
                self._ruler_hovered = False
                self._defer_hover_update(self._sync_ruler_visibility_buttons)
            return super().eventFilter(watched, event)

        if watched in self._floating_indicator_targets:
            etype = event.type()
            if self._handle_ruler_surface_event(watched, event):
                return True
            if etype == QEvent.Type.GestureOverride:
                if self._handle_pinch_gesture(watched, event):
                    return True
            if etype == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
                if self._handle_modifier_wheel_zoom(watched, event):
                    return True
            elif etype == QEvent.Type.NativeGesture:
                if self._handle_native_zoom_gesture(watched, event):
                    return True
            elif etype == QEvent.Type.Gesture:
                if self._handle_pinch_gesture(watched, event):
                    return True
            if etype in {QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.Show}:
                self._ruler_hovered = True
                self._set_floating_indicator_visible(True)
                self._sync_edge_navigation_visibility_from_hover_state()
                self._sync_ruler_visibility_buttons()
            elif etype in {QEvent.Type.Leave, QEvent.Type.HoverLeave, QEvent.Type.Hide}:
                self._defer_hover_update(lambda: self._set_floating_indicator_visible(self._should_show_floating_indicator()))
                self._defer_hover_update(self._sync_edge_navigation_visibility_from_hover_state)
                self._ruler_hovered = False
                self._defer_hover_update(self._sync_ruler_visibility_buttons)
            elif etype in {QEvent.Type.MouseMove, QEvent.Type.HoverMove}:
                target = self._floating_indicator_target_widget()
                mapped = self._map_event_point_to_target(watched, event)
                self._update_edge_navigation_for_point(mapped, target)
                self._ruler_hovered = True
                self._sync_ruler_visibility_buttons()
        return super().eventFilter(watched, event)

    def load_pdf(self, path_or_url: str) -> bool:
        path_or_url = str(path_or_url or "").strip()
        if path_or_url.lower().startswith(("http://", "https://")):
            path_or_url = self._download_pdf(path_or_url)

        if not path_or_url or not os.path.isfile(path_or_url):
            show_error(self, "PDF Viewer", "The PDF file is missing or inaccessible.")
            return False
        replacement = None
        if self.use_pixmap:
            if not PDF_AVAILABLE:
                show_error(self, "PDF Viewer", "PDF rendering is unavailable.")
                return False
            try:
                replacement = self._open_cached_doc(path_or_url)
                if replacement is None or len(replacement) == 0:
                    raise ValueError("The PDF has no readable pages")
            except Exception as exc:
                show_error(self, "PDF Viewer", f"Failed to open PDF: {exc}")
                return False

        self._zoom_render_timer.stop()
        self._render_revision += 1
        self._view_restore_timer.stop()
        self._pending_view_restore = None
        self._render_cache.clear()
        self._render_cache_bytes = 0
        self._sharp_pixmap = None
        self._zoom_anchor = None
        self._fit_width_mode = False
        self.pdf_path = path_or_url
        self.current_page = 0
        self.zoom_factor = 1.0
        self._fit_mode = False
        self.page_rotations.clear()
        self.auto_rotated_pages.clear()
        self.manual_rotated_pages.clear()
        self._rotation_warning_shown = False
        self.page_view_mode = "1up"
        self._pinch_last_total_scale = 1.0
        self._ruler_pinch_last_total_scale = 1.0
        self._ruler_pinch_active = False
        self._end_ruler_interaction(reset_pinch=True)
        if self.page_mode_combo:
            was_blocked = self.page_mode_combo.blockSignals(True)
            self.page_mode_combo.setCurrentIndex(0)
            self.page_mode_combo.blockSignals(was_blocked)
        self._sync_rotation_controls()

        if self.use_pixmap:
            self.doc = replacement
            self.page_count = len(replacement)
            self._render_pixmap_page()
        else:
            self.page_count = self._get_page_count(path_or_url)
            if self.web_view:
                self.web_view.setUrl(QUrl.fromLocalFile(path_or_url))

        if self._movable_ruler_enabled:
            self._ruler_state.visible = bool(PDFViewer._GLOBAL_RULER_VISIBLE)
            self._reset_ruler_if_needed()
        else:
            self._ruler_state.visible = False
        self._update_ruler_overlay()
        self._sync_ruler_visibility_buttons()
        self._update_centimeter_scale_overlay()
        self._update_page_label()

        return True

    def release_resources(self):
        self._zoom_render_timer.stop()
        self._viewport_geometry_timer.stop()
        self._render_revision += 1
        self._view_restore_timer.stop()
        self._pending_view_restore = None
        self._render_cache.clear()
        self._render_cache_bytes = 0
        self._sharp_pixmap = None
        self.doc = None
        for document in list(self._doc_cache.values()):
            document.close()
        self._doc_cache.clear()
        from Core.download_service import remove_owned_temporary_file
        for path in self._download_cache.values():
            remove_owned_temporary_file(path)
        self._download_cache.clear()
        self.image_label.clear()
        self.page_count = 0
        self.pdf_path = None

    @staticmethod
    def _looks_like_pdf_download(content_type: str, payload_prefix: bytes, final_url: str) -> bool:
        _ = str(final_url or "")
        sample = bytes(payload_prefix or b"").lstrip()
        lowered = sample.lower()
        if (
            lowered.startswith(b"<!doctype html")
            or lowered.startswith(b"<html")
            or lowered.startswith(b"<?xml")
        ):
            return False
        if sample.startswith(b"%PDF-"):
            return True

        ctype = str(content_type or "").strip().lower()
        if "application/pdf" in ctype:
            return True
        if (
            ctype.startswith("text/html")
            or ctype.startswith("text/plain")
            or ctype.startswith("application/xhtml+xml")
        ):
            return False
        return False

    def _download_pdf(self, url: str) -> Optional[str]:
        cached = self._download_cache.get(url)
        if cached and os.path.isfile(cached):
            return cached
        try:
            path = download_pdf(url)
            self._download_cache[url] = path
            return path
        except Exception as exc:
            show_error(self, "Load Error", str(exc))
            return None

    def _open_cached_doc(self, path: str):
        normalized = os.path.abspath(str(path or "").strip())
        if not normalized:
            return None
        cached = self._doc_cache.get(normalized)
        if cached is not None:
            self._doc_cache.move_to_end(normalized)
            return cached

        doc = fitz.open(normalized)
        self._doc_cache[normalized] = doc
        self._doc_cache.move_to_end(normalized)
        while len(self._doc_cache) > int(self._max_cached_docs):
            old_path, old_doc = self._doc_cache.popitem(last=False)
            if old_doc is self.doc:
                self._doc_cache[old_path] = old_doc
                self._doc_cache.move_to_end(old_path)
                continue
            try:
                old_doc.close()
            except Exception:
                pass
        return doc

    def _get_page_count(self, pdf_path: str) -> int:
        if not PDF_AVAILABLE:
            return 0
        try:
            doc = fitz.open(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0

    def _update_page_label(self):
        if self.page_count:
            if self._is_two_page_mode() and self.current_page > 0:
                left = self.current_page + 1
                right = min(self.page_count, self.current_page + 2)
                if right > left:
                    self.page_label.setText(f"{left}-{right}/{self.page_count}")
                else:
                    self.page_label.setText(f"{left}/{self.page_count}")
            else:
                self.page_label.setText(f"{self.current_page + 1}/{self.page_count}")
        else:
            self.page_label.setText("0/0")

        zoom_percent = int(self.zoom_factor * 100)
        self.zoom_label.setText(f"{zoom_percent}%")
        self.rotation_label.setText(f"{self.get_page_rotation(self.current_page)}°")
        self.floating_page_indicator.setText(str(self.page_label.text() or "0/0"))
        self.floating_page_indicator.adjustSize()
        self._position_floating_page_indicator()
        self._update_centimeter_scale_overlay()

    @staticmethod
    def _normalize_rotation_degrees(degrees: int) -> int:
        try:
            value = int(round(float(degrees)))
        except Exception:
            return 0
        value = value % 360
        nearest = int(round(value / 90.0) * 90) % 360
        return nearest

    def supports_page_rotation(self) -> bool:
        return bool(self.use_pixmap and PDF_AVAILABLE and self.doc is not None)

    def _warn_rotation_not_supported(self) -> None:
        if self._rotation_warning_shown:
            return
        self._rotation_warning_shown = True
        show_warning(
            self,
            "Rotation Not Available",
            "Page-specific rotation requires the PyMuPDF viewer path.",
        )

    def get_page_rotation(self, page_num: int) -> int:
        try:
            idx = int(page_num)
        except Exception:
            return 0
        return int(self.page_rotations.get(idx, 0))

    def set_page_rotation(self, page_num: int, degrees: int, manual: bool = False) -> None:
        try:
            idx = int(page_num)
        except Exception:
            return
        if idx < 0:
            return
        normalized = self._normalize_rotation_degrees(degrees)

        if manual:
            self.auto_rotated_pages.discard(idx)
            if normalized == 0:
                self.manual_rotated_pages.discard(idx)
            else:
                self.manual_rotated_pages.add(idx)
        else:
            if idx in self.manual_rotated_pages:
                return
            if normalized == 0:
                self.auto_rotated_pages.discard(idx)
            else:
                self.auto_rotated_pages.add(idx)

        if normalized == 0:
            self.page_rotations.pop(idx, None)
        else:
            self.page_rotations[idx] = normalized

        if idx == self.current_page:
            if self._fit_mode:
                self.fit_to_page()
            else:
                self.refresh_view()
        else:
            self._update_page_label()

    def clear_page_rotation(self, page_num: int, manual: bool = False) -> None:
        self.set_page_rotation(page_num, 0, manual=manual)

    def rotate_current_page_cw(self) -> None:
        if not self.supports_page_rotation():
            self._warn_rotation_not_supported()
            return
        current = self.get_page_rotation(self.current_page)
        self.set_page_rotation(self.current_page, current + 90, manual=True)

    def rotate_current_page_ccw(self) -> None:
        if not self.supports_page_rotation():
            self._warn_rotation_not_supported()
            return
        current = self.get_page_rotation(self.current_page)
        self.set_page_rotation(self.current_page, current - 90, manual=True)

    def auto_rotate_page_if_landscape(self, page_num: int, warn_if_unsupported: bool = False) -> bool:
        if not self.supports_page_rotation():
            if warn_if_unsupported:
                self._warn_rotation_not_supported()
            return False
        try:
            idx = int(page_num)
        except Exception:
            return False
        if idx < 0 or not self.doc or idx >= len(self.doc):
            return False
        if idx in self.manual_rotated_pages:
            return False

        page = self.doc[idx]
        if float(page.rect.width) <= float(page.rect.height):
            if idx in self.auto_rotated_pages:
                self.clear_page_rotation(idx, manual=False)
            return False

        if self.get_page_rotation(idx) == 0:
            self.set_page_rotation(idx, 90, manual=False)
            return True

        if idx in self.auto_rotated_pages:
            return True
        return False

    def go_to_page(self, page_num: int):
        if not self.pdf_path:
            return

        if self.page_count and (page_num < 0 or page_num >= self.page_count):
            return

        self.current_page = self._normalize_page_for_mode(page_num)
        self._zoom_anchor = None
        self._pending_view_restore = None
        self._update_page_label()
        if self.use_pixmap:
            if self._fit_mode:
                self.fit_to_page()
            else:
                self._render_pixmap_page()
        elif self.web_view:
            url = QUrl.fromLocalFile(self.pdf_path)
            url.setFragment(f"page={page_num + 1}")
            self.web_view.setUrl(url)

    def next_page(self):
        if not self.page_count:
            return
        if self._is_two_page_mode():
            if self.current_page == 0:
                target = 1
            else:
                target = self.current_page + 2
            if target >= self.page_count:
                return
            self.go_to_page(target)
            return
        if self.current_page < self.page_count - 1:
            self.go_to_page(self.current_page + 1)

    def prev_page(self):
        if not self.page_count or self.current_page <= 0:
            return
        if self._is_two_page_mode():
            if self.current_page <= 1:
                self.go_to_page(0)
            else:
                self.go_to_page(self.current_page - 2)
            return
        self.go_to_page(self.current_page - 1)

    def zoom_in(self):
        self._fit_mode = False
        self._apply_zoom_factor(
            float(self.zoom_factor) * math.exp(0.09),
            anchor=self._cursor_anchor_point(),
        )

    def zoom_out(self):
        self._fit_mode = False
        self._apply_zoom_factor(
            float(self.zoom_factor) * math.exp(-0.09),
            anchor=self._cursor_anchor_point(),
        )

    def fit_to_width(self):
        if not (self.doc and self.use_pixmap and self.page_count):
            self.fit_to_page()
            return
        page = self.doc[self.current_page]
        width = float(page.rect.height if self.get_page_rotation(self.current_page) in {90, 270} else page.rect.width)
        gap = 0
        if self._is_two_page_mode() and self.current_page > 0 and self.current_page + 1 < self.page_count:
            other = self.doc[self.current_page + 1]
            width += float(other.rect.height if self.get_page_rotation(self.current_page+1) in {90, 270} else other.rect.width)
            gap = 18
        self._fit_mode = False
        self._fit_width_mode = True
        self.zoom_factor = self._clamp_zoom_factor(max(1, self.image_scroll.viewport().width()-20-gap) / max(1, width))
        self._render_pixmap_page()
        self._update_ruler_overlay()
        self._update_centimeter_scale_overlay()

    def fit_to_page(self):
        self._fit_width_mode = False
        if getattr(self, '_busy_fit_to_page', False):
            return
        self._busy_fit_to_page = True
        try:
            self._fit_mode = True
            if self.use_pixmap:
                if not (self.doc and PDF_AVAILABLE and hasattr(self, "image_scroll")):
                    return
                try:
                    page = self.doc[self.current_page]
                    rect = page.rect
                    viewport = self.image_scroll.viewport().size()
                    page_w = float(rect.width)
                    page_h = float(rect.height)
                    rotation = self.get_page_rotation(self.current_page)
                    if rotation in {90, 270}:
                        page_w, page_h = page_h, page_w
                    if self._is_two_page_mode() and self.current_page > 0:
                        second_idx = self.current_page + 1
                        if second_idx < self.page_count:
                            second_page = self.doc[second_idx]
                            second_w = float(second_page.rect.width)
                            second_h = float(second_page.rect.height)
                            second_rotation = self.get_page_rotation(second_idx)
                            if second_rotation in {90, 270}:
                                second_w, second_h = second_h, second_w
                            page_w = page_w + second_w + 18.0
                            page_h = max(page_h, second_h)
                    if page_w <= 0 or page_h <= 0:
                        return
                    if viewport.width() <= 0:
                        return
                    fit_w = viewport.width() / page_w
                    fit_h = viewport.height() / page_h if viewport.height() > 0 else fit_w
                    # Fill the pane aggressively so fit mode does not shrink text after layout changes.
                    self.zoom_factor = self._clamp_zoom_factor(min(fit_w, fit_h))
                    self._render_pixmap_page()
                except Exception as e:
                    show_error(self, "Fit to Page", str(e))
                return

            if self.web_view:
                self.zoom_factor = self._clamp_zoom_factor(self.zoom_factor)
                self.web_view.setZoomFactor(self.zoom_factor)
                if self.pdf_path:
                    url = QUrl.fromLocalFile(self.pdf_path)
                    url.setFragment(f"page={self.current_page + 1}&zoom=page-width")
                    self.web_view.setUrl(url)
                self._update_page_label()
        finally:
            self._busy_fit_to_page = False

    def refresh_view(self):
        if self.use_pixmap:
            if self._fit_width_mode:
                self.fit_to_width()
            elif self._fit_mode:
                self.fit_to_page()
            else:
                self._render_pixmap_page()
        elif self.web_view:
            self.web_view.setZoomFactor(self.zoom_factor)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if not bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
            if event.key() == Qt.Key.Key_Left:
                self.prev_page()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Right:
                self.next_page()
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_floating_page_indicator()
        self._position_edge_navigation_buttons()
        self._sync_ruler_visibility_buttons()
        self._update_centimeter_scale_overlay()
        if self.use_pixmap and self._fit_width_mode:
            self._zoom_render_timer.start()
        elif self.use_pixmap and self._fit_mode:
            self.fit_to_page()

    def _update_viewport_geometry(self):
        self._position_floating_page_indicator()
        self._position_edge_navigation_buttons()
        self._sync_ruler_overlay_geometry()
        self._sync_centimeter_scale_overlay_geometry()

    def _render_dimensions(self):
        """Logical layout and bounded backing scale, including two-page spreads."""
        indices = [self.current_page]
        if self.page_view_mode == '2up' and self.current_page > 0 and self.current_page + 1 < self.page_count:
            indices.append(self.current_page + 1)
        sizes = []
        for index in indices:
            rect = self.doc[index].rect
            width, height = rect.width, rect.height
            if self.page_rotations.get(index, 0) in (90, 270):
                width, height = height, width
            sizes.append((width * self.zoom_factor, height * self.zoom_factor))
        width = sum(size[0] for size in sizes) + (18 if len(sizes) == 2 else 0)
        height = max(size[1] for size in sizes)
        ratio = backing_scale(width, height, self.devicePixelRatioF())
        return width, height, sizes, ratio

    def capture_view_state(self):
        return dict(page=self.current_page, zoom=self.zoom_factor,
                    fit_page=self._fit_mode, fit_width=self._fit_width_mode,
                    mode=self.page_view_mode, rotations=dict(self.page_rotations),
                    scroll=(self.image_scroll.horizontalScrollBar().value(),
                            self.image_scroll.verticalScrollBar().value()))

    def restore_view_state(self, state):
        self._fit_mode = False
        self._fit_width_mode = False
        self.page_view_mode = state.get('mode', '1up')
        blocked = self.page_mode_combo.blockSignals(True)
        self.page_mode_combo.setCurrentIndex(1 if self.page_view_mode == '2up' else 0)
        self.page_mode_combo.blockSignals(blocked)
        self.current_page = self._normalize_page_for_mode(state.get('page', 0))
        self.zoom_factor = self._clamp_zoom_factor(state.get('zoom', 1))
        self.page_rotations = dict(state.get('rotations', {}))
        self._zoom_anchor = None
        self._render_pixmap_page()
        self._fit_mode = bool(state.get('fit_page'))
        self._fit_width_mode = bool(state.get('fit_width'))
        self._pending_view_restore = (self.pdf_path, tuple(state.get('scroll', (0, 0))))
        self._view_restore_timer.start(0)
        self._sync_rotation_controls()
        self._update_ruler_overlay()

    def _restore_pending_scroll(self):
        if not self._pending_view_restore:
            return
        path, scroll = self._pending_view_restore
        if path == self.pdf_path:
            if self._sharp_revision != self._render_revision:
                self._view_restore_timer.start(20)
                return
            self.image_scroll.horizontalScrollBar().setValue(scroll[0])
            self.image_scroll.verticalScrollBar().setValue(scroll[1])
        self._pending_view_restore = None

    def _render_pixmap_page(self):
        # Requests can arrive while await_future pumps Qt events. A monotonic
        # revision also rejects an old A frame after an A -> B -> A zoom burst.
        self._render_revision += 1
        if getattr(self, '_busy__render_pixmap_page', False):
            self._zoom_render_timer.start()
            return
        if not (self.doc and PDF_AVAILABLE):
            return
        self._zoom_render_timer.stop()
        self._busy__render_pixmap_page = True
        revision = self._render_revision
        render_doc, render_page, render_zoom = self.doc, self.current_page, self.zoom_factor
        render_mode, render_rotations = self.page_view_mode, dict(self.page_rotations)
        try:
            logical_w, logical_h, sizes, ratio = self._render_dimensions()
            render_scale = render_zoom * ratio
            images = []
            for offset, size in enumerate(sizes):
                page_idx = render_page + offset
                rotation = render_rotations.get(page_idx, 0)
                key = (id(render_doc), page_idx, round(render_scale, 5), rotation)
                if key in self._render_cache:
                    image = self._render_cache[key]
                    self._render_cache.move_to_end(key)
                else:
                    pix = render_doc[page_idx].get_pixmap(
                        matrix=fitz.Matrix(render_scale, render_scale).prerotate(rotation),
                        alpha=False, show_progress=False, max_pixels=MAX_BACKING_PIXELS)
                    if revision != self._render_revision or self.doc is not render_doc:
                        self._zoom_render_timer.start()
                        return
                    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
                    self._render_cache[key] = image
                    self._render_cache_bytes += image.sizeInBytes()
                    while len(self._render_cache) > 6 or self._render_cache_bytes > 48 * 1024 * 1024:
                        _, previous = self._render_cache.popitem(last=False)
                        self._render_cache_bytes -= previous.sizeInBytes()
                images.append(image)
            if (revision != self._render_revision or self.doc is not render_doc
                    or self.current_page != render_page or self.zoom_factor != render_zoom
                    or self.page_view_mode != render_mode or self.page_rotations != render_rotations):
                self._zoom_render_timer.start()
                return
            canvas = QImage(max(1, round(logical_w*ratio)), max(1, round(logical_h*ratio)), QImage.Format.Format_RGB888)
            canvas.fill(QColor('white'))
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            x = 0.0
            for image, (width, height) in zip(images, sizes):
                painter.drawImage(QRectF(x*ratio, (logical_h-height)*ratio/2, width*ratio, height*ratio), image)
                x += width + 18
            painter.end()
            pm = QPixmap.fromImage(canvas)
            pm.setDevicePixelRatio(ratio)
            self.image_label.setPixmap(pm)
            self._sharp_pixmap, self._sharp_zoom = pm, render_zoom
            self._sharp_revision = revision
            self.image_label.resize(round(logical_w), round(logical_h))
            self._update_page_label()
        except Exception as exc:
            if revision == self._render_revision and self.doc is render_doc:
                show_error(self, 'PDF Render Error', str(exc))
        finally:
            self._busy__render_pixmap_page = False

    def _on_page_mode_changed(self, label: str) -> None:
        self.page_view_mode = "2up" if "2 pages" in str(label).lower() else "1up"
        self._sync_rotation_controls()
        self.current_page = self._normalize_page_for_mode(self.current_page)
        if self._fit_mode:
            self.fit_to_page()
        else:
            self.refresh_view()

    def _sync_rotation_controls(self) -> None:
        can_rotate = not self._is_two_page_mode()
        self.rotate_ccw_btn.setVisible(can_rotate)
        self.rotate_cw_btn.setVisible(can_rotate)
        self.rotation_label.setVisible(can_rotate)
        self.rotate_ccw_btn.setEnabled(can_rotate)
        self.rotate_cw_btn.setEnabled(can_rotate)

    def _is_two_page_mode(self) -> bool:
        return bool(self.use_pixmap and self.page_view_mode == "2up")

    def _normalize_page_for_mode(self, page_num: int) -> int:
        try:
            page = int(page_num)
        except Exception:
            page = 0
        if self.page_count:
            page = max(0, min(page, self.page_count - 1))
        if not self._is_two_page_mode():
            return page
        if page <= 0:
            return 0
        return 1 + (((page - 1) // 2) * 2)


# ---------------------------------------------------------------------------
# Questionnaire Widgets
# ---------------------------------------------------------------------------

class QuestionNavigator(QWidget):
    """Sidebar question navigator."""

    def __init__(self, num_questions: int, on_select=None, parent=None):
        super().__init__(parent)
        self.num_questions = num_questions
        self.on_select = on_select
        self.question_buttons: Dict[int, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        self.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")

        title = QLabel("Questions")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)

        for i in range(1, self.num_questions + 1):
            btn = QPushButton(str(i))
            btn.setFixedSize(36, 36)
            btn.setStyleSheet(self._button_style_for_bg(Colors.WARNING))
            btn.clicked.connect(lambda _, q=i: self.select_question(q))
            self.question_buttons[i] = btn
            container_layout.addWidget(btn)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def select_question(self, question_num: int):
        self._set_current(question_num)
        if self.on_select:
            self.on_select(question_num)

    def _set_current(self, q_num: int):
        for btn in self.question_buttons.values():
            btn.setStyleSheet(self._button_style_for_bg(Colors.TEXT_GRAY))
        if q_num in self.question_buttons:
            self.question_buttons[q_num].setStyleSheet(self._button_style_for_bg(Colors.WARNING))

    def update_results(self, correct_answers: Dict[str, str], user_answers: Dict[str, str]) -> int:
        correct_count = 0
        for q in range(1, self.num_questions + 1):
            user_ans = user_answers.get(str(q), "")
            correct_ans = correct_answers.get(str(q), "")
            btn = self.question_buttons.get(q)
            if not btn:
                continue
            if not user_ans:
                btn.setStyleSheet(self._button_style_for_bg(Colors.INFO))
            elif user_ans == correct_ans:
                btn.setStyleSheet(self._button_style_for_bg(Colors.SUCCESS))
                correct_count += 1
            else:
                btn.setStyleSheet(self._button_style_for_bg(Colors.ERROR))
        return correct_count

    @staticmethod
    def _button_style_for_bg(bg_color: str) -> str:
        text_color = _contrast_text_for_bg(bg_color)
        border_color = Colors.contrast_text_for_bg(bg_color)
        return (
            f"background-color: {bg_color}; "
            f"color: {text_color}; "
            f"border: 1px solid {border_color};"
        )


class MCQQuestionnaire(QWidget):
    """MCQ questionnaire."""

    def __init__(self, num_questions=40, on_answer_change=None, parent=None):
        super().__init__(parent)
        self.num_questions = num_questions
        self.on_answer_change = on_answer_change
        self.answers: Dict[int, str] = {}
        self.radio_buttons: Dict[int, Dict[str, QPushButton]] = {}
        self.question_widgets: Dict[int, QWidget] = {}
        self._row_widgets: List[QWidget] = []
        self._enabled = True
        self._last_correct_answers: Dict[str, str] = {}
        self._container_widget: Optional[QWidget] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.progress_label = QLabel("0/0 answered")
        self.progress_label.setStyleSheet(f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};")
        layout.addWidget(self.progress_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        container = QWidget()
        self._container_widget = container
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(6, 6, 6, 6)
        container_layout.setSpacing(6)

        for i in range(1, self.num_questions + 1):
            row_widget = QWidget()
            row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(4, 2, 4, 2)
            q_label = QLabel(f"Q{i}")
            q_label.setFixedWidth(30)
            q_label.setStyleSheet(
                f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)}; background-color: transparent;"
            )
            row.addWidget(q_label)

            self.radio_buttons[i] = {}
            for opt in ["A", "B", "C", "D"]:
                btn = QPushButton(opt)
                btn.setCheckable(True)
                btn.setFixedWidth(30)
                btn.setStyleSheet(self._base_option_style())
                btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                btn.installEventFilter(self)
                btn.clicked.connect(lambda _, q=i, o=opt: self._set_answer(q, o))
                self.radio_buttons[i][opt] = btn
                row.addWidget(btn)

            self._row_widgets.append(row_widget)
            self.question_widgets[i] = row_widget
            container_layout.addWidget(row_widget)

        container_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll)
        self._apply_container_background_style()


    def _container_background_style(self) -> str:
        return f"background-color: {Colors.BG_LIGHT}; border: none;"

    def _apply_container_background_style(self) -> None:
        style = self._container_background_style()
        self.scroll.setStyleSheet(style)
        viewport = self.scroll.viewport()
        if viewport is not None:
            viewport.setStyleSheet(style)
        if self._container_widget:
            self._container_widget.setStyleSheet(style)
        for row in self._row_widgets:
            row.setStyleSheet("background-color: transparent; border: none;")
            for label in row.findChildren(QLabel):
                label.setStyleSheet(
                    f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)}; background-color: transparent;"
                )

    def eventFilter(self, watched, event):  # type: ignore[override]
        if isinstance(watched, QPushButton):
            etype = event.type()
            if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if self._handle_option_key_navigation(watched, event):
                    return True
        return super().eventFilter(watched, event)


    def _is_mcq_option_button(self, button: QPushButton) -> bool:
        for options in self.radio_buttons.values():
            for candidate in options.values():
                if button is candidate:
                    return True
        return False

    def _mcq_option_position(self, button: QPushButton) -> Optional[Tuple[int, int]]:
        ordered_questions = sorted(self.radio_buttons.keys())
        option_order = ["A", "B", "C", "D"]
        for row_idx, q_num in enumerate(ordered_questions):
            options = self.radio_buttons.get(q_num, {})
            for col_idx, option in enumerate(option_order):
                if options.get(option) is button:
                    return row_idx, col_idx
        return None

    def _mcq_button_at(self, row_idx: int, col_idx: int) -> Optional[QPushButton]:
        ordered_questions = sorted(self.radio_buttons.keys())
        if row_idx < 0 or row_idx >= len(ordered_questions):
            return None
        q_num = ordered_questions[row_idx]
        option_order = ["A", "B", "C", "D"]
        if col_idx < 0 or col_idx >= len(option_order):
            return None
        candidate = self.radio_buttons.get(q_num, {}).get(option_order[col_idx])
        return candidate if isinstance(candidate, QPushButton) else None

    def _handle_option_key_navigation(self, watched: QPushButton, event: QKeyEvent) -> bool:
        if not self._is_mcq_option_button(watched):
            return False
        if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return False

        key = event.key()
        position = self._mcq_option_position(watched)
        if position is None:
            return False
        row_idx, col_idx = position
        if key == Qt.Key.Key_Left:
            target = self._mcq_button_at(row_idx, col_idx - 1)
        elif key == Qt.Key.Key_Right:
            target = self._mcq_button_at(row_idx, col_idx + 1)
        elif key == Qt.Key.Key_Up:
            target = self._mcq_button_at(row_idx - 1, col_idx)
        elif key == Qt.Key.Key_Down:
            target = self._mcq_button_at(row_idx + 1, col_idx)
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            watched.click()
            return True
        else:
            return False

        if isinstance(target, QPushButton) and target.isEnabled():
            workspace = getattr(self.window(), '_studio_workspace', None)
            if workspace:
                for question, options in self.radio_buttons.items():
                    if target in options.values():
                        workspace.select_question(str(question))
                        break
            target.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return False


    @staticmethod
    def _base_option_style() -> str:
        info_text = _contrast_text_for_bg(Colors.INFO)
        secondary_text = _contrast_text_for_bg(Colors.SECONDARY)
        info_border = _mix_hex(Colors.INFO, Colors.BG_DARK, 0.34)
        checked_border = _mix_hex(Colors.SECONDARY, Colors.BG_DARK, 0.30)
        return (
            "QPushButton {"
            f"background-color: {Colors.INFO};"
            f"color: {info_text};"
            f"border: 1px solid {info_border};"
            "border-radius: 8px;"
            "padding: 4px;"
            "font-weight: 700;"
            "}"
            "QPushButton:checked {"
            f"background-color: {Colors.SECONDARY};"
            f"color: {secondary_text};"
            f"border: 1px solid {checked_border};"
            "}"
        )

    @staticmethod
    def _success_option_style() -> str:
        success_text = _contrast_text_for_bg(Colors.SUCCESS)
        return f"QPushButton {{ background-color: {Colors.SUCCESS}; color: {success_text}; border-radius: 6px; padding: 4px; }}"

    @staticmethod
    def _error_option_style() -> str:
        error_text = _contrast_text_for_bg(Colors.ERROR)
        return f"QPushButton {{ background-color: {Colors.ERROR}; color: {error_text}; border-radius: 6px; padding: 4px; }}"

    def apply_runtime_theme(self) -> None:
        self.progress_label.setStyleSheet(f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};")
        self._apply_container_background_style()
        if self._last_correct_answers:
            self.highlight_results(self._last_correct_answers)
        else:
            for options in self.radio_buttons.values():
                for button in options.values():
                    button.setStyleSheet(self._base_option_style())

    def _set_answer(self, q_num: int, option: str):
        if not self._enabled:
            return
        for opt, btn in self.radio_buttons[q_num].items():
            btn.setChecked(opt == option)
            btn.setStyleSheet(self._base_option_style())
        self.answers[q_num] = option
        self._update_progress()
        if self.on_answer_change:
            self.on_answer_change(q_num)

    def _update_progress(self):
        answered = len([v for v in self.answers.values() if v])
        self.progress_label.setText(f"{answered}/{self.num_questions} answered")

    def get_answers(self):
        return {str(q): a for q, a in self.answers.items() if a}

    def apply_saved_answers(self, saved_answers: Dict[str, Any]) -> None:
        if not isinstance(saved_answers, dict):
            return
        for raw_qid, raw_value in saved_answers.items():
            try:
                q_num = int(str(raw_qid).strip())
            except Exception:
                continue
            option = str(raw_value or "").strip().upper()
            if not option:
                continue
            options = self.radio_buttons.get(q_num)
            if not options or option not in options:
                continue
            for opt, btn in options.items():
                btn.setChecked(opt == option)
            self.answers[q_num] = option
        self._update_progress()

    def get_completion_state(self) -> Dict[str, bool]:
        return {str(i): bool(self.answers.get(i, "")) for i in range(1, self.num_questions + 1)}

    def highlight_results(self, correct_answers: Dict[str, str]):
        self._last_correct_answers = dict(correct_answers or {})
        for q, options in self.radio_buttons.items():
            user_ans = self.answers.get(q, "")
            correct_ans = correct_answers.get(str(q), "")
            for opt, btn in options.items():
                # Reset base color
                base = self._base_option_style()
                if not user_ans:
                    # Skipped: show correct in green, others default
                    if opt == correct_ans:
                        btn.setStyleSheet(self._success_option_style())
                    else:
                        btn.setStyleSheet(base)
                elif user_ans == correct_ans and opt == correct_ans:
                    btn.setStyleSheet(self._success_option_style())
                elif user_ans != correct_ans and opt == correct_ans:
                    btn.setStyleSheet(self._success_option_style())
                elif user_ans != correct_ans and opt == user_ans:
                    btn.setStyleSheet(self._error_option_style())
                else:
                    btn.setStyleSheet(base)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        for options in self.radio_buttons.values():
            for btn in options.values():
                btn.setEnabled(enabled)

    def set_answer_inputs_enabled(self, enabled: bool) -> None:
        self.set_enabled(bool(enabled))

    def scroll_to_question(self, q_num: int):
        widget = self.question_widgets.get(q_num)
        if widget:
            try:
                self.scroll.ensureWidgetVisible(widget)
            except Exception:
                try:
                    bar = self.scroll.verticalScrollBar()
                    bar.setValue(widget.y())
                except Exception:
                    pass


class SuperscriptTextEdit(QTextEdit):
    """Rich-text answer editor with context-menu formatting and caret/script serialization."""

    _SUPERSCRIPT_FONT_SCALE = 0.72
    _SUBSCRIPT_FONT_SCALE = 0.82

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptRichText(True)
        self._rich_menu_installed = False

    def _base_point_size(self) -> float:
        base = float(self.font().pointSizeF() or 0.0)
        if base <= 0.0:
            base = float(self.font().pointSize() or 12)
        return max(8.0, base)

    @staticmethod
    def _parse_caret_notation(text: str) -> List[Tuple[str, str]]:
        source = str(text or "")
        out: List[Tuple[str, str]] = []
        normal_parts: List[str] = []
        index = 0
        length = len(source)

        def _flush_normal() -> None:
            if normal_parts:
                out.append(("".join(normal_parts), "normal"))
                normal_parts.clear()

        while index < length:
            ch = source[index]
            if ch not in {"^", "_"}:
                normal_parts.append(ch)
                index += 1
                continue

            if index + 1 >= length:
                normal_parts.append(ch)
                index += 1
                continue

            nxt = source[index + 1]
            if ch == "_" and nxt != "{":
                # Keep plain underscores (for words like snake_case) untouched.
                normal_parts.append("_")
                index += 1
                continue

            if nxt == "{":
                close = source.find("}", index + 2)
                if close == -1:
                    normal_parts.append(ch)
                    index += 1
                    continue
                content = source[index + 2 : close]
                _flush_normal()
                if content:
                    out.append((content, "super" if ch == "^" else "sub"))
                index = close + 1
                continue

            _flush_normal()
            out.append((nxt, "super"))
            index += 2

        _flush_normal()
        return out

    def _script_format(self, mode: str) -> QTextCharFormat:
        fmt = QTextCharFormat()
        base_size = self._base_point_size()
        mode_key = str(mode or "").strip().lower()
        if mode_key == "super":
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
            fmt.setFontPointSize(max(6.0, base_size * self._SUPERSCRIPT_FONT_SCALE))
        elif mode_key == "sub":
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSubScript)
            fmt.setFontPointSize(max(6.0, base_size * self._SUBSCRIPT_FONT_SCALE))
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
            fmt.setFontPointSize(base_size)
        return fmt

    def set_caret_text(self, text: str) -> None:
        parts = self._parse_caret_notation(str(text or ""))
        self.clear()

        cursor = self.textCursor()
        for chunk, mode in parts:
            if not chunk:
                continue
            cursor.insertText(chunk, self._script_format(mode))
        self.setTextCursor(cursor)
        # Restoring an answer ending in a script must not make subsequent typing
        # inherit superscript/subscript formatting.
        self.mergeCurrentCharFormat(self._script_format("normal"))

    def to_caret_text(self) -> str:
        doc: QTextDocument = self.document()
        plain = self.toPlainText()
        if not plain:
            return ""

        script_flags: List[str] = []
        for idx, ch in enumerate(plain):
            if ch == "\n":
                script_flags.append("normal")
                continue
            cursor = QTextCursor(doc)
            cursor.setPosition(idx)
            cursor.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
            fmt = cursor.charFormat()
            alignment = fmt.verticalAlignment()
            if alignment == QTextCharFormat.VerticalAlignment.AlignSuperScript:
                script_flags.append("super")
            elif alignment == QTextCharFormat.VerticalAlignment.AlignSubScript:
                script_flags.append("sub")
            else:
                script_flags.append("normal")

        output_parts: List[str] = []
        run_chars: List[str] = []
        run_mode: Optional[str] = None

        def _flush() -> None:
            nonlocal run_chars, run_mode
            if run_mode is None or not run_chars:
                run_chars = []
                run_mode = None
                return
            text_chunk = "".join(run_chars)
            if run_mode == "super":
                if len(text_chunk) == 1:
                    output_parts.append(f"^{text_chunk}")
                else:
                    output_parts.append(f"^{{{text_chunk}}}")
            elif run_mode == "sub":
                output_parts.append(f"_{{{text_chunk}}}")
            else:
                output_parts.append(text_chunk)
            run_chars = []
            run_mode = None

        for ch, mode in zip(plain, script_flags):
            if ch == "\n":
                _flush()
                output_parts.append("\n")
                continue

            if run_mode is None:
                run_mode = mode
                run_chars.append(ch)
                continue

            if mode == run_mode:
                run_chars.append(ch)
                continue

            _flush()
            run_mode = mode
            run_chars.append(ch)

        _flush()
        return "".join(output_parts)

    def is_superscript_mode_active(self) -> bool:
        # Legacy compatibility method for older navigation checks.
        return False

    def _selection_formats(self) -> List[QTextCharFormat]:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return []
        start = min(cursor.selectionStart(), cursor.selectionEnd())
        end = max(cursor.selectionStart(), cursor.selectionEnd())
        doc = self.document()
        formats: List[QTextCharFormat] = []
        for idx in range(start, end):
            if str(doc.characterAt(idx)) == "\n":
                continue
            probe = QTextCursor(doc)
            probe.setPosition(idx)
            probe.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
            formats.append(probe.charFormat())
        return formats

    def _merge_selection_format(self, fmt: QTextCharFormat) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            self.mergeCurrentCharFormat(fmt)
            return
        selection_end = max(cursor.selectionStart(), cursor.selectionEnd())
        cursor.beginEditBlock()
        cursor.mergeCharFormat(fmt)
        cursor.endEditBlock()
        cursor.clearSelection()
        cursor.setPosition(selection_end)
        self.setTextCursor(cursor)
        insertion_fmt = self.currentCharFormat()
        insertion_fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        insertion_fmt.setFontPointSize(self._base_point_size())
        self.setCurrentCharFormat(insertion_fmt)

    def _toggle_font_weight(self) -> None:
        formats = self._selection_formats()
        if not formats:
            formats = [self.currentCharFormat()]
        all_bold = all(
            int(fmt.fontWeight()) >= int(QFont.Weight.Bold)
            for fmt in formats
        )
        update = QTextCharFormat()
        update.setFontWeight(QFont.Weight.Normal if all_bold else QFont.Weight.Bold)
        self._merge_selection_format(update)

    def _toggle_italic(self) -> None:
        formats = self._selection_formats()
        if not formats:
            formats = [self.currentCharFormat()]
        all_italic = all(bool(fmt.fontItalic()) for fmt in formats)
        update = QTextCharFormat()
        update.setFontItalic(not all_italic)
        self._merge_selection_format(update)

    def _toggle_underline(self) -> None:
        formats = self._selection_formats()
        if not formats:
            formats = [self.currentCharFormat()]
        all_underlined = all(bool(fmt.fontUnderline()) for fmt in formats)
        update = QTextCharFormat()
        update.setFontUnderline(not all_underlined)
        self._merge_selection_format(update)

    def _set_script_mode(self, mode: str) -> None:
        self._merge_selection_format(self._script_format(mode))

    def install_rich_text_context_menu(self) -> None:
        if self._rich_menu_installed:
            return
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_rich_text_context_menu)
        self._rich_menu_installed = True

    def keyPressEvent(self, event):
        if not self.isReadOnly() and event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            commands = {
                (Qt.Key.Key_B, False): self._toggle_font_weight,
                (Qt.Key.Key_I, False): self._toggle_italic,
                (Qt.Key.Key_U, False): self._toggle_underline,
                (Qt.Key.Key_P, True): lambda: self._set_script_mode("super"),
                (Qt.Key.Key_B, True): lambda: self._set_script_mode("sub"),
                (Qt.Key.Key_N, True): lambda: self._set_script_mode("normal"),
            }
            command = commands.get((event.key(), shift))
            if command:
                command()
                event.accept()
                return
        super().keyPressEvent(event)

    def show_rich_text_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setObjectName("ExamInputContextMenu")
        menu.setStyleSheet(f"QMenu {{background:{Colors.BG_CARD};color:{Colors.TEXT_LIGHT};border:1px solid {Colors.BG_LIGHT};padding:4px;}} QMenu::item {{font-size:14px;min-height:0px;padding:5px 16px;}} QMenu::item:selected {{background:{Colors.BG_LIGHT};}} QMenu::item:disabled {{color:{Colors.TEXT_GRAY};}}")
        selected = self.textCursor().hasSelection()
        editable = not self.isReadOnly()
        prefix = "Meta" if sys.platform == "darwin" else "Ctrl"
        commands = [
            ("Undo", self.undo, editable and self.document().isUndoAvailable(), "Z"),
            ("Redo", self.redo, editable and self.document().isRedoAvailable(), "Shift+Z"),
            ("Cut", self.cut, editable and selected, "X"),
            ("Copy", self.copy, selected, "C"),
            ("Paste", self.paste, editable and self.canPaste(), "V"),
            ("Delete", self._delete_selection, editable and selected, None),
            ("Select All", self.selectAll, not self.document().isEmpty(), "A"),
        ]
        for label, callback, enabled, sequence in commands:
            if label == "Cut":
                menu.addSeparator()
            action = menu.addAction(label, callback)
            action.setEnabled(enabled)
            if sequence:
                action.setShortcut(QKeySequence(prefix + "+" + sequence))
        menu.addSeparator()
        formatting = menu.addMenu("Formatting")
        formatting.setEnabled(editable)
        for label, callback, sequence in [
            ("Bold",self._toggle_font_weight,"B"),
            ("Italic",self._toggle_italic,"I"),
            ("Underline",self._toggle_underline,"U"),
            ("Superscript",lambda:self._set_script_mode("super"),"Shift+P"),
            ("Subscript",lambda:self._set_script_mode("sub"),"Shift+B"),
            ("Normal Text",lambda:self._set_script_mode("normal"),"Shift+N"),
        ]:
            action = formatting.addAction(label, callback)
            action.setShortcut(QKeySequence(prefix+"+"+sequence))
        menu.exec(self.mapToGlobal(pos))
        menu.deleteLater()

    def _delete_selection(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        cursor.removeSelectedText()
        self.setTextCursor(cursor)


def _editor_to_caret_text(editor: Any) -> str:
    if hasattr(editor, "to_caret_text"):
        try:
            return str(editor.to_caret_text())
        except Exception:
            pass
    if hasattr(editor, "toPlainText"):
        try:
            return str(editor.toPlainText())
        except Exception:
            pass
    if hasattr(editor, "text"):
        try:
            return str(editor.text())
        except Exception:
            pass
    return str(editor or "")


def _editor_set_caret_text(editor: Any, text: str) -> None:
    if hasattr(editor, "set_caret_text"):
        try:
            editor.set_caret_text(str(text or ""))
            return
        except Exception:
            pass
    if hasattr(editor, "setPlainText"):
        try:
            editor.setPlainText(str(text or ""))
            return
        except Exception:
            pass
    if hasattr(editor, "setText"):
        try:
            editor.setText(str(text or ""))
            return
        except Exception:
            pass


class ResizableAnswerTextEdit(SuperscriptTextEdit):
    """Rich-text answer field with bottom-edge resize drag zone."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        min_height: int = 72,
        max_height: int = 560,
        default_height: int = 86,
    ):
        super().__init__(parent)
        self._resize_dragging = False
        self._resize_zone_px = 10
        self._resize_start_global_y = 0.0
        self._resize_start_height = 0
        self._min_height = max(44, int(min_height))
        self._max_height = max(self._min_height + 20, int(max_height))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFixedHeight(self._clamp_height(default_height))
        self.setToolTip("Drag the bottom edge to resize this answer box.")

    def _clamp_height(self, value: int) -> int:
        return max(self._min_height, min(self._max_height, int(value)))

    @staticmethod
    def _event_global_y(event: QMouseEvent) -> float:
        if hasattr(event, "globalPosition"):
            try:
                return float(event.globalPosition().y())  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            return float(event.globalPos().y())  # type: ignore[attr-defined]
        except Exception:
            return 0.0

    def _in_resize_zone(self, event: QMouseEvent) -> bool:
        local = event.position().toPoint() if hasattr(event, "position") else event.pos()
        return int(local.y()) >= max(0, int(self.viewport().height()) - self._resize_zone_px)

    def _sync_resize_cursor(self, event: Optional[QMouseEvent] = None) -> None:
        if self._resize_dragging:
            self.viewport().setCursor(Qt.CursorShape.SizeVerCursor)
            return
        if event is not None and self._in_resize_zone(event):
            self.viewport().setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.viewport().unsetCursor()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._in_resize_zone(event):
            self._resize_dragging = True
            self._resize_start_global_y = self._event_global_y(event)
            self._resize_start_height = int(self.height())
            self._sync_resize_cursor(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._resize_dragging:
            delta_y = self._event_global_y(event) - self._resize_start_global_y
            next_height = self._clamp_height(int(round(self._resize_start_height + delta_y)))
            if next_height != int(self.height()):
                self.setFixedHeight(next_height)
                self.updateGeometry()
            self._sync_resize_cursor(event)
            event.accept()
            return
        self._sync_resize_cursor(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._resize_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._resize_dragging = False
            self._sync_resize_cursor(event)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):  # type: ignore[override]
        if not self._resize_dragging:
            self.viewport().unsetCursor()
        super().leaveEvent(event)


class WrittenQuestionnaire(QWidget):
    """Written questionnaire with input boxes."""

    def __init__(self, num_questions=6, on_answer_change=None, parent=None):
        super().__init__(parent)
        self.num_questions = num_questions
        self.on_answer_change = on_answer_change
        self.answers: Dict[int, ResizableAnswerTextEdit] = {}
        self.question_widgets: Dict[int, QWidget] = {}
        self._ordered_entries: List[ResizableAnswerTextEdit] = []
        self._container_widget: Optional[QWidget] = None
        self._last_correct_answers: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")
        container = QWidget()
        self._container_widget = container
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(6, 6, 6, 6)
        container_layout.setSpacing(6)
        container.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")

        for i in range(1, self.num_questions + 1):
            row_widget = QWidget()
            row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row_widget.setStyleSheet(
                "background-color: transparent; "
                f"border: 1px solid {_mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.26)}; "
                "border-radius: 8px;"
            )
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(10, 8, 10, 8)
            row.setSpacing(10)
            label = QLabel(f"Question {i}")
            label.setFixedWidth(116)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            label.setStyleSheet(
                f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)}; "
                "font-weight: 700;"
            )
            row.addWidget(label)

            entry = ResizableAnswerTextEdit(min_height=62, max_height=440, default_height=86)
            entry.setPlaceholderText("Your answer here...")
            entry.setStyleSheet(self._entry_base_style())
            entry.installEventFilter(self)
            if self.on_answer_change:
                entry.textChanged.connect(lambda q=i: self.on_answer_change(q))
            self.answers[i] = entry
            self._ordered_entries.append(entry)
            row.addWidget(entry)

            self.question_widgets[i] = row_widget
            container_layout.addWidget(row_widget)

        container_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and isinstance(watched, ResizableAnswerTextEdit)
            and watched in self._ordered_entries
        ):
            if self._handle_vertical_answer_navigation(watched, event):
                return True
        return super().eventFilter(watched, event)

    def _handle_vertical_answer_navigation(self, watched: ResizableAnswerTextEdit, event: QKeyEvent) -> bool:
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        nav_modifiers = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.MetaModifier
            | Qt.KeyboardModifier.AltModifier
        )
        if modifiers and not (modifiers & nav_modifiers):
            return False
        key = event.key()
        if key not in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            return False
        force_navigation = bool(modifiers & nav_modifiers)
        if not force_navigation:
            cursor = watched.textCursor()
            block_count = max(1, int(watched.document().blockCount()))
            at_first_line = int(cursor.blockNumber()) <= 0
            at_last_line = int(cursor.blockNumber()) >= (block_count - 1)
            if key == Qt.Key.Key_Up and not at_first_line:
                return False
            if key == Qt.Key.Key_Down and not at_last_line:
                return False

        try:
            current_idx = self._ordered_entries.index(watched)
        except ValueError:
            return False

        step = -1 if key == Qt.Key.Key_Up else 1
        next_idx = max(0, min(len(self._ordered_entries) - 1, current_idx + step))
        if next_idx == current_idx:
            return True

        target = self._ordered_entries[next_idx]
        target.setFocus(Qt.FocusReason.TabFocusReason)
        target.selectAll()
        return True

    @staticmethod
    def _entry_base_style() -> str:
        bg = _input_surface_bg()
        text_color = _contrast_text_for_bg(bg)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(bg, focus_color, 0.05)
        return (
            f"QTextEdit {{ background-color: {bg}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: 6px; }}"
            f"QTextEdit:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    @staticmethod
    def _entry_state_style(color: str) -> str:
        text_color = _contrast_text_for_bg(color)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(color, focus_color, 0.05)
        return (
            f"QTextEdit {{ background-color: {color}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: 6px; }}"
            f"QTextEdit:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    def apply_runtime_theme(self) -> None:
        self.scroll.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")
        if self._container_widget:
            self._container_widget.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")
        if self._last_correct_answers:
            self.highlight_results(self._last_correct_answers)
        else:
            for entry in self.answers.values():
                entry.setStyleSheet(self._entry_base_style())

    def get_answers(self):
        return {
            str(q): _editor_to_caret_text(entry)
            for q, entry in self.answers.items()
            if _editor_to_caret_text(entry).strip()
        }

    def apply_saved_answers(self, saved_answers: Dict[str, Any]) -> None:
        if not isinstance(saved_answers, dict):
            return
        for raw_qid, raw_value in saved_answers.items():
            try:
                q_num = int(str(raw_qid).strip())
            except Exception:
                continue
            entry = self.answers.get(q_num)
            if not entry:
                continue
            if isinstance(raw_value, dict):
                text = str(raw_value.get("value", "") or "")
            else:
                text = str(raw_value or "")
            _editor_set_caret_text(entry, text)

    def get_completion_state(self) -> Dict[str, bool]:
        return {str(q): bool(_editor_to_caret_text(entry).strip()) for q, entry in self.answers.items()}

    def set_answer_inputs_enabled(self, enabled: bool) -> None:
        editable = bool(enabled)
        for entry in self.answers.values():
            entry.setReadOnly(not editable)
            entry.setEnabled(True)

    def highlight_results(self, correct_answers: Dict[str, str]):
        self._last_correct_answers = dict(correct_answers or {})
        for q_num, entry in self.answers.items():
            user_ans = _editor_to_caret_text(entry).strip()
            correct_ans = correct_answers.get(str(q_num), "")
            if not user_ans:
                entry.setStyleSheet(self._entry_state_style(Colors.INFO))
                entry.setPlaceholderText(f"Correct answer: {correct_ans}")
            elif user_ans.lower() == correct_ans.lower():
                entry.setStyleSheet(self._entry_state_style(Colors.SUCCESS))
            else:
                entry.setStyleSheet(self._entry_state_style(Colors.ERROR))
                entry.setPlaceholderText(f"Correct answer: {correct_ans}")

    def scroll_to_question(self, q_num: int):
        widget = self.question_widgets.get(q_num)
        if widget:
            try:
                self.scroll.ensureWidgetVisible(widget)
            except Exception:
                try:
                    bar = self.scroll.verticalScrollBar()
                    bar.setValue(widget.y())
                except Exception:
                    pass


@dataclass(slots=True)
class RulerOverlayItem:
    visible: bool = False
    center: QPointF = field(default_factory=lambda: QPointF(220.0, 180.0))
    length: float = 240.0
    thickness: float = 30.0
    angle: float = 0.0


@dataclass(slots=True)
class ProtractorOverlayItem:
    visible: bool = False
    center: QPointF = field(default_factory=lambda: QPointF(260.0, 230.0))
    radius: float = 120.0
    angle: float = 0.0
    mode: str = "semi"


class DrawingCanvasWidget(QWidget):
    """Interactive drawing canvas with shapes and guide overlays."""

    zoom_changed = Signal(int)
    history_changed = Signal()
    TOOLS = ("pen", "eraser", "line", "rect", "ellipse", "triangle", "arrow")
    PROTRACTOR_MODE_SEMI = "semi"
    PROTRACTOR_MODE_ROUND = "round"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas_size = QSize(940, 560)
        self.setMinimumSize(self.canvas_size)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._space_pan = False
        self._pan_origin = None
        self.grabGesture(Qt.GestureType.PinchGesture)

        self.image = QImage(self.canvas_size, QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.transparent)

        self.tool = "pen"
        self.pen_color = QColor("#0f172a")
        self.pen_width = 3
        self.eraser_width = 18

        self.view_zoom = 1.0
        self._min_zoom = 0.25
        self._max_zoom = 4.0
        self._view_offset = QPointF(0.0, 0.0)

        self.is_drawing = False
        self.start_point: Optional[QPointF] = None
        self.last_point: Optional[QPointF] = None
        self.preview_point: Optional[QPointF] = None

        self.ruler = RulerOverlayItem()
        self.ruler.thickness = 30.0
        self.protractor = ProtractorOverlayItem()
        self.active_overlay: Optional[str] = None
        self.overlay_interaction_mode: Optional[str] = None
        self.dragging_overlay = False
        self._overlay_drag_start = QPointF()
        self._overlay_origin_center = QPointF()
        self._overlay_origin_angle = 0.0
        self._stroke_committed = False
        self._pinch_last_total_scale = 1.0

        self._initial_fit_pending = True
        self._document_layer = None
        self._background_image = QImage()
        self._pixels_per_mm = None
        self.undo_stack: List[QImage] = []
        self.redo_stack: List[QImage] = []
        self._saved_ink = False
        self._new_ink_layer()

    def set_tool(self, tool: str):
        tool_name = str(tool or "").strip().lower()
        if tool_name in self.TOOLS:
            self.tool = tool_name
            self.update()
            return
        if tool_name in {"ruler", "protractor"}:
            self.set_guide_visible(tool_name, True)

    def set_pen_color(self, color: QColor):
        self.pen_color = QColor(color)

    def set_pen_width(self, width: int):
        self.pen_width = max(1, int(width))

    def set_guide_visible(self, name: str, visible: bool):
        if name == "ruler":
            self.ruler.visible = visible
        elif name == "protractor":
            self.protractor.visible = visible
        self.update()

    def set_guide_angle(self, name: str, angle: float):
        angle = float(angle) % 360.0
        if name == "ruler":
            self.ruler.angle = angle
        elif name == "protractor":
            self.protractor.angle = angle
        self.update()

    def set_protractor_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        if normalized in {"round", "360", "circle", "full"}:
            self.protractor.mode = self.PROTRACTOR_MODE_ROUND
        else:
            self.protractor.mode = self.PROTRACTOR_MODE_SEMI
        self.update()

    def set_zoom_percent(self, percent: int) -> None:
        try:
            requested = float(percent) / 100.0
        except Exception:
            requested = 1.0
        clamped = max(self._min_zoom, min(self._max_zoom, requested))
        if abs(clamped - self.view_zoom) <= 1e-6:
            return
        center = QPointF(self.width()/2, self.height()/2)
        logical = self._view_to_image_point(center)
        self._initial_fit_pending = False
        self.view_zoom = clamped
        origin = self._image_to_view_point(logical)
        self._view_offset += center-origin
        self._clamp_view_offset()
        if self._document_layer:
            self._document_layer.schedule()
        self.zoom_changed.emit(int(round(self.view_zoom * 100.0)))
        self.update()

    def zoom_percent(self) -> int:
        return int(round(self.view_zoom * 100.0))

    def adjust_zoom_steps(self, steps: float) -> None:
        try:
            delta = float(steps)
        except Exception:
            return
        if abs(delta) <= 1e-6:
            return
        next_zoom = float(self.view_zoom) * math.exp(delta * 0.12)
        self.set_zoom_percent(int(round(next_zoom * 100.0)))

    def clear_canvas(self):
        self._push_undo_state()
        self.image.fill(Qt.GlobalColor.transparent)
        self._saved_ink = False
        self.update()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.image.copy())
        self.image = self.undo_stack.pop()
        self.history_changed.emit()
        self.update()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.image.copy())
        self.image = self.redo_stack.pop()
        self.history_changed.emit()
        self.update()

    def load_reference(self, source):
        from UI.drawing_document import DrawingDocumentLayer
        if isinstance(source, dict):
            layer = DrawingDocumentLayer(self)
            if not layer.set_source(source):
                layer.deleteLater()
                return
            self._document_layer = layer
            clip = source['clip']
            self.canvas_size = QSize(max(1, math.ceil(clip[2]-clip[0])), max(1, math.ceil(clip[3]-clip[1])))
            self._pixels_per_mm = 72.0/25.4
            self._new_ink_layer()
        elif source:
            image = QImage(str(source))
            if not image.isNull():
                self._background_image = image
                self.canvas_size = image.size()
                self._new_ink_layer()
        self._initial_fit_pending = True
        self.update()

    def _new_ink_layer(self):
        ratio = min(2.0, math.sqrt(MAX_BACKING_PIXELS/(self.canvas_size.width()*self.canvas_size.height())))
        self.image = QImage(max(1,round(self.canvas_size.width()*ratio)), max(1,round(self.canvas_size.height()*ratio)), QImage.Format.Format_ARGB32_Premultiplied)
        self.image.setDevicePixelRatio(ratio)
        self.image.fill(Qt.GlobalColor.transparent)

    def load_image(self, path: str):
        if not path or not os.path.isfile(path):
            return
        loaded = QImage(path)
        if loaded.isNull():
            return
        if loaded.width()*loaded.height() > MAX_BACKING_PIXELS:
            scale = backing_scale(loaded.width(),loaded.height(),minimum_edge=0)
            loaded = loaded.scaled(max(1,round(loaded.width()*scale)),max(1,round(loaded.height()*scale)),
                Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        from UI.drawing_document import decode_project, DrawingDocumentLayer
        project = decode_project(loaded)
        if project:
            self._saved_ink = True
            size, ink, source, background = project
            layer = DrawingDocumentLayer(self)
            if source and layer.set_source(source):
                self._document_layer = layer
                self.canvas_size = size
                self.image = ink
                self._pixels_per_mm = 72.0/25.4
            elif not source:
                layer.deleteLater()
                self.canvas_size = size
                self.image = ink
                self._background_image = background
            else:
                layer.deleteLater()
                self.canvas_size = size
                self._background_image = loaded
                self._new_ink_layer()
        else:
            # Legacy/exported images retain their native coordinates and aspect.
            self.canvas_size = loaded.size()
            self._background_image = loaded
            self._new_ink_layer()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._initial_fit_pending = True
        self._view_offset = QPointF()
        self.update()

    def save_image(self, path: str) -> bool:
        if not path:
            return False
        try:
            from UI.drawing_document import PROJECT_KEY, encode_project
            from Core.atomic_storage import atomic_write_bytes
            source = self._document_layer.source if self._document_layer else None
            background = self._document_layer.export_image() if self._document_layer else self._background_image
            ratio = backing_scale(self.canvas_size.width(), self.canvas_size.height(), minimum_edge=4096)
            result = QImage(max(1,round(self.canvas_size.width()*ratio)), max(1,round(self.canvas_size.height()*ratio)), QImage.Format.Format_RGB32)
            result.fill(QColor('white'))
            painter = QPainter(result)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            rect = QRectF(0,0,result.width(),result.height())
            if not background.isNull():
                painter.drawImage(rect, background)
            painter.drawImage(rect, self.image)
            painter.end()
            result.setText(PROJECT_KEY, encode_project(self.image,self.canvas_size,source,self._background_image))
            from PySide6.QtCore import QByteArray, QBuffer, QIODevice
            data = QByteArray(); buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not result.save(buffer,'PNG'):
                return False
            buffer.close()
            atomic_write_bytes(path,bytes(data))
            return True
        except Exception:
            logging.exception('Could not save drawing project')
            return False

    def close_document_layer(self):
        if self._document_layer:
            self._document_layer.close()

    def _push_undo_state(self):
        self.undo_stack.append(self.image.copy())
        # Shared images detach on the next stroke; bound worst-case undo RAM.
        max_entries = max(1,min(20,48*1024*1024//max(1,self.image.sizeInBytes())))
        del self.undo_stack[:-max_entries]
        self.redo_stack.clear()
        self.history_changed.emit()

    def _is_in_bounds(self, pt: QPointF) -> bool:
        return 0.0 <= float(pt.x()) < float(self.canvas_size.width()) and 0.0 <= float(pt.y()) < float(self.canvas_size.height())

    def _clamp_to_bounds(self, pt: QPointF) -> QPointF:
        max_x = max(0.0, float(self.canvas_size.width() - 1))
        max_y = max(0.0, float(self.canvas_size.height() - 1))
        return QPointF(
            max(0.0, min(float(pt.x()), max_x)),
            max(0.0, min(float(pt.y()), max_y)),
        )

    def _canvas_center(self) -> QPointF:
        return QPointF(float(self.canvas_size.width()) / 2.0, float(self.canvas_size.height()) / 2.0)

    def _max_view_offset(self) -> QPointF:
        viewport_w = float(max(1, self.width()))
        viewport_h = float(max(1, self.height()))
        content_w = float(self.canvas_size.width()) * float(self.view_zoom)
        content_h = float(self.canvas_size.height()) * float(self.view_zoom)
        max_x = max(0.0, (content_w - viewport_w) * 0.5)
        max_y = max(0.0, (content_h - viewport_h) * 0.5)
        return QPointF(max_x, max_y)

    def _clamp_view_offset(self) -> None:
        limit = self._max_view_offset()
        self._view_offset = QPointF(
            max(-float(limit.x()), min(float(self._view_offset.x()), float(limit.x()))),
            max(-float(limit.y()), min(float(self._view_offset.y()), float(limit.y()))),
        )

    def _pan_view_by(self, dx: float, dy: float) -> None:
        if self.view_zoom <= 1.0:
            return
        self._view_offset = QPointF(float(self._view_offset.x()) + float(dx), float(self._view_offset.y()) + float(dy))
        self._clamp_view_offset()
        self.update()

    def _view_origin(self):
        return QPointF((self.width()-self.canvas_size.width()*self.view_zoom)/2,
                       (self.height()-self.canvas_size.height()*self.view_zoom)/2) + self._view_offset

    def _view_to_image_point(self, pt: QPointF) -> QPointF:
        return (pt-self._view_origin())/max(1e-6,self.view_zoom)

    def _image_to_view_point(self, pt: QPointF) -> QPointF:
        return pt*self.view_zoom+self._view_origin()

    def _apply_view_transform(self, painter: QPainter) -> None:
        painter.translate(self._view_origin())
        painter.scale(self.view_zoom,self.view_zoom)

    @staticmethod
    def _distance(a: QPointF, b: QPointF) -> float:
        return math.hypot(float(a.x()) - float(b.x()), float(a.y()) - float(b.y()))

    @staticmethod
    def _dot(a: QPointF, b: QPointF) -> float:
        return (float(a.x()) * float(b.x())) + (float(a.y()) * float(b.y()))

    @staticmethod
    def _sub(a: QPointF, b: QPointF) -> QPointF:
        return QPointF(float(a.x()) - float(b.x()), float(a.y()) - float(b.y()))

    @staticmethod
    def _add(a: QPointF, b: QPointF) -> QPointF:
        return QPointF(float(a.x()) + float(b.x()), float(a.y()) + float(b.y()))

    @staticmethod
    def _mul(v: QPointF, scalar: float) -> QPointF:
        return QPointF(float(v.x()) * float(scalar), float(v.y()) * float(scalar))

    def _point_in_overlay_axes(self, point: QPointF, center: QPointF, angle: float) -> QPointF:
        return local_point(self._image_to_view_point(point), center, angle)

    def _hit_test_ruler(self, point: QPointF) -> Optional[Tuple[str, float]]:
        if not self.ruler.visible:
            return None
        local = self._point_in_overlay_axes(point, self.ruler.center, self.ruler.angle)
        half_len = float(self.ruler.length) / 2.0
        half_thickness = float(getattr(self.ruler, "thickness", 30.0)) / 2.0
        rotate_handle = QPointF(half_len + 24.0, 0.0)
        handle_distance = self._distance(local, rotate_handle)
        if handle_distance <= 16.0:
            return ("rotate", handle_distance * 0.45)
        if -half_len <= float(local.x()) <= half_len and -half_thickness <= float(local.y()) <= half_thickness:
            score = abs(float(local.y())) + 8.0
            return ("move", score)
        return None

    def _hit_test_protractor(self, point: QPointF) -> Optional[Tuple[str, float]]:
        if not self.protractor.visible:
            return None
        local = self._point_in_overlay_axes(point, self.protractor.center, self.protractor.angle)
        dist = math.hypot(float(local.x()), float(local.y()))
        radius = float(self.protractor.radius)
        is_round = self.protractor.mode == self.PROTRACTOR_MODE_ROUND
        rotate_handle = QPointF(0.0, -(radius + 18.0))
        handle_distance = self._distance(local, rotate_handle)
        if handle_distance <= 14.0:
            return ("rotate", handle_distance * 0.45)
        if dist <= 18.0:
            return ("move", dist)
        if dist <= radius + 16.0 and (is_round or local.y() <= 12):
            return ("move", abs(dist - radius) + 4.0)
        # Semi protractor: allow dragging from anywhere in the visible upper body
        # and from the baseline.
        if (not is_round) and float(local.y()) <= 12.0 and dist <= radius + 16.0:
            return ("move", abs(dist - radius) + max(0.0, float(local.y())))
        if (not is_round) and abs(float(local.y())) <= 12.0 and abs(float(local.x())) <= radius + 12.0:
            return ("move", abs(float(local.y())) + 6.0)
        return None

    def _point_inside_protractor_body(self, point: QPointF, tolerance: float = 8.0) -> bool:
        if not self.protractor.visible:
            return False
        local = self._point_in_overlay_axes(point, self.protractor.center, self.protractor.angle)
        dist = math.hypot(float(local.x()), float(local.y()))
        radius = float(self.protractor.radius) + float(max(0.0, tolerance))
        if self.protractor.mode == self.PROTRACTOR_MODE_ROUND:
            return dist <= radius
        return dist <= radius and float(local.y()) <= 10.0

    def _overlay_hit_test(self, point: QPointF) -> Tuple[Optional[str], Optional[str]]:
        ruler_hit = self._hit_test_ruler(point)
        protractor_hit = self._hit_test_protractor(point)
        if ruler_hit and not protractor_hit:
            return "ruler", ruler_hit[0]
        if protractor_hit and not ruler_hit:
            return "protractor", protractor_hit[0]
        if ruler_hit and protractor_hit:
            if self._point_inside_protractor_body(point, tolerance=10.0):
                return "protractor", protractor_hit[0]
            ruler_mode, ruler_score = ruler_hit
            protractor_mode, protractor_score = protractor_hit
            if float(protractor_score) <= (float(ruler_score) + 4.0):
                return "protractor", protractor_mode
            return "ruler", ruler_mode
        return None, None

    def _current_overlay(self) -> Optional[object]:
        if self.active_overlay == "ruler":
            return self.ruler
        if self.active_overlay == "protractor":
            return self.protractor
        return None

    def _projection_on_ruler_axis(self, point: QPointF) -> QPointF:
        axis = QPointF(math.cos(math.radians(self.ruler.angle)), math.sin(math.radians(self.ruler.angle)))
        relative = self._sub(point, self._view_to_image_point(self.ruler.center))
        t = self._dot(relative, axis)
        return self._add(self._view_to_image_point(self.ruler.center), self._mul(axis, t))

    def _projection_on_ruler_top_edge(self, point: QPointF) -> QPointF:
        axis = QPointF(math.cos(math.radians(self.ruler.angle)), math.sin(math.radians(self.ruler.angle)))
        normal = QPointF(-float(axis.y()), float(axis.x()))
        relative = self._sub(point, self._view_to_image_point(self.ruler.center))
        t = self._dot(relative, axis)
        half_thickness = float(getattr(self.ruler, "thickness", 30.0)) * 0.5 / self.view_zoom
        top_edge_offset = self._mul(normal, -half_thickness)
        return self._add(self._add(self._view_to_image_point(self.ruler.center), self._mul(axis, t)), top_edge_offset)

    def _distance_to_ruler_axis(self, point: QPointF) -> float:
        axis = QPointF(math.cos(math.radians(self.ruler.angle)), math.sin(math.radians(self.ruler.angle)))
        relative = self._sub(point, self._view_to_image_point(self.ruler.center))
        return abs((float(relative.x()) * float(axis.y())) - (float(relative.y()) * float(axis.x())))

    def _point_near_ruler_body(self, point: QPointF, margin: float = 0.0) -> bool:
        if not self.ruler.visible:
            return False
        local = self._point_in_overlay_axes(point, self.ruler.center, self.ruler.angle)
        half_len = (float(self.ruler.length) / 2.0) + max(0.0, float(margin))
        half_thickness = (float(getattr(self.ruler, "thickness", 30.0)) / 2.0) + max(0.0, float(margin))
        return (
            -half_len <= float(local.x()) <= half_len
            and -half_thickness <= float(local.y()) <= half_thickness
        )

    def _snap_line_to_ruler(self, start: QPointF, end: QPointF) -> Tuple[QPointF, QPointF]:
        if not self.ruler.visible:
            return start, end

        if not (self._point_near_ruler_body(start, margin=12.0) or self._point_near_ruler_body(end, margin=12.0)):
            return start, end

        snapped_start = self._projection_on_ruler_top_edge(start)
        snapped_end = self._projection_on_ruler_top_edge(end)
        return self._clamp_to_bounds(snapped_start), self._clamp_to_bounds(snapped_end)

    def _snap_pen_segment_to_ruler(self, start: QPointF, end: QPointF) -> Tuple[QPointF, QPointF, bool]:
        if not self.ruler.visible:
            return start, end, False
        if not (self._point_near_ruler_body(start, margin=10.0) or self._point_near_ruler_body(end, margin=10.0)):
            return start, end, False
        snapped_start = self._clamp_to_bounds(self._projection_on_ruler_top_edge(start))
        snapped_end = self._clamp_to_bounds(self._projection_on_ruler_top_edge(end))
        return snapped_start, snapped_end, True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Resizing a viewport must never resize the saved document or ink layer.
        if self._initial_fit_pending and self.width()>50 and self.height()>50:
            self._initial_fit_pending = False
            fit = min((self.width()-24)/self.canvas_size.width(), (self.height()-24)/self.canvas_size.height())
            self.view_zoom = max(self._min_zoom,min(self._max_zoom,fit))
            self.zoom_changed.emit(self.zoom_percent())
        self._clamp_view_offset()
        if self._document_layer:
            self._document_layer.schedule()

    def event(self, event):  # type: ignore[override]
        etype = event.type()
        if etype == QEvent.Type.NativeGesture:
            if self._handle_native_zoom_gesture(event):
                return True
        if etype == QEvent.Type.Gesture:
            if self._handle_pinch_gesture(event):
                return True
        return super().event(event)

    def _handle_native_zoom_gesture(self, event: object) -> bool:
        try:
            gesture_type = event.gestureType()  # type: ignore[attr-defined]
        except Exception:
            return False
        zoom_type = getattr(Qt.NativeGestureType, "ZoomNativeGesture", None)
        if zoom_type is None or gesture_type != zoom_type:
            return False
        try:
            gesture_value = float(event.value())  # type: ignore[attr-defined]
        except Exception:
            return False
        if abs(gesture_value) <= 1e-6:
            return True
        next_zoom = float(self.view_zoom) * math.exp(gesture_value * 0.42)
        self.set_zoom_percent(int(round(next_zoom * 100.0)))
        if hasattr(event, "accept"):
            try:
                event.accept()  # type: ignore[attr-defined]
            except Exception:
                pass
        return True

    def _handle_pinch_gesture(self, event: object) -> bool:
        pinch_gesture_type = getattr(Qt.GestureType, "PinchGesture", None)
        if pinch_gesture_type is None or not hasattr(event, "gesture"):
            return False
        pinch = event.gesture(pinch_gesture_type)  # type: ignore[attr-defined]
        if pinch is None:
            return False
        state = getattr(pinch, "state", lambda: Qt.GestureState.NoGesture)()
        if state == Qt.GestureState.GestureStarted:
            self._pinch_last_total_scale = 1.0
            if hasattr(event, "accept"):
                try:
                    event.accept()  # type: ignore[attr-defined]
                except Exception:
                    pass
            return True
        if state in {Qt.GestureState.GestureFinished, Qt.GestureState.GestureCanceled}:
            self._pinch_last_total_scale = 1.0
            return True
        try:
            total_scale = float(getattr(pinch, "totalScaleFactor")())
        except Exception:
            try:
                total_scale = float(getattr(pinch, "scaleFactor")())
            except Exception:
                return False
        total_scale = max(1e-6, total_scale)
        last_scale = max(1e-6, float(self._pinch_last_total_scale or 1.0))
        delta = total_scale / last_scale
        self._pinch_last_total_scale = total_scale
        if abs(delta - 1.0) <= 1e-4:
            return True
        next_zoom = float(self.view_zoom) * float(delta)
        self.set_zoom_percent(int(round(next_zoom * 100.0)))
        if hasattr(event, "accept"):
            try:
                event.accept()  # type: ignore[attr-defined]
            except Exception:
                pass
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not self.is_drawing:
            self._space_pan = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pan = False
            if self._pan_origin is None:
                self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._space_pan = False
        self._pan_origin = None
        self.unsetCursor()
        super().focusOutEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton or (self._space_pan and event.button() == Qt.MouseButton.LeftButton):
            self._pan_origin = QPointF(event.position())
            self._pan_offset_origin = QPointF(self._view_offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        point = self._view_to_image_point(event.position())
        if event.button() != Qt.MouseButton.LeftButton:
            return

        overlay_name, mode = self._overlay_hit_test(point)
        if overlay_name and mode:
            overlay = self.ruler if overlay_name == "ruler" else self.protractor
            self.active_overlay = overlay_name
            self.overlay_interaction_mode = mode
            self.dragging_overlay = True
            self._overlay_drag_start = QPointF(event.position())
            self._overlay_origin_center = QPointF(overlay.center)
            self._overlay_origin_angle = float(overlay.angle)
            self.update()
            return

        if not self._is_in_bounds(point):
            return
        self.is_drawing = True
        self.start_point = QPointF(point)
        self.last_point = QPointF(point)
        self.preview_point = QPointF(point)
        self._stroke_committed = False

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._pan_origin is not None:
            self._view_offset = self._pan_offset_origin + event.position() - self._pan_origin
            self._clamp_view_offset()
            self.update()
            event.accept()
            return
        point = self._clamp_to_bounds(self._view_to_image_point(event.position()))
        if self.dragging_overlay and self.active_overlay:
            overlay = self._current_overlay()
            if overlay is None:
                return
            if self.overlay_interaction_mode == "move":
                delta = self._sub(event.position(), self._overlay_drag_start)
                overlay.center = self._add(self._overlay_origin_center, delta)
            elif self.overlay_interaction_mode == "rotate":
                dx = float(event.position().x()) - float(overlay.center.x())
                dy = float(event.position().y()) - float(overlay.center.y())
                if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                    overlay.angle = (math.degrees(math.atan2(dy, dx)) + (90 if self.active_overlay == "protractor" else 0)) % 360.0
            self.update()
            return

        if not self.is_drawing or not self._is_in_bounds(point):
            return

        if self.tool in {"pen", "eraser"} and self.last_point is not None:
            if not self._stroke_committed:
                self._push_undo_state()
                self._stroke_committed = True
            painter = QPainter(self.image)
            if self.tool == "eraser":
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                pen = QPen(QColor("white"), self.eraser_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                draw_start = QPointF(self.last_point)
                draw_end = QPointF(point)
            else:
                pen = QPen(self.pen_color, self.pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                draw_start, draw_end, snapped = self._snap_pen_segment_to_ruler(QPointF(self.last_point), QPointF(point))
                if snapped:
                    self.preview_point = QPointF(draw_end)
                else:
                    self.preview_point = QPointF(point)
            painter.setPen(pen)
            painter.drawLine(draw_start, draw_end)
            painter.end()
            self.last_point = QPointF(draw_end if self.tool == "pen" else point)
            if self.tool == "eraser":
                self.preview_point = QPointF(point)
        else:
            self.preview_point = QPointF(point)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._pan_origin is not None:
            self._pan_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space_pan else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.dragging_overlay:
            overlay = self._current_overlay()
            if overlay:
                overlay.angle = snapped_angle(overlay.angle, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            self.dragging_overlay = False
            self.active_overlay = None
            self.overlay_interaction_mode = None
            self.update()
            return

        if not self.is_drawing or not self.start_point:
            return

        end = self._clamp_to_bounds(self._view_to_image_point(event.position()))
        if self.tool in {"line", "rect", "ellipse", "triangle", "arrow"}:
            delta = self._distance(self.start_point, end)
            if delta > 0.2:
                if not self._stroke_committed:
                    self._push_undo_state()
                    self._stroke_committed = True
                painter = QPainter(self.image)
                self._draw_shape(painter, self.start_point, end, self.tool, is_preview=False)
                painter.end()

        self.is_drawing = False
        self.start_point = None
        self.last_point = None
        self.preview_point = None
        self._stroke_committed = False
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        modifiers = event.modifiers()
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            delta = event.angleDelta().y() / 120.0
            if abs(delta) <= 1e-6:
                super().wheelEvent(event)
                return
            self.adjust_zoom_steps(delta)
            event.accept()
            return

        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        pan_dx = float(pixel_delta.x()) if hasattr(pixel_delta, "x") else 0.0
        pan_dy = float(pixel_delta.y()) if hasattr(pixel_delta, "y") else 0.0
        if abs(pan_dx) <= 1e-6 and abs(pan_dy) <= 1e-6:
            pan_dx = float(angle_delta.x()) / 3.0
            pan_dy = float(angle_delta.y()) / 3.0
        if self.view_zoom > 1.0 and (abs(pan_dx) > 1e-6 or abs(pan_dy) > 1e-6):
            self._pan_view_by(pan_dx, pan_dy)
            event.accept()
            return

        delta = float(angle_delta.y()) / 120.0
        if abs(delta) <= 1e-6:
            super().wheelEvent(event)
            return

        point = self._clamp_to_bounds(self._view_to_image_point(event.position()))
        overlay_name, mode = self._overlay_hit_test(point)
        if overlay_name and mode:
            overlay = self.ruler if overlay_name == "ruler" else self.protractor
            overlay.angle = (float(overlay.angle) + (delta * 5.0)) % 360.0
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(Colors.BG_DARK))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.save()
        self._apply_view_transform(painter)
        rect = QRectF(0,0,self.canvas_size.width(),self.canvas_size.height())
        painter.fillRect(rect,QColor('white'))
        background = self._document_layer.image if self._document_layer else self._background_image
        if not background.isNull():
            painter.drawImage(rect,background)
        painter.drawImage(rect,self.image)
        if self.is_drawing and self.start_point and self.preview_point and self.tool in {'line','rect','ellipse','triangle','arrow'}:
            self._draw_shape(painter,self.start_point,self.preview_point,self.tool,is_preview=True)
        painter.restore()
        # Instruments are painted and hit-tested in screen space, not ink space.
        if self.ruler.visible:
            self._draw_ruler_overlay(painter)
        if self.protractor.visible:
            self._draw_protractor_overlay(painter)

    def _draw_shape(self, painter: QPainter, start: QPointF, end: QPointF, shape: str, is_preview: bool):
        pen = QPen(self.pen_color, self.pen_width)
        if is_preview:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if shape == "line":
            start_line, end_line = self._snap_line_to_ruler(start, end)
            painter.drawLine(start_line, end_line)
            return
        if shape == "rect":
            painter.drawRect(QRectF(start, end).normalized())
            return
        if shape == "ellipse":
            painter.drawEllipse(QRectF(start, end).normalized())
            return
        if shape == "triangle":
            rect = QRectF(start, end).normalized()
            top = QPointF(rect.center().x(), rect.top())
            left = QPointF(rect.left(), rect.bottom())
            right = QPointF(rect.right(), rect.bottom())
            painter.drawPolygon(QPolygonF([QPointF(top), QPointF(left), QPointF(right)]))
            return
        if shape == "arrow":
            painter.drawLine(start, end)
            dx = float(end.x()) - float(start.x())
            dy = float(end.y()) - float(start.y())
            angle = math.atan2(dy, dx)
            arrow_len = max(12.0, float(self.pen_width) * 3.5)
            left = QPointF(
                end.x() - arrow_len * math.cos(angle - math.pi / 6),
                end.y() - arrow_len * math.sin(angle - math.pi / 6),
            )
            right = QPointF(
                end.x() - arrow_len * math.cos(angle + math.pi / 6),
                end.y() - arrow_len * math.sin(angle + math.pi / 6),
            )
            painter.drawLine(end, left)
            painter.drawLine(end, right)

    def _draw_ruler_overlay(self, painter: QPainter):
        painter.save()
        painter.translate(self.ruler.center)
        painter.rotate(self.ruler.angle)
        thickness = float(getattr(self.ruler, "thickness", 30.0))
        half_thickness = int(round(thickness / 2.0))
        ruler_rect = QRect(
            int(-self.ruler.length / 2),
            -half_thickness,
            int(self.ruler.length),
            int(thickness),
        )
        painter.setPen(QPen(QColor("#f59e0b"), 2))
        painter.setBrush(QBrush(QColor(245, 158, 11, 70)))
        painter.drawRoundedRect(ruler_rect, 4, 4)

        calibrated = self._pixels_per_mm is not None
        unit_pixels = (self._pixels_per_mm * self.view_zoom) if calibrated else self.view_zoom
        unit_step = ruler_tick_step(unit_pixels)
        usable_len = float(self.ruler.length) - 12.0
        tick_count = int(usable_len / (unit_pixels * unit_step))
        start_x = float(ruler_rect.left()) + 6.0
        y_top = -half_thickness
        painter.setPen(QPen(QColor('#78350f'),1))
        font = painter.font(); font.setPixelSize(11); painter.setFont(font)
        label_step = max(10,unit_step*10)
        for index in range(tick_count+1):
            unit = index * unit_step
            x = start_x + unit * unit_pixels
            tick = thickness * (.48 if unit%10==0 else (.34 if unit%5==0 else .22))
            painter.drawLine(QPointF(x,y_top),QPointF(x,y_top+tick))
            if unit % label_step == 0:
                label = str(unit//10) if calibrated else str(unit)
                painter.drawText(QRectF(x-12,half_thickness-14,24,12),Qt.AlignmentFlag.AlignCenter,label)
        painter.drawText(QRectF(ruler_rect.right()-24,half_thickness-14,24,12),'cm' if calibrated else 'px')

        handle_center = QPointF((float(self.ruler.length) / 2.0) + 24.0, 0.0)
        painter.setPen(QPen(QColor("#f59e0b"), 2))
        painter.setBrush(QBrush(QColor(245, 158, 11, 180)))
        painter.drawEllipse(handle_center, 8.0, 8.0)
        painter.restore()

    def _protractor_tick_degrees(self) -> List[int]:
        if self.protractor.mode == self.PROTRACTOR_MODE_ROUND:
            return list(range(0, 360, 1))
        return list(range(0, 181, 1))

    def _protractor_label_degrees(self) -> List[int]:
        if self.protractor.mode == self.PROTRACTOR_MODE_ROUND:
            labels = list(range(0, 361, 30))
            if labels[-1] != 360:
                labels.append(360)
            return labels
        return list(range(0, 181, 20))

    def _draw_upright_protractor_label(
        self,
        painter: QPainter,
        label: str,
        center: QPointF,
        bold: bool,
    ) -> None:
        painter.save()
        painter.translate(center)
        painter.rotate(-float(self.protractor.angle))
        painter.setFont(QFont("Arial", 8, QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
        painter.drawText(
            QRectF(-14.0, -9.0, 28.0, 18.0),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
        painter.restore()

    def _draw_protractor_overlay(self, painter: QPainter):
        painter.save()
        painter.translate(self.protractor.center)
        painter.rotate(self.protractor.angle)
        radius = float(self.protractor.radius)
        r = int(round(radius))
        is_round = self.protractor.mode == self.PROTRACTOR_MODE_ROUND

        painter.setPen(QPen(QColor("#22c55e"), 2))
        painter.setBrush(QBrush(QColor(34, 197, 94, 55)))
        if is_round:
            painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)
        else:
            path = QPainterPath()
            path.arcMoveTo(-r, -r, 2 * r, 2 * r, 180)
            path.arcTo(-r, -r, 2 * r, 2 * r, 180, -180)
            path.lineTo(r, 0)
            path.lineTo(-r, 0)
            painter.drawPath(path)

        for deg in self._protractor_tick_degrees():
            rad = math.radians(float(deg))
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            x = radius * cos_a
            y = -radius * sin_a
            if deg % 10 == 0:
                tick = 14.0
            elif deg % 5 == 0:
                tick = 9.0
            else:
                tick = 5.0
            x2 = (radius - tick) * cos_a
            y2 = -(radius - tick) * sin_a
            painter.drawLine(QPointF(x, y), QPointF(x2, y2))

        painter.setPen(QPen(QColor("#14532d"), 1))
        for deg in self._protractor_label_degrees():
            rad = math.radians(float(deg % 360))
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            if is_round:
                label_r = radius - (28.0 if deg % 90 == 0 else 22.0)
                if deg == 360:
                    label_r -= 14.0
            else:
                label_r = radius - (24.0 if deg % 30 == 0 else 19.0)
            lx = label_r * cos_a
            ly = -label_r * sin_a
            self._draw_upright_protractor_label(
                painter,
                str(deg),
                QPointF(lx, ly),
                bold=(deg % 30 == 0),
            )

        painter.setBrush(QBrush(QColor(34, 197, 94, 190)))
        painter.setPen(QPen(QColor("#22c55e"), 2))
        painter.drawEllipse(QPointF(0.0, 0.0), 7.0, 7.0)
        rotate_handle = QPointF(0.0, float(-(radius + 18.0)))
        painter.drawEllipse(rotate_handle, 7.0, 7.0)
        painter.restore()


class DrawingEditorDialog(QDialog):
    """Popup drawing editor for diagram/graph responses."""

    def __init__(
        self,
        output_path: str,
        existing_path: Optional[str] = None,
        reference_path: Optional[str | Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.output_path = output_path
        self.setWindowTitle("Drawing Editor")
        self.resize(1060, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar_shell = QWidget(self)
        toolbar = QHBoxLayout(toolbar_shell)
        toolbar.setContentsMargins(20, 10, 20, 10)
        toolbar.setSpacing(15)
        toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        tools_group = QHBoxLayout()
        tools_group.setContentsMargins(0, 0, 0, 0)
        tools_group.setSpacing(15)
        tools_group.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.tool_combo = QComboBox()
        self.tool_combo.setObjectName("drawingToolCombo")
        self.tool_combo.addItems(["pen", "eraser", "line", "rect", "ellipse", "triangle", "arrow"])
        self.tool_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.tool_combo.setMinimumContentsLength(8)
        self.tool_combo.setMinimumWidth(170)
        tools_group.addWidget(self.tool_combo, 0, Qt.AlignmentFlag.AlignCenter)

        stroke_label = QLabel("Stroke")
        stroke_label.setObjectName("drawingToolbarLabel")
        tools_group.addWidget(stroke_label, 0, Qt.AlignmentFlag.AlignCenter)
        self.width_spin = QSpinBox()
        self.width_spin.setObjectName("drawingStrokeSpin")
        self.width_spin.setRange(1, 40)
        self.width_spin.setValue(3)
        self.width_spin.setMinimumWidth(84)
        tools_group.addWidget(self.width_spin, 0, Qt.AlignmentFlag.AlignCenter)

        color_group = QHBoxLayout()
        color_group.setContentsMargins(0, 0, 0, 0)
        color_group.setSpacing(8)
        color_group.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        color_label = QLabel("Colors")
        color_label.setObjectName("drawingToolbarLabel")
        color_group.addWidget(color_label, 0, Qt.AlignmentFlag.AlignCenter)
        self._color_buttons: List[QPushButton] = []
        color_palette = [
            "#0f172a", "#dc2626", "#2563eb", "#16a34a", "#ca8a04", "#9333ea", "#db2777", "#0e7490"
        ]
        for hex_color in color_palette:
            btn = QPushButton("")
            btn.setFixedSize(30, 30)
            btn.setStyleSheet(
                "QPushButton {"
                f"background-color: {hex_color};"
                "border: 1px solid rgba(226, 232, 240, 0.82);"
                "border-radius: 8px;"
                "}"
                "QPushButton:hover {"
                "border: 2px solid #F8FAFC;"
                "}"
                "QPushButton:pressed {"
                "border: 2px solid #38BDF8;"
                "}"
            )
            btn.clicked.connect(lambda _, c=hex_color: self.canvas.set_pen_color(QColor(c)))
            self._color_buttons.append(btn)
            color_group.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)

        toolbar.addLayout(tools_group, 0)
        toolbar.addStretch(1)
        toolbar.addLayout(color_group, 0)
        layout.addWidget(toolbar_shell, 0)

        self.canvas = DrawingCanvasWidget()
        self.finished.connect(lambda _: self.canvas.close_document_layer())
        if existing_path and os.path.exists(existing_path):
            self.canvas.load_image(existing_path)
        elif reference_path:
            self.canvas.load_reference(reference_path)
        layout.addWidget(self.canvas, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(20, 0, 20, 12)
        footer.setSpacing(12)
        footer.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        footer_controls = QHBoxLayout()
        footer_controls.setContentsMargins(0, 0, 0, 0)
        footer_controls.setSpacing(10)
        footer_controls.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.toggle_ruler_btn = QPushButton("Ruler")
        self.toggle_ruler_btn.setObjectName("drawingOverlayControl")
        self.toggle_ruler_btn.setCheckable(True)
        footer_controls.addWidget(self.toggle_ruler_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self.toggle_protractor_btn = QPushButton("Protractor")
        self.toggle_protractor_btn.setObjectName("drawingOverlayControl")
        self.toggle_protractor_btn.setCheckable(True)
        footer_controls.addWidget(self.toggle_protractor_btn, 0, Qt.AlignmentFlag.AlignCenter)

        zoom_label = QLabel("Zoom")
        zoom_label.setObjectName("drawingToolbarLabel")
        footer_controls.addWidget(zoom_label, 0, Qt.AlignmentFlag.AlignCenter)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setObjectName("drawingZoomSpin")
        self.zoom_spin.setRange(25, 400)
        self.zoom_spin.setSingleStep(5)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setValue(100)
        self.zoom_spin.setMinimumWidth(94)
        footer_controls.addWidget(self.zoom_spin, 0, Qt.AlignmentFlag.AlignCenter)
        self.zoom_reset_btn = QPushButton("100%")
        self.zoom_reset_btn.setObjectName("drawingZoomReset")
        footer_controls.addWidget(self.zoom_reset_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self.custom_color_btn = QPushButton("Custom...")
        self.custom_color_btn.setObjectName("drawingCustomColor")
        footer_controls.addWidget(self.custom_color_btn, 0, Qt.AlignmentFlag.AlignCenter)

        footer.addLayout(footer_controls, 0)
        footer.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        self.clear_btn = QPushButton("Clear")
        self.save_btn = QPushButton("Save")
        self.cancel_btn = QPushButton("Cancel")
        actions.addWidget(self.undo_btn)
        actions.addWidget(self.redo_btn)
        actions.addWidget(self.clear_btn)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.cancel_btn)
        footer.addLayout(actions, 0)
        layout.addLayout(footer, 0)

        button_height = max(34, self.undo_btn.sizeHint().height())
        self.custom_color_btn.setFixedHeight(button_height)
        self.toggle_ruler_btn.setFixedHeight(button_height)
        self.toggle_protractor_btn.setFixedHeight(button_height)
        self.zoom_reset_btn.setFixedHeight(button_height)

        self.setStyleSheet(
            "QLabel#drawingToolbarLabel {"
            f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)};"
            "font-weight: 600;"
            "}"
            "QComboBox#drawingToolCombo, "
            "QSpinBox#drawingStrokeSpin, "
            "QSpinBox#drawingZoomSpin {"
            "background-color: #0F172A;"
            "color: #F8FAFC;"
            "border: 1px solid #334155;"
            "border-radius: 8px;"
            "padding: 5px 9px;"
            "min-height: 32px;"
            "selection-background-color: #0EA5E9;"
            "selection-color: #F8FAFC;"
            "}"
            "QComboBox#drawingToolCombo::drop-down { width: 26px; border: none; }"
            "QComboBox#drawingToolCombo QAbstractItemView {"
            "background-color: #0F172A;"
            "color: #F8FAFC;"
            "border: 1px solid #334155;"
            "selection-background-color: #1D4ED8;"
            "selection-color: #F8FAFC;"
            "min-width: 220px;"
            "padding: 4px;"
            "}"
            "QPushButton#drawingOverlayControl, QPushButton#drawingZoomReset, QPushButton#drawingCustomColor {"
            "background-color: #0284C7;"
            "color: #F8FAFC;"
            "border: 1px solid #38BDF8;"
            "border-radius: 10px;"
            "padding: 6px 12px;"
            "font-weight: 700;"
            "}"
            "QPushButton#drawingOverlayControl:checked {"
            "background-color: #0EA5E9;"
            "color: #082F49;"
            "border: 1px solid #7DD3FC;"
            "}"
            "QPushButton#drawingOverlayControl:hover, QPushButton#drawingZoomReset:hover, QPushButton#drawingCustomColor:hover {"
            "background-color: #0EA5E9;"
            "}"
        )

        self.tool_combo.currentTextChanged.connect(self.canvas.set_tool)
        self.width_spin.valueChanged.connect(self.canvas.set_pen_width)
        self.undo_btn.clicked.connect(self.canvas.undo)
        self.redo_btn.clicked.connect(self.canvas.redo)
        self.clear_btn.clicked.connect(self.canvas.clear_canvas)
        self.custom_color_btn.clicked.connect(self._choose_custom_color)
        self.toggle_ruler_btn.toggled.connect(lambda v: self.canvas.set_guide_visible("ruler", v))
        self.toggle_protractor_btn.toggled.connect(self._on_protractor_toggled)
        self.zoom_spin.valueChanged.connect(self.canvas.set_zoom_percent)
        self.zoom_reset_btn.clicked.connect(lambda: self.zoom_spin.setValue(100))
        self.canvas.zoom_changed.connect(self._sync_zoom_spin)
        self._sync_zoom_spin(self.canvas.zoom_percent())
        self.save_btn.clicked.connect(self._save_and_close)
        self.cancel_btn.clicked.connect(self.reject)

        self._undo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self._undo_shortcut.activated.connect(self.canvas.undo)
        self._redo_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self)
        self._redo_shortcut.activated.connect(self.canvas.redo)
        self._redo_shortcut_ctrl_y = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._redo_shortcut_ctrl_y.activated.connect(self.canvas.redo)
        self._redo_shortcut_meta_y = QShortcut(QKeySequence("Meta+Y"), self)
        self._redo_shortcut_meta_y.activated.connect(self.canvas.redo)

        from UI.drawing_workspace import DrawingEditorPresentation
        self._presentation = DrawingEditorPresentation(self)

    def _sync_zoom_spin(self, percent: int) -> None:
        blocked = self.zoom_spin.blockSignals(True)
        self.zoom_spin.setValue(int(max(25, min(400, int(percent)))))
        self.zoom_spin.blockSignals(blocked)

    def _choose_custom_color(self):
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self.canvas.set_pen_color(color)

    def _on_protractor_toggled(self, enabled: bool) -> None:
        if not bool(enabled):
            self.canvas.set_guide_visible("protractor", False)
            return

        current_mode = getattr(self.canvas.protractor, "mode", DrawingCanvasWidget.PROTRACTOR_MODE_SEMI)
        options = [
            ("Protractor (0-180)", DrawingCanvasWidget.PROTRACTOR_MODE_SEMI),
            ("Round Protractor (0-360)", DrawingCanvasWidget.PROTRACTOR_MODE_ROUND),
        ]
        labels = [item[0] for item in options]
        default_index = 0 if current_mode == DrawingCanvasWidget.PROTRACTOR_MODE_SEMI else 1
        label, ok = QInputDialog.getItem(
            self,
            "Protractor Type",
            "Display",
            labels,
            default_index,
            False,
        )
        if not ok:
            blocked = self.toggle_protractor_btn.blockSignals(True)
            self.toggle_protractor_btn.setChecked(False)
            self.toggle_protractor_btn.blockSignals(blocked)
            self.canvas.set_guide_visible("protractor", False)
            return

        selected_mode = options[labels.index(str(label))][1]
        self.canvas.set_protractor_mode(selected_mode)
        self.canvas.set_guide_visible("protractor", True)

    def _save_and_close(self):
        ok = self.canvas.save_image(self.output_path)
        if ok:
            self.accept()
        else:
            show_error(self, "Save Error", "Failed to save drawing image.")


class CalculatorDialog(QDialog):
    """Dedicated non-modal window for the scientific calculator."""

    visibility_changed = Signal(bool)

    def __init__(self, calculator_widget: ScientificCalculatorWidget, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calculator")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(980, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(calculator_widget, 1)

    def closeEvent(self, event):
        # Keep the dialog instance alive so button state and memory persist.
        self.hide()
        event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)


class NotesWidget(QWidget):
    """Floating exam-session scratchpad with runtime theming."""

    notes_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.editor = SuperscriptTextEdit(self)
        self.editor.setPlaceholderText("Type notes here...")
        self.editor.install_rich_text_context_menu()
        self.editor.textChanged.connect(self._emit_notes_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(self.editor, 1)
        self.apply_runtime_theme()

    def _emit_notes_changed(self) -> None:
        self.notes_changed.emit(_editor_to_caret_text(self.editor))

    def set_notes_text(self, text: str) -> None:
        _editor_set_caret_text(self.editor, str(text or ""))

    def notes_text(self) -> str:
        return _editor_to_caret_text(self.editor)

    def apply_runtime_theme(self) -> None:
        accent = str(getattr(Colors, "ACCENT_CYAN", "") or Colors.SECONDARY)
        bg_card = str(Colors.BG_CARD)
        border = _mix_hex(accent, Colors.BG_DARK, 0.38)
        viewport_bg = _mix_hex(bg_card, Colors.BG_DARK, 0.08)
        text_color = _contrast_text_for_bg(viewport_bg)
        self.setStyleSheet(
            "QWidget {"
            f"background-color: {bg_card};"
            f"border: 1px solid {border};"
            "border-radius: 2px;"
            "}"
            "QTextEdit {"
            f"background-color: {viewport_bg};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 2px;"
            "padding: 8px;"
            f"selection-background-color: {_mix_hex(accent, Colors.BG_DARK, 0.18)};"
            f"selection-color: {_contrast_text_for_bg(_mix_hex(accent, Colors.BG_DARK, 0.18))};"
            f"caret-color: {accent};"
            "font-size: 13px;"
            "}"
            "QTextEdit:focus {"
            f"border: 1px solid {accent};"
            "}"
            "QScrollBar:vertical {"
            f"background: {_mix_hex(bg_card, Colors.BG_DARK, 0.12)};"
            "width: 10px;"
            "margin: 0px;"
            "border-radius: 5px;"
            "}"
            "QScrollBar::handle:vertical {"
            f"background: {accent};"
            "border-radius: 5px;"
            "min-height: 24px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "height: 0px;"
            "}"
        )


class NotesDialog(QDialog):
    """Persistent floating dialog used for the exam scratchpad."""

    visibility_changed = Signal(bool)

    def __init__(self, notes_widget: NotesWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Scratchpad / Notes")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(420, 340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(notes_widget, 1)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)


class TableAnswerWidget(QWidget):
    """Render extracted table structure with editable blank cells."""

    LIGHT_CELL_BORDER = "#4B5563"

    def __init__(
        self,
        table_spec: Dict[str, Any],
        on_change: Optional[Callable[[], None]] = None,
        context_menu_installer: Optional[Callable[[QTextEdit], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.table_spec = dict(table_spec or {})
        self.on_change = on_change
        self.context_menu_installer = context_menu_installer
        self.inputs: Dict[Tuple[int, int], QWidget] = {}
        self.text_inputs: Dict[Tuple[int, int], SuperscriptTextEdit] = {}
        self.tick_inputs: Dict[Tuple[int, int], QCheckBox] = {}
        self._cell_widgets: Dict[Tuple[int, int], QWidget] = {}
        self._tick_touched: set[Tuple[int, int]] = set()
        self._current_state_color: Optional[str] = None

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        rows = int(self.table_spec.get("rows", 0) or 0)
        cols = int(self.table_spec.get("cols", 0) or 0)
        cells = list(self.table_spec.get("cells", []) or [])
        cell_map: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for cell in cells:
            try:
                r = int(cell.get("row", -1))
                c = int(cell.get("col", -1))
            except Exception:
                continue
            if r < 0 or c < 0:
                continue
            cell_map[(r, c)] = dict(cell)

        for r in range(rows):
            for c in range(cols):
                cell = dict(cell_map.get((r, c), {}))
                missing = bool(cell.get("missing", False))
                text = str(cell.get("text", "") or "").strip()
                is_answer = bool(cell.get("is_answer", False))
                input_kind = str(cell.get("input_kind", "text") or "text").strip().lower()
                if missing:
                    placeholder = QLabel("")
                    placeholder.setMinimumHeight(34)
                    placeholder.setStyleSheet(
                        f"border: 1px dashed {self.LIGHT_CELL_BORDER}; background-color: {Colors.BG_MEDIUM};"
                    )
                    self._cell_widgets[(r, c)] = placeholder
                    grid.addWidget(placeholder, r, c, 1, 1)
                    continue

                if is_answer and input_kind == "tick":
                    checkbox = QCheckBox()
                    checkbox.setTristate(False)
                    checkbox.setChecked(False)
                    checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
                    checkbox.setMinimumHeight(36)
                    checkbox.setMaximumHeight(44)
                    checkbox.setStyleSheet(self._checkbox_style())
                    checkbox.stateChanged.connect(lambda _state, coords=(r, c): self._on_tick_changed(coords))
                    self.tick_inputs[(r, c)] = checkbox
                    self.inputs[(r, c)] = checkbox
                    self._cell_widgets[(r, c)] = checkbox
                    grid.addWidget(checkbox, r, c, 1, 1, Qt.AlignmentFlag.AlignCenter)
                    continue

                if is_answer:
                    editor = SuperscriptTextEdit()
                    editor.setPlaceholderText(text if text else "Answer")
                    editor.setMinimumHeight(44)
                    editor.setMaximumHeight(72)
                    editor.setStyleSheet(self._editor_style())
                    editor.textChanged.connect(self._notify_changed)
                    if self.context_menu_installer:
                        self.context_menu_installer(editor)
                    self.text_inputs[(r, c)] = editor
                    self.inputs[(r, c)] = editor
                    self._cell_widgets[(r, c)] = editor
                    grid.addWidget(editor, r, c, 1, 1)
                    continue

                label = QLabel(text)
                label.setWordWrap(True)
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                label_text = _contrast_text_for_bg(Colors.BG_MEDIUM)
                label.setStyleSheet(
                    f"border: 1px solid {self.LIGHT_CELL_BORDER}; background-color: {Colors.BG_MEDIUM}; "
                    f"padding: 6px; color: {label_text};"
                )
                self._cell_widgets[(r, c)] = label
                grid.addWidget(label, r, c, 1, 1)

    @staticmethod
    def _editor_style(bg_color: Optional[str] = None) -> str:
        bg = bg_color or _input_surface_bg()
        text_color = _contrast_text_for_bg(bg)
        return (
            f"QTextEdit {{ background-color: {bg}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: 6px; font-size: 14px; }}"
        )

    @staticmethod
    def _checkbox_style(bg_color: Optional[str] = None) -> str:
        bg = bg_color or _input_surface_bg()
        card_bg = _mix_hex(bg, Colors.BG_CARD, 0.2)
        border = _input_border_color()
        hover_border = _mix_hex(border, _input_focus_glow_color(), 0.42)
        checked_bg = _mix_hex(str(Colors.SUCCESS), card_bg, 0.24)
        checked_border = _mix_hex(str(Colors.SUCCESS), border, 0.5)
        tick_color = _contrast_text_for_bg(checked_bg)
        return (
            "QCheckBox { background: transparent; padding: 0px; margin: 0px; }"
            "QCheckBox::indicator {"
            "width: 18px; height: 18px; border-radius: 5px;"
            f"border: 1px solid {border};"
            f"background-color: {card_bg};"
            "}"
            "QCheckBox::indicator:hover {"
            f"border: 1px solid {hover_border};"
            f"background-color: {_mix_hex(card_bg, Colors.BG_LIGHT, 0.18)};"
            "}"
            "QCheckBox::indicator:checked {"
            f"border: 1px solid {checked_border};"
            f"background-color: {checked_bg};"
            f"color: {tick_color};"
            "}"
            "QCheckBox::indicator:disabled {"
            f"border: 1px solid {_mix_hex(border, Colors.BG_DARK, 0.3)};"
            f"background-color: {_mix_hex(card_bg, Colors.BG_DARK, 0.25)};"
            "}"
        )

    def _on_tick_changed(self, coords: Tuple[int, int]) -> None:
        self._tick_touched.add(tuple(coords))
        self._notify_changed()

    @staticmethod
    def _checkbox_value(checked: bool) -> str:
        return "Check" if bool(checked) else "No Check"

    @staticmethod
    def _is_checkbox_checked(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        if normalized in {"check", "checked", "tick", "yes", "true", "1", "y", "✓"}:
            return True
        if normalized in {"no check", "unchecked", "no", "false", "0", "n", ""}:
            return False
        return False

    def _notify_changed(self) -> None:
        if self.on_change:
            self.on_change()

    def apply_runtime_theme(self) -> None:
        for widget in self._cell_widgets.values():
            if isinstance(widget, QLabel):
                label_text = _contrast_text_for_bg(Colors.BG_MEDIUM)
                widget.setStyleSheet(
                    f"border: 1px solid {self.LIGHT_CELL_BORDER}; background-color: {Colors.BG_MEDIUM}; "
                    f"padding: 6px; color: {label_text};"
                )
        target_color = self._current_state_color
        for editor in self.text_inputs.values():
            editor.setStyleSheet(self._editor_style(target_color))
        for checkbox in self.tick_inputs.values():
            checkbox.setStyleSheet(self._checkbox_style(target_color))

    def set_state(self, bg_color: str) -> None:
        self._current_state_color = bg_color
        for editor in self.text_inputs.values():
            editor.setStyleSheet(self._editor_style(bg_color))
        for checkbox in self.tick_inputs.values():
            checkbox.setStyleSheet(self._checkbox_style(bg_color))

    def clear_state(self) -> None:
        self._current_state_color = None
        for editor in self.text_inputs.values():
            editor.setStyleSheet(self._editor_style())
        for checkbox in self.tick_inputs.values():
            checkbox.setStyleSheet(self._checkbox_style())

    def set_inputs_enabled(self, enabled: bool) -> None:
        editable = bool(enabled)
        for editor in self.text_inputs.values():
            editor.setReadOnly(not editable)
            editor.setEnabled(True)
        for checkbox in self.tick_inputs.values():
            checkbox.setEnabled(editable)

    def has_answer(self) -> bool:
        if any(bool(_editor_to_caret_text(editor).strip()) for editor in self.text_inputs.values()):
            return True
        if any(checkbox.isChecked() for checkbox in self.tick_inputs.values()):
            return True
        if bool(self._tick_touched):
            return True
        return False

    def get_cell_answers(self) -> Dict[str, str]:
        payload: Dict[str, str] = {}
        for (r, c), widget in sorted(self.inputs.items()):
            if isinstance(widget, QTextEdit):
                payload[f"{r},{c}"] = _editor_to_caret_text(widget)
            elif isinstance(widget, QCheckBox):
                payload[f"{r},{c}"] = self._checkbox_value(widget.isChecked())
        return payload

    def set_cell_answers(self, cells: Dict[str, Any]) -> None:
        if not isinstance(cells, dict):
            return
        for key, value in cells.items():
            try:
                row_str, col_str = str(key).split(",", 1)
                coords = (int(row_str), int(col_str))
            except Exception:
                continue
            if coords in self.text_inputs:
                _editor_set_caret_text(self.text_inputs[coords], str(value or ""))
                continue
            checkbox = self.tick_inputs.get(coords)
            if not checkbox:
                continue
            checkbox.setChecked(self._is_checkbox_checked(value))
            self._tick_touched.add(coords)

    def to_serialized_answer(self) -> str:
        rows = int(self.table_spec.get("rows", 0) or 0)
        cols = int(self.table_spec.get("cols", 0) or 0)
        cells = {tuple(map(int, key.split(","))): value for key, value in self.get_cell_answers().items()}
        lines: List[str] = []
        for r in range(rows):
            row_parts: List[str] = []
            for c in range(cols):
                value = str(cells.get((r, c), "") or "").strip()
                if value:
                    row_parts.append(f"R{r+1}C{c+1}={value}")
            if row_parts:
                lines.append("; ".join(row_parts))
        if not lines:
            return ""
        return "Table response:\n" + "\n".join(lines).strip()


class MathQuestionnaire(QWidget):
    """Written/AI questionnaire with hierarchy, mapping confidence, and page jump support."""

    def __init__(
        self,
        question_ids: Optional[List[str]] = None,
        question_items: Optional[List[QuestionLeaf]] = None,
        on_answer_change=None,
        on_jump_to_page=None,
        drawing_session_dir: Optional[str] = None,
        drawing_file_prefix: str = "",
        parent=None,
        lazy_workspace: bool = False,
    ):
        super().__init__(parent)
        self.on_answer_change = on_answer_change
        self.on_jump_to_page = on_jump_to_page
        self.drawing_session_dir = drawing_session_dir or tempfile.mkdtemp(prefix="exam_drawings_")
        self.drawing_file_prefix = drawing_file_prefix or "drawing"
        self.answers: Dict[str, ResizableAnswerTextEdit] = {}
        self.answer_split_widgets: Dict[str, QWidget] = {}
        self.correct_answer_labels: Dict[str, QLabel] = {}
        self.table_inputs: Dict[str, TableAnswerWidget] = {}
        self.marks_labels: Dict[str, QLabel] = {}
        self.status_labels: Dict[str, QLabel] = {}
        self.context_labels: Dict[str, QLabel] = {}
        self.question_widgets: Dict[str, QWidget] = {}
        self.answer_types: Dict[str, str] = {}
        self.section_types: Dict[str, str] = {}
        self.objective_inputs: Dict[str, QComboBox] = {}
        self.drawing_paths: Dict[str, str] = {}
        self.drawing_notes: Dict[str, str] = {}
        self.drawing_note_inputs: Dict[str, SuperscriptTextEdit] = {}
        self.drawing_status_labels: Dict[str, QLabel] = {}
        self._drawing_action_buttons: List[QPushButton] = []
        self._drawing_status_colors: Dict[str, str] = {}
        self.drawing_reference_images: Dict[str, Any] = {}
        self._last_grading_results: Dict[str, Dict] = {}
        self._last_mapping_report: Optional[MappingReport] = None
        self._container_widget: Optional[QWidget] = None
        self.hidden_questions: set[str] = set()

        if question_items:
            self.question_items = question_items
        else:
            self.question_items = []
            for q_id in question_ids or []:
                parts = parse_question_id(q_id)
                level = 0
                parent_id = None
                if parts.part:
                    level = 1
                    parent_id = str(parts.main) if parts.main is not None else None
                if parts.part and parts.subpart:
                    level = 2
                    parent_id = f"{parts.main}{parts.part}" if parts.main is not None else None
                response_type, _, reason = detect_response_type("")
                self.question_items.append(
                    QuestionLeaf(
                        canonical_id=normalize_question_id(q_id),
                        display_id=format_question_display(q_id),
                        main=parts.main,
                        part=parts.part,
                        subpart=parts.subpart,
                        page=None,
                        text="",
                        parent_id=parent_id,
                        level=level,
                        response_type=response_type,
                        requires_manual_review=response_type == "drawing",
                        manual_review_reason=reason if response_type == "drawing" else "",
                        section_type=detect_section_type("", mode="WRITTEN_ONLY"),
                    )
                )

        self.question_ids = [normalize_question_id(item.canonical_id) for item in self.question_items]
        os.makedirs(self.drawing_session_dir, exist_ok=True)

        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")
        container = QWidget()
        self._container_widget = container
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(6, 6, 6, 6)
        container_layout.setSpacing(6)
        container.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")

        self._lazy_workspace = bool(lazy_workspace)
        self._pending_answers: Dict[str, Any] = {}
        self._question_container_layout = container_layout
        for item in self.question_items:
            qid = normalize_question_id(item.canonical_id)
            self.answer_types[qid] = item.response_type if item.response_type in {"text", "drawing", "table"} else "text"
            if isinstance(getattr(item, "table_spec", None), dict) and item.table_spec.get("cells") and self.answer_types[qid] != "drawing":
                self.answer_types[qid] = "table"
            self.section_types[qid] = getattr(item, "section_type", "written")
            if not self._lazy_workspace:
                self._create_question_widget(item)

        container_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll)

    def ensure_question_widget(self, q_id: str) -> Optional[QWidget]:
        qid = normalize_question_id(q_id)
        if qid not in self.question_widgets:
            item = next((item for item in self.question_items if normalize_question_id(item.canonical_id) == qid), None)
            if item is None:
                return None
            self._create_question_widget(item)
            if qid in self._pending_answers:
                self.apply_saved_answers({qid: self._pending_answers.pop(qid)})
            self.apply_runtime_theme()
        return self.question_widgets.get(qid)

    def _create_question_widget(self, item: QuestionLeaf) -> None:
        q_id = normalize_question_id(item.canonical_id)
        response_type = item.response_type if item.response_type in {"text", "drawing", "table"} else "text"
        section_type = getattr(item, "section_type", detect_section_type(item.text, mode="MIXED"))
        table_spec_raw = getattr(item, "table_spec", None)
        has_table_spec = isinstance(table_spec_raw, dict) and bool(table_spec_raw.get("cells"))
        if has_table_spec and response_type != "drawing":
            response_type = "table"
        self.answer_types[q_id] = response_type
        self.section_types[q_id] = section_type
        row_widget = QWidget()
        row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row_widget.setStyleSheet(
            "background-color: transparent; "
            f"border: 1px solid {_mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.28)}; "
            "border-radius: 9px;"
        )
        row_widget.setMinimumWidth(0)
        row_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout(row_widget)
        left_margin = 8 + (item.level * 14)
        row.setContentsMargins(left_margin, 8, 10, 8)
        row.setSpacing(8)

        status_dot = QLabel("●")
        status_dot.setFixedWidth(10)
        status_dot.setVisible(False)
        status_dot.setStyleSheet(f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};")
        status_dot.setToolTip("Answer-key mapping status")
        self.status_labels[q_id] = status_dot

        id_label = QLabel(f"Q{item.display_id or format_question_id_display(q_id)}")
        id_label.setMinimumWidth(78)
        id_label.setMaximumWidth(112)
        id_label.setStyleSheet(
            f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)}; "
            "font-family: \"JetBrains Mono\", \"Menlo\", \"Consolas\", monospace; "
            "font-weight: 700;"
        )
        row.addWidget(id_label)

        marks_badge = QLabel("")
        marks_badge.setMinimumWidth(98)
        marks_badge.setMaximumWidth(136)
        marks_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        marks_badge.setVisible(False)
        marks_badge.setStyleSheet(self._badge_base_style())
        self.marks_labels[q_id] = marks_badge
        row.addWidget(marks_badge)

        context_text = self._build_context_text(item)
        if section_type == "objective" and response_type != "table":
            context_text += " • Objective"
        context = QLabel(context_text)
        context.setStyleSheet(f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};")
        context.setMinimumWidth(96)
        context.setMaximumWidth(280)
        context.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.context_labels[q_id] = context
        row.addWidget(context)

        if response_type == "drawing":
            reference_path = getattr(item, "drawing_reference_path", None)
            if reference_path:
                self.drawing_reference_images[q_id] = reference_path
            drawing_box = QWidget()
            drawing_layout = QVBoxLayout(drawing_box)
            drawing_layout.setContentsMargins(0, 0, 0, 0)
            drawing_layout.setSpacing(3)

            controls = QHBoxLayout()
            open_btn = QPushButton("Open Canvas")
            upload_btn = QPushButton("Upload Drawing")
            clear_btn = QPushButton("Clear")
            open_btn.setProperty("drawingActionType", "open")
            upload_btn.setProperty("drawingActionType", "upload")
            clear_btn.setProperty("drawingActionType", "clear")
            self._drawing_action_buttons.extend([open_btn, upload_btn, clear_btn])
            open_btn.clicked.connect(lambda _, q=q_id: self._open_drawing_canvas(q))
            upload_btn.clicked.connect(lambda _, q=q_id: self._replace_or_upload_drawing(q))
            clear_btn.clicked.connect(lambda _, q=q_id: self.clear_drawing(q))
            controls.addWidget(open_btn)
            controls.addWidget(upload_btn)
            controls.addWidget(clear_btn)
            controls.addStretch(1)
            drawing_layout.addLayout(controls)

            status = QLabel("No drawing")
            status.setStyleSheet(f"color: {Colors.WARNING};")
            status.setToolTip(item.manual_review_reason or "Drawing question")
            self.drawing_status_labels[q_id] = status
            drawing_layout.addWidget(status)

            note_input = SuperscriptTextEdit()
            note_input.setPlaceholderText("Notes for examiner (optional)")
            note_input.setMinimumHeight(40)
            note_input.setMaximumHeight(72)
            note_input.setStyleSheet(self._note_input_base_style())
            self._install_text_context_menu(note_input)
            note_input.textChanged.connect(
                lambda q=q_id, w=note_input: self._set_drawing_note(q, _editor_to_caret_text(w))
            )
            self.drawing_note_inputs[q_id] = note_input
            drawing_layout.addWidget(note_input)
            row.addWidget(drawing_box, 1)
        else:
            if response_type == "table":
                if has_table_spec:
                    table_widget = TableAnswerWidget(
                        table_spec=dict(item.table_spec or {}),
                        on_change=(lambda q=q_id: self.on_answer_change(q)) if self.on_answer_change else None,
                        context_menu_installer=self._install_text_context_menu,
                    )
                    self.table_inputs[q_id] = table_widget
                    row.addWidget(table_widget, 1)
                else:
                    entry, answer_split, correct_label = self._build_text_answer_panel(q_id=q_id)
                    entry.setPlaceholderText("Table layout unavailable. Enter your table values here...")
                    self.answers[q_id] = entry
                    self.answer_split_widgets[q_id] = answer_split
                    self.correct_answer_labels[q_id] = correct_label
                    row.addWidget(answer_split, 1)
            elif section_type == "objective":
                obj_box = QWidget()
                obj_layout = QHBoxLayout(obj_box)
                obj_layout.setContentsMargins(0, 0, 0, 0)
                obj_layout.setSpacing(6)
                obj_label = QLabel("Option")
                obj_label.setStyleSheet(f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)};")
                obj_layout.addWidget(obj_label)
                combo = QComboBox()
                combo.addItems(["", "A", "B", "C", "D"])
                combo.setFixedWidth(110)
                combo.setMinimumHeight(42)
                combo.setStyleSheet(self._combo_base_style(font_size=16, padding=6))
                if self.on_answer_change:
                    combo.currentTextChanged.connect(lambda _, q=q_id: self.on_answer_change(q))
                self.objective_inputs[q_id] = combo
                obj_layout.addWidget(combo)
                obj_layout.addStretch(1)
                row.addWidget(obj_box, 1)
            else:
                entry, answer_split, correct_label = self._build_text_answer_panel(q_id=q_id)
                if response_type == "table":
                    entry.setPlaceholderText("Table was not detected. Enter your response here...")
                self.answers[q_id] = entry
                self.answer_split_widgets[q_id] = answer_split
                self.correct_answer_labels[q_id] = correct_label
                row.addWidget(answer_split, 1)

        jump_btn = QPushButton("-")
        jump_btn.setFixedWidth(72)
        jump_btn.setMinimumHeight(30)
        jump_btn.setStyleSheet(
            "font-family: \"JetBrains Mono\", \"Menlo\", \"Consolas\", monospace; "
            "font-size: 12px; font-weight: 700;"
        )
        parsed_page = self._normalize_page_number(item.page)
        jump_btn.setEnabled(parsed_page is not None)
        if parsed_page is not None:
            jump_btn.setText(f"Page {parsed_page}")
            jump_btn.clicked.connect(lambda _, q=q_id, p=parsed_page: self._jump_to_page(q, p))
        row.addWidget(jump_btn)

        self.question_widgets[q_id] = row_widget
        if self._lazy_workspace:
            self._question_container_layout.insertWidget(max(0, self._question_container_layout.count() - 1), row_widget)
        else:
            self._question_container_layout.addWidget(row_widget)


    def _build_text_answer_panel(self, q_id: str) -> Tuple[ResizableAnswerTextEdit, QWidget, QLabel]:
        split = QWidget()
        split_layout = QHBoxLayout(split)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(8)

        entry = ResizableAnswerTextEdit(min_height=74, max_height=560, default_height=96)
        entry.setPlaceholderText("Enter your answer...")
        entry.setMinimumWidth(0)
        entry.setStyleSheet(self._line_edit_base_style(font_size=16, padding=8))
        if self.on_answer_change:
            entry.textChanged.connect(lambda q=q_id: self.on_answer_change(q))
        self._install_text_context_menu(entry)

        correct_label = QLabel("")
        correct_label.setWordWrap(True)
        correct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        correct_label.setStyleSheet(f"color: {_mix_hex(Colors.WARNING, Colors.TEXT_LIGHT, 0.42)}; padding: 6px;")
        correct_label.hide()

        split_layout.addWidget(entry, 1)
        split_layout.addWidget(correct_label, 1)
        split_layout.setStretch(0, 1)
        split_layout.setStretch(1, 1)
        return entry, split, correct_label

    def _install_text_context_menu(self, widget: QTextEdit) -> None:
        if hasattr(widget, "install_rich_text_context_menu"):
            try:
                widget.install_rich_text_context_menu()
                return
            except Exception:
                pass
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda pos, w=widget: self._show_text_context_menu(w, pos))

    def _show_text_context_menu(self, widget: QTextEdit, pos: QPoint) -> None:
        if hasattr(widget, "show_rich_text_context_menu"):
            try:
                widget.show_rich_text_context_menu(pos)
                return
            except Exception:
                pass
        menu = QMenu(widget)
        menu.setObjectName("ExamInputContextMenu")

        action_specs: List[Tuple[str, Callable[[], None]]] = [
            ("Undo", lambda: self._invoke_text_action(widget, "undo")),
            ("Redo", lambda: self._invoke_text_action(widget, "redo")),
            ("Cut", lambda: self._invoke_text_action(widget, "cut")),
            ("Copy", lambda: self._invoke_text_action(widget, "copy")),
            ("Paste", lambda: self._invoke_text_action(widget, "paste")),
            ("Delete", lambda: self._invoke_text_action(widget, "delete")),
            ("Select All", lambda: self._invoke_text_action(widget, "select_all")),
        ]

        for label, callback in action_specs:
            action = QAction(label, menu)
            action.triggered.connect(callback)
            menu.addAction(action)

        menu.exec(widget.mapToGlobal(pos))

    @staticmethod
    def _invoke_text_action(widget: QTextEdit, action_name: str) -> None:
        try:
            if action_name == "undo":
                widget.undo()
            elif action_name == "redo":
                widget.redo()
            elif action_name == "cut":
                widget.cut()
            elif action_name == "copy":
                widget.copy()
            elif action_name == "paste":
                widget.paste()
            elif action_name == "delete":
                cursor = widget.textCursor()
                if cursor.hasSelection():
                    cursor.removeSelectedText()
                    widget.setTextCursor(cursor)
            elif action_name == "select_all":
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
                widget.selectAll()
            elif action_name == "toggle_bold" and hasattr(widget, "_toggle_font_weight"):
                widget._toggle_font_weight()
            elif action_name == "toggle_italic" and hasattr(widget, "_toggle_italic"):
                widget._toggle_italic()
            elif action_name == "toggle_underline" and hasattr(widget, "_toggle_underline"):
                widget._toggle_underline()
            elif action_name == "superscript" and hasattr(widget, "_set_script_mode"):
                widget._set_script_mode("super")
            elif action_name == "subscript" and hasattr(widget, "_set_script_mode"):
                widget._set_script_mode("sub")
            elif action_name == "normal_text" and hasattr(widget, "_set_script_mode"):
                widget._set_script_mode("normal")
        except Exception:
            pass

    def _set_text_result_state(
        self,
        q_id: str,
        bg_color: str,
        right_text: str = "",
        right_visible: bool = False,
        placeholder: str = "",
    ) -> None:
        entry = self.answers.get(q_id)
        if entry:
            entry.setStyleSheet(self._line_edit_state_style(bg_color, font_size=16, padding=8))
            if placeholder:
                entry.setPlaceholderText(placeholder)
            else:
                entry.setPlaceholderText("Enter your answer...")

        label = self.correct_answer_labels.get(q_id)
        if label:
            label.setText(right_text)
            label.setVisible(bool(right_visible and right_text.strip()))

    @staticmethod
    def _line_edit_base_style(font_size: int = 16, padding: int = 8) -> str:
        bg = _input_surface_bg()
        text_color = _contrast_text_for_bg(bg)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(bg, focus_color, 0.06)
        return (
            f"QTextEdit {{ background-color: {bg}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: {padding}px; font-size: {font_size}px; }}"
            f"QTextEdit:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    @staticmethod
    def _note_input_base_style() -> str:
        bg = _input_surface_bg()
        text_color = _contrast_text_for_bg(bg)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(bg, focus_color, 0.06)
        return (
            f"QTextEdit {{ background-color: {bg}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: 8px; font-size: 14px; }}"
            f"QTextEdit:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    @staticmethod
    def _combo_base_style(font_size: int = 14, padding: int = 4, bg_color: Optional[str] = None) -> str:
        bg = bg_color or _input_surface_bg()
        text_color = _contrast_text_for_bg(bg)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(bg, focus_color, 0.06)
        return (
            f"QComboBox {{ background-color: {bg}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: {padding}px; font-size: {font_size}px; }}"
            f"QComboBox:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    @staticmethod
    def _badge_base_style(bg: Optional[str] = None) -> str:
        badge_bg = bg or Colors.BG_MEDIUM
        text_color = _contrast_text_for_bg(badge_bg)
        return (
            f"background-color: {badge_bg}; color: {text_color}; "
            f"border: 1px solid {Colors.BG_LIGHT}; border-radius: 8px; padding: 3px;"
        )

    @staticmethod
    def _line_edit_state_style(bg_color: str, font_size: int = 18, padding: int = 10) -> str:
        text_color = _contrast_text_for_bg(bg_color)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(bg_color, focus_color, 0.06)
        return (
            f"QTextEdit {{ background-color: {bg_color}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: {padding}px; font-size: {font_size}px; }}"
            f"QTextEdit:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    def apply_runtime_theme(self) -> None:
        self.scroll.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")
        if self._container_widget:
            self._container_widget.setStyleSheet(f"background-color: {Colors.BG_LIGHT};")

        for label in self.context_labels.values():
            label.setStyleSheet(f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};")
        for badge in self.marks_labels.values():
            badge.setStyleSheet(self._badge_base_style())
        for entry in self.answers.values():
            entry.setStyleSheet(self._line_edit_base_style(font_size=16, padding=8))
            entry.setPlaceholderText("Enter your answer...")
        for label in self.correct_answer_labels.values():
            label.setStyleSheet(f"color: {_mix_hex(Colors.WARNING, Colors.TEXT_LIGHT, 0.42)}; padding: 6px;")
            label.hide()
        for combo in self.objective_inputs.values():
            combo.setStyleSheet(self._combo_base_style(font_size=16, padding=6))
        for table in self.table_inputs.values():
            table.apply_runtime_theme()
        for note in self.drawing_note_inputs.values():
            note.setStyleSheet(self._note_input_base_style())
        for button in self._drawing_action_buttons:
            if not isinstance(button, QPushButton):
                continue
            action_type = str(button.property("drawingActionType") or "").strip().lower()
            base_color = {
                "open": Colors.SECONDARY,
                "upload": Colors.INFO,
                "clear": Colors.ERROR,
            }.get(action_type, Colors.PRIMARY)
            text = _contrast_text_for_bg(base_color)
            button.setStyleSheet(
                "QPushButton {"
                f"background-color: {base_color};"
                f"color: {text};"
                f"border: 1px solid {_mix_hex(base_color, Colors.BG_DARK, 0.35)};"
                "border-radius: 9px;"
                "padding: 7px 12px;"
                "font-weight: 700;"
                "}"
            )
        for q_id, color in self._drawing_status_colors.items():
            self._set_drawing_status(q_id, self.drawing_status_labels.get(q_id).text() if q_id in self.drawing_status_labels else "", color)

        if self._last_mapping_report:
            self.set_mapping_status(self._last_mapping_report)
        if self._last_grading_results:
            self.highlight_results(self._last_grading_results)

    def set_answer_inputs_enabled(self, enabled: bool) -> None:
        editable = bool(enabled)
        for entry in self.answers.values():
            entry.setReadOnly(not editable)
            entry.setEnabled(True)
        for table in self.table_inputs.values():
            table.set_inputs_enabled(editable)
        for combo in self.objective_inputs.values():
            combo.setEnabled(editable)
        for note in self.drawing_note_inputs.values():
            note.setReadOnly(not editable)
            note.setEnabled(True)
        for button in self._drawing_action_buttons:
            if isinstance(button, QPushButton):
                button.setEnabled(editable)

    def _build_context_text(self, item: QuestionLeaf) -> str:
        if item.main is None:
            return "Unstructured"
        if item.part and item.subpart:
            return f"Question {item.main}, Part ({item.part}), Sub-part ({item.subpart})"
        if item.part:
            return f"Question {item.main}, Part ({item.part})"
        if item.subpart:
            return f"Question {item.main}, Sub-part ({item.subpart})"
        return f"Question {item.main}"

    def _jump_to_page(self, q_id: str, page: int):
        if self.on_jump_to_page:
            self.on_jump_to_page(q_id, page)

    def _normalize_page_number(self, raw_page: Any) -> Optional[int]:
        if raw_page is None:
            return None
        if isinstance(raw_page, bool):
            return None
        if isinstance(raw_page, (int, float)):
            page = int(raw_page)
            return page if page > 0 else None
        text = str(raw_page).strip()
        if not text:
            return None
        match = re.search(r"\d+", text)
        if not match:
            return None
        try:
            page = int(match.group(0))
        except Exception:
            return None
        return page if page > 0 else None

    def set_mapping_status(self, report: Optional[MappingReport]):
        if not report:
            return
        self._last_mapping_report = report
        for q_id, dot in self.status_labels.items():
            entry = report.entries.get(q_id)
            if not entry or not entry.answer_key_id:
                dot.setStyleSheet(f"color: {Colors.ERROR};")
                dot.setToolTip("No answer-key mapping")
                continue
            if entry.confidence >= 0.85:
                color = Colors.SUCCESS
                label = "Confident mapping"
            elif entry.confidence >= 0.65:
                color = Colors.WARNING
                label = "Uncertain mapping"
            else:
                color = Colors.ERROR
                label = "Low-confidence mapping"
            dot.setStyleSheet(f"color: {color};")
            dot.setToolTip(
                f"{label}\n{q_id} -> {entry.answer_key_id}\n"
                f"Strategy: {entry.strategy}\nConfidence: {entry.confidence:.2f}"
            )

    def _drawing_output_path(self, q_id: str) -> str:
        q_safe = re.sub(r"[^a-zA-Z0-9]+", "_", q_id)
        name = f"{self.drawing_file_prefix}_{q_safe}.png"
        return os.path.join(self.drawing_session_dir, name)

    def _set_drawing_note(self, q_id: str, text: str):
        self.drawing_notes[q_id] = text
        if self.on_answer_change:
            self.on_answer_change(q_id)

    def _set_drawing_status(self, q_id: str, message: str, color: str):
        label = self.drawing_status_labels.get(q_id)
        if label:
            label.setText(message)
            label.setStyleSheet(f"color: {color};")
        self._drawing_status_colors[q_id] = color

    def _open_drawing_canvas(self, q_id: str):
        output_path = self._drawing_output_path(q_id)
        existing = self.drawing_paths.get(q_id) or None
        reference_path = self.drawing_reference_images.get(q_id) or None
        dialog = DrawingEditorDialog(
            output_path=output_path,
            existing_path=existing,
            reference_path=reference_path,
            parent=self,
        )
        accepted = dialog.exec()
        dialog.deleteLater()
        if accepted:
            self.drawing_paths[q_id] = output_path
            self._set_drawing_status(q_id, f"Canvas saved: {os.path.basename(output_path)}", Colors.SUCCESS)
            if self.on_answer_change:
                self.on_answer_change(q_id)

    def _replace_or_upload_drawing(self, q_id: str):
        if self.drawing_paths.get(q_id):
            self._open_drawing_canvas(q_id)
        else:
            self._upload_drawing(q_id)

    def _upload_drawing(self, q_id: str):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload Drawing",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        out_path = self._drawing_output_path(q_id)
        try:
            shutil.copy2(path, out_path)
            self.drawing_paths[q_id] = out_path
            self._set_drawing_status(q_id, f"Uploaded: {os.path.basename(path)}", Colors.SUCCESS)
            if self.on_answer_change:
                self.on_answer_change(q_id)
        except Exception as e:
            show_error(self, "Upload Error", f"Could not load drawing: {e}")

    def clear_drawing(self, q_id: str):
        if self.drawing_paths.get(q_id) and QMessageBox.question(self, 'Clear drawing',
                'Remove this drawing from your answer?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.drawing_paths[q_id] = ""
        self._set_drawing_status(q_id, "No drawing", Colors.WARNING)
        if q_id in self.drawing_note_inputs:
            self.drawing_note_inputs[q_id].clear()
        self.drawing_notes[q_id] = ""
        if self.on_answer_change:
            self.on_answer_change(q_id)

    def set_marks(self, question_marks: Dict[str, float]):
        # Marks are intentionally hidden from row inputs per UX request.
        return

    def get_answers(self):
        payload: Dict[str, Dict[str, Any]] = {}
        section_types = getattr(self, "section_types", {})
        for q_id in self.question_ids:
            if q_id in self.hidden_questions:
                continue
            if q_id in self._pending_answers and q_id not in self.question_widgets:
                payload[q_id] = self._pending_answers[q_id]
                continue
            response_type = self.answer_types.get(q_id, "text")
            section_type = section_types.get(q_id, "written")
            if response_type == "drawing":
                payload[q_id] = {
                    "type": "drawing",
                    "image_path": self.drawing_paths.get(q_id, ""),
                    "notes": self.drawing_notes.get(q_id, ""),
                }
            elif response_type == "table" and q_id in self.table_inputs:
                table = self.table_inputs[q_id]
                payload[q_id] = {
                    "type": "table",
                    "cells": table.get_cell_answers(),
                    "value": table.to_serialized_answer(),
                }
            else:
                if section_type == "objective" and q_id in self.objective_inputs:
                    value = (self.objective_inputs[q_id].currentText() or "").strip()
                else:
                    if q_id in self.answers:
                        entry_obj = self.answers.get(q_id)
                        value = _editor_to_caret_text(entry_obj)
                    else:
                        value = ""
                payload[q_id] = {
                    "type": "text",
                    "value": value,
                }
        return payload

    def apply_saved_answers(self, saved_answers: Dict[str, Any]) -> None:
        if not isinstance(saved_answers, dict):
            return

        for raw_qid, raw_payload in saved_answers.items():
            q_id = normalize_question_id(str(raw_qid))
            if not q_id:
                continue

            if self._lazy_workspace and q_id not in self.question_widgets:
                self._pending_answers[q_id] = raw_payload
                continue
            response_type = self.answer_types.get(q_id, "text")
            section_type = self.section_types.get(q_id, "written")

            if response_type == "drawing":
                note_text = ""
                if isinstance(raw_payload, dict):
                    note_text = str(raw_payload.get("notes", "") or "")
                    source_path = str(raw_payload.get("image_path", "") or "").strip()
                else:
                    source_path = str(raw_payload or "").strip()

                note_input = self.drawing_note_inputs.get(q_id)
                if note_input:
                    blocked = note_input.blockSignals(True)
                    _editor_set_caret_text(note_input, note_text)
                    note_input.blockSignals(blocked)
                self.drawing_notes[q_id] = note_text

                restored_path = ""
                if source_path and os.path.exists(source_path):
                    target_path = self._drawing_output_path(q_id)
                    try:
                        if os.path.abspath(source_path) != os.path.abspath(target_path):
                            shutil.copy2(source_path, target_path)
                        elif not os.path.exists(target_path):
                            shutil.copy2(source_path, target_path)
                        restored_path = target_path
                    except Exception:
                        restored_path = source_path

                self.drawing_paths[q_id] = restored_path
                if restored_path and os.path.exists(restored_path):
                    self._set_drawing_status(
                        q_id,
                        f"Restored: {os.path.basename(restored_path)}",
                        Colors.SUCCESS,
                    )
                elif note_text.strip():
                    self._set_drawing_status(
                        q_id,
                        "Drawing notes restored (image file unavailable)",
                        Colors.WARNING,
                    )
                else:
                    self._set_drawing_status(q_id, "No drawing", Colors.WARNING)
                continue

            if response_type == "table" and q_id in self.table_inputs:
                table_widget = self.table_inputs.get(q_id)
                if table_widget and isinstance(raw_payload, dict):
                    cells = raw_payload.get("cells", {})
                    if isinstance(cells, dict):
                        table_widget.set_cell_answers(cells)
                continue

            if section_type == "objective" and q_id in self.objective_inputs:
                combo = self.objective_inputs.get(q_id)
                if not combo:
                    continue
                if isinstance(raw_payload, dict):
                    option = str(raw_payload.get("value", "") or "").strip().upper()
                else:
                    option = str(raw_payload or "").strip().upper()
                if option in {"A", "B", "C", "D"}:
                    index = combo.findText(option)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                continue

            entry = self.answers.get(q_id)
            if not entry:
                continue
            if isinstance(raw_payload, dict):
                value = str(raw_payload.get("value", "") or "")
            else:
                value = str(raw_payload or "")
            _editor_set_caret_text(entry, value)

    def get_completion_state(self) -> Dict[str, bool]:
        state: Dict[str, bool] = {}
        payload = self.get_answers()
        for q_id in self.question_ids:
            if q_id in self.hidden_questions:
                continue
            item = payload.get(q_id, {})
            if not isinstance(item, dict):
                state[q_id] = bool(str(item).strip())
                continue
            ans_type = str(item.get("type", "")).strip().lower()
            if ans_type == "drawing":
                state[q_id] = bool(str(item.get("image_path", "")).strip())
            elif ans_type == "table":
                table_widget = self.table_inputs.get(q_id)
                if table_widget:
                    state[q_id] = bool(table_widget.has_answer())
                else:
                    cells = item.get("cells", {})
                    state[q_id] = any(
                        str(v or "").strip().lower() not in {"", "no check"}
                        for v in (cells.values() if isinstance(cells, dict) else [])
                    )
            else:
                state[q_id] = bool(str(item.get("value", "")).strip())
        return state

    def get_text_answers_legacy(self) -> Dict[str, str]:
        legacy: Dict[str, str] = {}
        for q_id, entry in self.answers.items():
            if q_id in self.hidden_questions:
                continue
            text = _editor_to_caret_text(entry)
            if text.strip():
                legacy[q_id] = text
        for q_id, table in getattr(self, "table_inputs", {}).items():
            if q_id in self.hidden_questions:
                continue
            value = table.to_serialized_answer()
            if value.strip():
                legacy[q_id] = value
        for q_id, combo in getattr(self, "objective_inputs", {}).items():
            if q_id in self.hidden_questions:
                continue
            value = (combo.currentText() or "").strip()
            if value:
                legacy[q_id] = value
        return legacy

    def set_question_visibility(self, q_id: str, visible: bool) -> None:
        q_norm = normalize_question_id(str(q_id or ""))
        if not q_norm:
            return
        widget = self.question_widgets.get(q_norm)
        if widget is not None:
            widget.setVisible(bool(visible))
        if visible:
            self.hidden_questions.discard(q_norm)
        else:
            self.hidden_questions.add(q_norm)

    def set_hidden_questions(self, hidden_qids: List[str]) -> None:
        hidden = {normalize_question_id(str(q)) for q in (hidden_qids or []) if normalize_question_id(str(q))}
        for q_id in self.question_ids:
            self.set_question_visibility(q_id, q_id not in hidden)

    def is_question_hidden(self, q_id: str) -> bool:
        q_norm = normalize_question_id(str(q_id or ""))
        return q_norm in self.hidden_questions

    def visible_question_ids(self) -> List[str]:
        return [q for q in self.question_ids if q not in self.hidden_questions]

    @staticmethod
    def _badge_source_label(result: Dict[str, Any]) -> str:
        source = str(result.get("grading_source", "") or "").lower()
        manual = bool(result.get("manual_review_required", False))
        if manual:
            if source.startswith("ai"):
                return "AI->MANUAL"
            return "MANUAL"
        if "objective" in source:
            return "OBJ"
        if source == "optional_skipped":
            return "SKIP"
        if source == "blank_response":
            return "BLANK"
        if source.startswith("rule_engine"):
            return "RULE"
        if source == "ai_drawing":
            return "AI-DRAW"
        if source == "ai":
            return "AI"
        if source.startswith("baseline"):
            return "BASE"
        if source.startswith("manual"):
            return "MANUAL"
        if source:
            return source.replace("_", "-").upper()[:12]
        return "AUTO"

    @staticmethod
    def _coerce_badge_mark(value: Any) -> float:
        try:
            parsed = float(value)
            if math.isfinite(parsed):
                return parsed
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _truncate_tooltip(text: Any, limit: int = 180) -> str:
        raw = str(text or "").strip()
        if not raw:
            return "n/a"
        if len(raw) <= limit:
            return raw
        return raw[: max(0, limit - 3)] + "..."

    def _set_result_badge(self, q_id: str, result: Dict[str, Any]) -> None:
        badge = self.marks_labels.get(q_id)
        if not badge:
            return
        if not result:
            badge.clear()
            badge.setVisible(False)
            badge.setToolTip("")
            return

        earned = self._coerce_badge_mark(result.get("awarded_marks", result.get("earned_marks", 0.0)))
        total = self._coerce_badge_mark(result.get("max_marks", result.get("total_marks", 0.0)))
        source = self._badge_source_label(result)
        badge.setText(f"{earned:g}/{total:g} | {source}")
        badge.setVisible(True)

        manual_review = bool(result.get("manual_review_required", False))
        is_correct = bool(result.get("is_correct", False))
        has_answer = bool(str(result.get("student_answer", "")).strip())
        if manual_review:
            bg = Colors.WARNING
        elif result.get("optional_unselected", False) or not has_answer:
            bg = Colors.INFO
        elif is_correct:
            bg = Colors.SUCCESS
        else:
            bg = Colors.ERROR

        badge_text = _contrast_text_for_bg(bg)
        badge.setStyleSheet(
            f"background-color: {bg}; color: {badge_text}; border: 1px solid {Colors.BG_LIGHT}; border-radius: 8px; padding: 3px;"
        )

        model_name = str(result.get("model_used", "") or "n/a")
        fallback_used = "yes" if bool(result.get("model_fallback_used", False)) else "no"
        tooltip = (
            f"Answer: {self._truncate_tooltip(result.get('student_answer', ''), 220)}\n"
            f"Mark scheme: {self._truncate_tooltip(result.get('mark_scheme_text', result.get('correct_answer', '')), 220)}\n"
            f"Feedback: {self._truncate_tooltip(result.get('explanation', result.get('feedback', '')), 260)}\n"
            f"Max marks source: {self._truncate_tooltip(result.get('max_marks_source', ''), 60)}\n"
            f"Mapping: {self._truncate_tooltip(result.get('mapping_strategy', ''), 60)}\n"
            f"Model: {model_name}\n"
            f"Model fallback used: {fallback_used}"
        )
        badge.setToolTip(tooltip)

    def highlight_results(self, grading_results: Dict[str, Dict]):
        self._last_grading_results = dict(grading_results or {})
        for q_id in self.question_ids:
            response_type = self.answer_types.get(q_id, "text")
            result = grading_results.get(q_id, {})
            self._set_result_badge(q_id, result)

            if response_type == "drawing":
                status = result.get("manual_review_status", "manual_review_required")
                if result.get("manual_review_required", False):
                    if status == "drawing_submitted_pending_review":
                        self._set_drawing_status(q_id, "Manual review required (drawing submitted)", Colors.WARNING)
                    else:
                        self._set_drawing_status(q_id, "Manual review required (no drawing uploaded)", Colors.ERROR)
                continue

            if result.get("optional_unselected", False):
                if response_type == "table" and q_id in self.table_inputs:
                    self.table_inputs[q_id].set_state(Colors.INFO)
                elif self.section_types.get(q_id, "written") == "objective":
                    combo = self.objective_inputs.get(q_id)
                    if combo:
                        combo.setStyleSheet(self._combo_base_style(font_size=16, padding=4, bg_color=Colors.INFO))
                else:
                    self._set_text_result_state(
                        q_id=q_id,
                        bg_color=Colors.INFO,
                        placeholder="Optional question not selected",
                        right_visible=False,
                    )
                continue

            if response_type == "table" and q_id in self.table_inputs:
                table = self.table_inputs[q_id]
                is_correct = bool(result.get("is_correct", False))
                has_answer = bool(str(result.get("student_answer", "")).strip())
                manual_review_required = bool(result.get("manual_review_required", False))
                placeholder_key = _is_placeholder_answer(result.get("correct_answer", ""))
                if manual_review_required:
                    table.set_state(Colors.WARNING)
                elif not has_answer:
                    table.set_state(Colors.INFO)
                elif is_correct:
                    table.set_state(Colors.SUCCESS)
                else:
                    table.set_state(Colors.WARNING if placeholder_key else Colors.ERROR)
                continue

            if self.section_types.get(q_id, "written") == "objective":
                combo = self.objective_inputs.get(q_id)
                if combo:
                    is_correct = bool(result.get("is_correct", False))
                    has_answer = bool(str(result.get("student_answer", "")).strip())
                    if not has_answer:
                        combo.setStyleSheet(self._combo_base_style(font_size=16, padding=4, bg_color=Colors.INFO))
                    elif is_correct:
                        combo.setStyleSheet(self._combo_base_style(font_size=16, padding=4, bg_color=Colors.SUCCESS))
                    else:
                        combo.setStyleSheet(self._combo_base_style(font_size=16, padding=4, bg_color=Colors.ERROR))
                continue

            is_correct = result.get("is_correct", False)
            has_answer = bool(str(result.get("student_answer", "")).strip())
            correct_ans = result.get("correct_answer", "")
            _dbg(
                f"[DBG-UI-ROW] qid={q_id} has_answer={has_answer} is_correct={is_correct} "
                f"student={repr(str(result.get('student_answer', ''))[:80])} "
                f"correct={repr(str(correct_ans)[:80])}"
            )

            manual_review_required = bool(result.get("manual_review_required", False))
            placeholder_key = _is_placeholder_answer(correct_ans)

            if q_id not in self.answers:
                continue

            if manual_review_required:
                self._set_text_result_state(
                    q_id=q_id,
                    bg_color=Colors.WARNING,
                    placeholder="Manual review required",
                    right_visible=False,
                )
            elif not has_answer:
                placeholder = "No fixed key available" if placeholder_key else "Enter your answer..."
                self._set_text_result_state(
                    q_id=q_id,
                    bg_color=Colors.INFO,
                    placeholder=placeholder,
                    right_visible=False,
                )
            elif is_correct:
                self._set_text_result_state(
                    q_id=q_id,
                    bg_color=Colors.SUCCESS,
                    right_visible=False,
                )
            else:
                if placeholder_key:
                    self._set_text_result_state(
                        q_id=q_id,
                        bg_color=Colors.WARNING,
                        placeholder="Rubric/manual review recommended",
                        right_visible=False,
                    )
                else:
                    self._set_text_result_state(
                        q_id=q_id,
                        bg_color=Colors.ERROR,
                        right_text=f"Correct answer:\n{correct_ans}",
                        right_visible=True,
                    )

    def scroll_to_question(self, q_id: str):
        q_norm = normalize_question_id(q_id)
        widget = self.question_widgets.get(q_norm)
        if widget:
            try:
                self.scroll.ensureWidgetVisible(widget)
            except Exception:
                try:
                    bar = self.scroll.verticalScrollBar()
                    bar.setValue(widget.y())
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Background Written Grading
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class GradingJobInput:
    answers: Dict[str, Dict[str, Any]]
    question_ids: List[str]
    question_texts: Dict[str, str]
    question_marks: Dict[str, float]
    question_response_types: Dict[str, str]
    question_section_types: Dict[str, str]
    subject_code: str
    paper_num: int
    year: str
    subject_name: str = ""
    past_paper_code: str = ""
    exam_year: int = 2026
    paper_mode: str = "WRITTEN_ONLY"
    pdf_url: Optional[str] = None
    question_pdf_path: Optional[str] = None
    paper_instruction_text: str = ""
    mark_scheme_path: Optional[str] = None
    series: str = ""
    component_code: str = ""
    grade_threshold_url: str = ""
    question_url: str = ""
    mark_scheme_url: str = ""
    manual_overrides: Dict[str, str] = field(default_factory=dict)
    optional_selection: Dict[str, List[str]] = field(default_factory=dict)
    use_ai: bool = False
    ai_options: Optional[AIGradingOptions] = None
    official_total_marks: Optional[float] = None
    question_mark_hints: Dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class GradingJobResult:
    results: Dict[str, Any]
    mapping_report: MappingReport
    expanded_key: Dict[str, Dict[str, Any]]
    resolved_marks: Dict[str, float]
    source_label: str
    warnings: List[str] = field(default_factory=list)
    cancelled: bool = False
    auto_graded_marks: float = 0.0
    auto_graded_total_marks: float = 0.0
    pending_manual_marks: float = 0.0
    final_confirmed_marks: float = 0.0
    pending_manual_count: int = 0


class GradingWorker(QThread):
    progress = Signal(str, float)
    resolved_marks_ready = Signal(dict)
    finished_payload = Signal(object)
    failed = Signal(str, str)
    cancelled_payload = Signal(object)

    def __init__(self, job: GradingJobInput):
        super().__init__()
        self.job = job
        self._cancel_event = threading.Event()

    def request_cancel(self):
        self._cancel_event.set()

    def _cancel_check(self) -> bool:
        return self._cancel_event.is_set()

    @staticmethod
    def _coerce_positive_mark(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except Exception:
            return float(default)
        if not math.isfinite(parsed) or parsed <= 0:
            return float(default)
        return float(parsed)

    def _resolve_authoritative_total_marks(self, expanded_key: Dict[str, Dict[str, Any]]) -> Optional[float]:
        explicit = self._coerce_positive_mark(getattr(self.job, "official_total_marks", None), default=0.0)
        if explicit > 0:
            return explicit

        parsed = parse_total_marks_from_front_page_text(str(self.job.paper_instruction_text or ""))
        if isinstance(parsed, int) and parsed > 0:
            return float(parsed)

        computed = 0.0
        for qid in self.job.question_ids:
            computed += self._coerce_positive_mark(
                (expanded_key.get(qid, {}) or {}).get("marks", self.job.question_marks.get(qid, 0.0)),
                default=0.0,
            )
        return computed if computed > 0 else None

    @staticmethod
    def _mark_adjustment_priority(qid: str, entry: Dict[str, Any], source: str) -> float:
        mapping_source = str(entry.get("mapping_source", "") or "").strip().lower()
        confidence = 0.0
        try:
            confidence = float(entry.get("mapping_confidence", 0.0) or 0.0)
        except Exception:
            confidence = 0.0
        answer_text = str(entry.get("answer", "") or "").strip().lower()

        if mapping_source == "unmatched_placeholder":
            return 0.0
        if source == "fallback":
            return 0.5
        if source == "hint":
            return 1.0
        if mapping_source == "answer_key_expanded":
            return 1.5
        if confidence <= 0.65:
            return 2.0
        if answer_text in {"[see mark scheme]", ""}:
            return 2.5
        if mapping_source in {"answer_key_direct", "answer_key_expanded"} and confidence >= 0.9:
            return 4.0
        return 3.0

    def _apply_mark_total_normalization(
        self,
        marks: Dict[str, float],
        official_total: Optional[float],
        sources: Dict[str, str],
        expanded_key: Dict[str, Dict[str, Any]],
    ) -> Dict[str, float]:
        target = self._coerce_positive_mark(official_total, default=0.0)
        if target <= 0 or not marks:
            return dict(marks)

        normalized = {qid: self._coerce_positive_mark(value, default=0.0) for qid, value in marks.items()}
        current_total = float(sum(normalized.values()))
        if current_total <= 0:
            return normalized

        diff = float(target - current_total)
        if abs(diff) <= 1e-6:
            return normalized

        priorities: Dict[str, float] = {}
        for qid in normalized.keys():
            entry = dict(expanded_key.get(qid, {}) or {})
            priorities[qid] = self._mark_adjustment_priority(qid, entry, sources.get(qid, "fallback"))

        ordered_qids = sorted(normalized.keys(), key=lambda q: (priorities.get(q, 99.0), str(q)))
        floor_value = 0.0 if len(ordered_qids) <= 1 else 0.1

        if diff > 0:
            remaining = diff
            for priority in sorted({priorities.get(q, 99.0) for q in ordered_qids}):
                bucket = [q for q in ordered_qids if priorities.get(q, 99.0) == priority]
                if not bucket or remaining <= 1e-9:
                    continue
                weights = [max(1.0, normalized.get(q, 0.0)) for q in bucket]
                total_weight = float(sum(weights) or len(bucket))
                consumed = 0.0
                for idx, qid in enumerate(bucket):
                    if idx == len(bucket) - 1:
                        delta = max(0.0, remaining - consumed)
                    else:
                        delta = max(0.0, round((remaining * weights[idx]) / total_weight, 6))
                        consumed += delta
                    normalized[qid] = float(normalized.get(qid, 0.0) + delta)
                remaining = 0.0
        else:
            remaining = abs(diff)
            for priority in sorted({priorities.get(q, 99.0) for q in ordered_qids}):
                bucket = [q for q in ordered_qids if priorities.get(q, 99.0) == priority]
                if not bucket or remaining <= 1e-9:
                    continue
                capacities = [max(0.0, normalized.get(q, 0.0) - floor_value) for q in bucket]
                capacity_sum = float(sum(capacities))
                if capacity_sum <= 1e-9:
                    continue
                take = min(remaining, capacity_sum)
                consumed = 0.0
                for idx, qid in enumerate(bucket):
                    if capacities[idx] <= 0:
                        continue
                    if idx == len(bucket) - 1:
                        delta = max(0.0, min(capacities[idx], take - consumed))
                    else:
                        delta = max(0.0, min(capacities[idx], round((take * capacities[idx]) / capacity_sum, 6)))
                        consumed += delta
                    normalized[qid] = float(max(floor_value, normalized.get(qid, 0.0) - delta))
                remaining -= take

            if remaining > 1e-6:
                for qid in ordered_qids:
                    if remaining <= 1e-9:
                        break
                    available = max(0.0, normalized.get(qid, 0.0))
                    if available <= 0:
                        continue
                    delta = min(available, remaining)
                    normalized[qid] = float(max(0.0, normalized.get(qid, 0.0) - delta))
                    remaining -= delta

        normalized = {qid: float(round(value, 6)) for qid, value in normalized.items()}
        final_total = float(sum(normalized.values()))
        residual = float(target - final_total)
        if abs(residual) > 1e-6 and ordered_qids:
            for qid in ordered_qids:
                base = float(normalized.get(qid, 0.0))
                candidate = base + residual
                if candidate >= 0:
                    normalized[qid] = float(round(candidate, 6))
                    break
        return normalized

    def _build_reconciled_marks_candidate(
        self,
        expanded_key: Dict[str, Dict[str, Any]],
        mapping_report: MappingReport,
        official_total: Optional[float],
        *,
        normalize_to_total: bool,
    ) -> Dict[str, Any]:
        mark_hints = {
            normalize_question_id(qid): self._coerce_positive_mark(value, default=0.0)
            for qid, value in dict(getattr(self.job, "question_mark_hints", {}) or {}).items()
            if normalize_question_id(qid)
        }

        base_marks: Dict[str, float] = {}
        source_map: Dict[str, str] = {}
        merged_key: Dict[str, Dict[str, Any]] = {normalize_question_id(k): dict(v) for k, v in (expanded_key or {}).items() if normalize_question_id(k)}

        for raw_qid in self.job.question_ids:
            qid = normalize_question_id(raw_qid)
            if not qid:
                continue
            entry = dict(merged_key.get(qid, {}) or {})

            from_expanded = self._coerce_positive_mark(entry.get("marks", None), default=0.0)
            from_hint = self._coerce_positive_mark(mark_hints.get(qid, None), default=0.0)
            if from_expanded > 0:
                chosen = from_expanded
                source = str(entry.get("max_marks_source", "") or "expanded")
            elif from_hint > 0:
                chosen = from_hint
                source = "question_paper_hint"
            else:
                chosen = 0.0
                source = "unresolved"

            base_marks[qid] = float(chosen)
            source_map[qid] = source
            entry["marks"] = float(chosen)
            merged_key[qid] = entry

        raw_total = float(sum(base_marks.values()))
        normalized_marks = dict(base_marks)
        if normalize_to_total:
            normalized_marks = self._apply_mark_total_normalization(
                normalized_marks,
                official_total,
                source_map,
                merged_key,
            )

        for qid in list(normalized_marks.keys()):
            entry = dict(merged_key.get(qid, {}) or {})
            entry["marks"] = float(normalized_marks[qid])
            merged_key[qid] = entry

        official_value = self._coerce_positive_mark(official_total, default=0.0)
        raw_diff = abs(raw_total - official_value) if official_value > 0 else 0.0
        fallback_count = sum(1 for source in source_map.values() if source in {"unresolved", "fallback"})
        return {
            "expanded_key": merged_key,
            "resolved_marks": {qid: float(normalized_marks[qid]) for qid in self.job.question_ids if qid in normalized_marks},
            "raw_total": raw_total,
            "raw_diff": raw_diff,
            "coverage": float(mapping_report.coverage),
            "fallback_count": fallback_count,
            "mark_sources": source_map,
        }

    @staticmethod
    def _candidate_is_better(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
        candidate_diff = float(candidate.get("raw_diff", math.inf))
        current_diff = float(current.get("raw_diff", math.inf))
        if candidate_diff + 1e-6 < current_diff:
            return True
        if current_diff + 1e-6 < candidate_diff:
            return False

        candidate_cov = float(candidate.get("coverage", 0.0) or 0.0)
        current_cov = float(current.get("coverage", 0.0) or 0.0)
        if candidate_cov > current_cov + 1e-6:
            return True
        if current_cov > candidate_cov + 1e-6:
            return False

        candidate_fallback = int(candidate.get("fallback_count", 0) or 0)
        current_fallback = int(current.get("fallback_count", 0) or 0)
        return candidate_fallback < current_fallback

    def _recount_with_relaxed_answer_key(self) -> Optional[Tuple[MappingReport, Dict[str, Dict[str, Any]]]]:
        mark_scheme_path = str(self.job.mark_scheme_path or "").strip()
        if (not mark_scheme_path or not os.path.exists(mark_scheme_path)) and self.job.pdf_url:
            downloaded = self._download_mark_scheme_candidate()
            if downloaded:
                mark_scheme_path = downloaded
        if not mark_scheme_path or not os.path.exists(mark_scheme_path):
            return None

        parser = MarkSchemeParser()
        relaxed_key: Dict[str, Dict[str, Any]] = {}
        question_marks = _question_mark_lookup(
            getattr(self.job, "question_marks", {}),
            getattr(self.job, "question_mark_hints", {}),
        )
        if is_math_subject_code(self.job.subject_code, self.job.subject_name):
            relaxed_key = extract_math_mark_scheme(
                mark_scheme_path,
                expected_question_ids=None,
            )
        else:
            ms_text = parser.extract_text_from_pdf(mark_scheme_path)
            relaxed_key = parser.parse_written_mark_scheme(
                ms_text,
                expected_question_ids=None,
            )
            relaxed_key = _apply_question_paper_mark_validation(relaxed_key, question_marks)
        if not relaxed_key:
            return None

        normalized_relaxed_key = {normalize_question_id(k): dict(v) for k, v in relaxed_key.items() if normalize_question_id(k)}
        if not normalized_relaxed_key:
            return None

        mapper = QuestionIDMapper()
        relaxed_mapping_report = mapper.generate_mapping(
            self.job.question_ids,
            list(normalized_relaxed_key.keys()),
            question_order=self.job.question_ids,
            manual_overrides=self.job.manual_overrides,
        )
        relaxed_expanded_key = mapper.expand_answer_key(
            answer_key=normalized_relaxed_key,
            mapping=relaxed_mapping_report,
            question_marks=self.job.question_mark_hints,
            policy="strict_leaf",
        )
        return relaxed_mapping_report, relaxed_expanded_key

    def run(self):
        try:
            self.progress.emit("Resolving answer key...", 0.05)
            answer_key, source_label = self._load_candidate_answer_key()
            normalized_key = {normalize_question_id(k): dict(v) for k, v in answer_key.items()}

            if self._cancel_check():
                self.cancelled_payload.emit(
                    GradingJobResult(
                        results={},
                        mapping_report=MappingReport(),
                        expanded_key={},
                        resolved_marks=dict(self.job.question_marks),
                        source_label=source_label,
                        warnings=["Cancelled before mapping."],
                        cancelled=True,
                    )
                )
                return

            self.progress.emit("Mapping question IDs...", 0.15)
            mapper = QuestionIDMapper()
            mapping_report = mapper.generate_mapping(
                self.job.question_ids,
                list(normalized_key.keys()),
                question_order=self.job.question_ids,
                manual_overrides=self.job.manual_overrides,
            )

            self.progress.emit("Expanding answer key...", 0.22)
            expanded_key = mapper.expand_answer_key(
                answer_key=normalized_key,
                mapping=mapping_report,
                question_marks=self.job.question_mark_hints,
                policy="strict_leaf",
            )

            warnings: List[str] = []
            final_total_guard_messages: List[str] = []
            explicit_official = self._coerce_positive_mark(getattr(self.job, "official_total_marks", None), default=0.0)
            parsed_official = parse_total_marks_from_front_page_text(str(self.job.paper_instruction_text or ""))
            official_is_authoritative = False
            if explicit_official > 0:
                official_total_marks = explicit_official
                official_is_authoritative = True
            elif isinstance(parsed_official, int) and parsed_official > 0:
                official_total_marks = float(parsed_official)
                official_is_authoritative = True
            else:
                official_total_marks = self._resolve_authoritative_total_marks(expanded_key)
            pregrade_choice_structure = parse_choice_structure(
                str(self.job.paper_instruction_text or ""),
                list(self.job.question_ids or []),
                {qid: str(self.job.question_texts.get(qid, "") or "") for qid in list(self.job.question_ids or [])},
            )
            normalize_pregrade_to_total = False
            candidate = self._build_reconciled_marks_candidate(
                expanded_key,
                mapping_report,
                official_total_marks,
                normalize_to_total=normalize_pregrade_to_total,
            )
            chosen_candidate = candidate

            official_value = self._coerce_positive_mark(official_total_marks, default=0.0)
            if official_value > 0 and official_is_authoritative and float(candidate.get("raw_diff", 0.0) or 0.0) > 0.01:
                recounted = self._recount_with_relaxed_answer_key()
                if recounted:
                    relaxed_mapping_report, relaxed_expanded_key = recounted
                    relaxed_candidate = self._build_reconciled_marks_candidate(
                        relaxed_expanded_key,
                        relaxed_mapping_report,
                        official_total_marks,
                        normalize_to_total=normalize_pregrade_to_total,
                    )
                    if self._candidate_is_better(relaxed_candidate, chosen_candidate):
                        chosen_candidate = relaxed_candidate
                        mapping_report = relaxed_mapping_report
                        warnings.append(
                            "Recounted and rechecked mark allocation using relaxed mark-scheme parsing due total-mark mismatch."
                        )
                    else:
                        warnings.append(
                            "Retained primary mark allocation after recount/recheck comparison."
                        )

            expanded_key = dict(chosen_candidate.get("expanded_key", {}) or {})
            resolved_marks = {
                qid: float((chosen_candidate.get("resolved_marks", {}) or {}).get(qid, self.job.question_marks.get(qid, 1.0)))
                for qid in self.job.question_ids
            }
            resolved_mark_sources = {
                normalize_question_id(k): str(v)
                for k, v in dict(chosen_candidate.get("mark_sources", {}) or {}).items()
                if normalize_question_id(k)
            }
            self.resolved_marks_ready.emit(resolved_marks)

            if mapping_report.unmatched_extracted or mapping_report.coverage < 0.9:
                warnings.append(
                    "Coverage "
                    f"{mapping_report.coverage*100:.1f}% (source: {source_label}); "
                    f"unmatched: {', '.join(mapping_report.unmatched_extracted[:10]) or 'None'}"
                )
            if official_value > 0 and official_is_authoritative:
                resolved_total = float(sum(float(v) for v in resolved_marks.values()))
                if abs(resolved_total - official_value) > 0.01 and normalize_pregrade_to_total:
                    warnings.append(
                        f"Resolved question marks still differ from official total ({resolved_total:.2f}/{official_value:.2f}) after reconciliation."
                    )

            if self._cancel_check():
                self.cancelled_payload.emit(
                    GradingJobResult(
                        results={},
                        mapping_report=mapping_report,
                        expanded_key=expanded_key,
                        resolved_marks=resolved_marks,
                        source_label=source_label,
                        warnings=warnings + ["Cancelled before grading started."],
                        cancelled=True,
                    )
                )
                return

            self.progress.emit("Grading responses...", 0.3)

            def _ai_progress(done: int, total: int, message: str):
                frac = 0.3 if total <= 0 else 0.3 + min(0.69, (done / total) * 0.69)
                self.progress.emit(message, frac)

            normalized_payloads: Dict[str, Dict[str, Any]] = {}
            for qid in self.job.question_ids:
                raw_payload = self.job.answers.get(qid, {})
                if isinstance(raw_payload, dict):
                    p_type = str(raw_payload.get("type", "")).strip().lower()
                    if p_type == "drawing":
                        normalized_payloads[qid] = {
                            "type": "drawing",
                            "image_path": str(raw_payload.get("image_path", "") or "").strip(),
                            "notes": str(raw_payload.get("notes", "") or "").strip(),
                        }
                    elif p_type == "table":
                        cells_payload = raw_payload.get("cells", {})
                        normalized_payloads[qid] = {
                            "type": "table",
                            "cells": dict(cells_payload) if isinstance(cells_payload, dict) else {},
                            "value": str(raw_payload.get("value", "") or ""),
                        }
                    else:
                        normalized_payloads[qid] = {
                            "type": "text",
                            "value": str(raw_payload.get("value", "") or ""),
                        }
                else:
                    normalized_payloads[qid] = {"type": "text", "value": str(raw_payload or "")}

            response_types = {normalize_question_id(k): v for k, v in (self.job.question_response_types or {}).items()}
            section_types = {normalize_question_id(k): v for k, v in (self.job.question_section_types or {}).items()}
            text_qids: List[str] = []
            drawing_qids: List[str] = []
            for qid in self.job.question_ids:
                payload_type = normalized_payloads.get(qid, {}).get("type", "text")
                declared = response_types.get(qid, "text")
                if declared == "drawing" or payload_type == "drawing":
                    drawing_qids.append(qid)
                else:
                    text_qids.append(qid)

            table_qids = [
                qid
                for qid in text_qids
                if response_types.get(qid, "text") == "table"
                or normalized_payloads.get(qid, {}).get("type", "text") == "table"
            ]
            objective_qids = [
                qid
                for qid in text_qids
                if section_types.get(qid, "written") == "objective" and qid not in table_qids
            ]
            written_qids = [qid for qid in text_qids if qid not in objective_qids]
            _dbg(
                f"[DBG-WORKER-SPLIT] text_qids={text_qids} written_qids={written_qids} "
                f"objective_qids={objective_qids} table_qids={table_qids} drawing_qids={drawing_qids}"
            )

            text_user_answers: Dict[str, str] = {}
            for qid in text_qids:
                payload = normalized_payloads.get(qid, {})
                text_user_answers[qid] = str(payload.get("value", "") or "")

            written_user_answers: Dict[str, str] = {qid: text_user_answers.get(qid, "") for qid in written_qids}
            written_answer_key: Dict[str, Dict[str, Any]] = {}
            written_question_texts: Dict[str, str] = {}

            explicit_selection = self.job.optional_selection if isinstance(self.job.optional_selection, dict) else {}
            choice_structure = parse_choice_structure(
                str(self.job.paper_instruction_text or ""),
                list(written_qids),
                {qid: str(self.job.question_texts.get(qid, "") or "") for qid in written_qids},
            )
            choice_resolution = resolve_choice_selection(
                structure=choice_structure,
                answers={qid: str(text_user_answers.get(qid, "") or "") for qid in written_qids},
                question_marks={qid: float(resolved_marks.get(qid, self.job.question_marks.get(qid, 1.0))) for qid in written_qids},
                explicit_selection=explicit_selection,
            )
            if choice_resolution.warnings:
                warnings.extend(choice_resolution.warnings)

            choice_manual_review_qids: set[str] = set(choice_resolution.manual_review_required_ids or [])
            resolved_active_set = {
                normalize_question_id(qid)
                for qid in list(choice_resolution.active_question_ids or [])
                if normalize_question_id(qid) in written_qids
            }
            resolved_skipped_set = {
                normalize_question_id(qid)
                for qid in list(choice_resolution.skipped_question_ids or [])
                if normalize_question_id(qid) in written_qids
            }

            if choice_structure.groups and resolved_active_set:
                active_written_qids = [qid for qid in written_qids if qid in resolved_active_set]
                skipped_optional_qids = [qid for qid in written_qids if qid in resolved_skipped_set]
            else:
                optional_choice_candidates = [
                    qid
                    for qid in written_qids
                    if _is_optional_choice_question(
                        self.job.question_texts.get(qid, ""),
                        subject_code=self.job.subject_code,
                        paper_num=self.job.paper_num,
                    )
                ]
                attempted_optional = [qid for qid in optional_choice_candidates if bool(text_user_answers.get(qid, "").strip())]
                skipped_optional_qids: List[str] = []
                if len(optional_choice_candidates) >= 2 and attempted_optional:
                    skipped_optional_qids = [qid for qid in optional_choice_candidates if not bool(text_user_answers.get(qid, "").strip())]
                active_written_qids = [qid for qid in written_qids if qid not in skipped_optional_qids]
                choice_manual_review_qids = set()

            written_manual_review_results: Dict[str, Dict[str, Any]] = {}
            gradable_written_qids: List[str] = []
            written_user_answers = {}
            for qid in active_written_qids:
                expected = dict(expanded_key.get(qid, {}) or {})
                written_question_texts[qid] = self.job.question_texts.get(qid, "")
                q_marks = float(expected.get("marks", resolved_marks.get(qid, 0.0)) or 0.0)
                mark_scheme_text = str(expected.get("mark_scheme_text", expected.get("answer", "")) or "").strip()
                manual_review_required = bool(expected.get("manual_review_required", False))
                manual_review_reason = str(expected.get("manual_review_reason", "") or "").strip()

                if not expected:
                    manual_review_required = True
                    manual_review_reason = "No resolved leaf grading specification was available."
                elif not mark_scheme_text or mark_scheme_text == "[See Mark Scheme]":
                    manual_review_required = True
                    manual_review_reason = manual_review_reason or "Exact leaf mark-scheme text could not be extracted safely."
                elif q_marks <= 0:
                    manual_review_required = True
                    manual_review_reason = manual_review_reason or "Exact leaf maximum marks could not be sourced safely."

                if manual_review_required:
                    written_manual_review_results[qid] = {
                        "question_id": qid,
                        "question_text": written_question_texts[qid],
                        "student_answer": text_user_answers.get(qid, ""),
                        "correct_answer": expected.get("answer", "[Manual Review Required]"),
                        "mark_scheme_text": mark_scheme_text or "[See Mark Scheme]",
                        "is_correct": False,
                        "awarded_marks": 0.0,
                        "max_marks": q_marks,
                        "earned_marks": 0.0,
                        "total_marks": q_marks,
                        "explanation": manual_review_reason or "Manual review required.",
                        "feedback": manual_review_reason or "Manual review required.",
                        "warnings": ["manual_review_required", "unresolved_leaf_spec"],
                        "grading_source": "manual_review_unresolved_leaf",
                        "grading_source_detail": "manual_review_unresolved_leaf",
                        "grading_source_label": "Manual review",
                        "ai_error": "",
                        "model_used": "",
                        "model_fallback_used": False,
                        "strict_ai_required": False,
                        "manual_review_required": True,
                        "manual_review_reason": manual_review_reason or "Exact leaf grading data unavailable.",
                        "manual_review_status": "required",
                        "raw_response": "",
                        "parse_status": "manual_review_unresolved_leaf",
                        "max_marks_source": str(expected.get("max_marks_source", "unresolved") or "unresolved"),
                        "mark_scheme_source": str(expected.get("mark_scheme_source", "unresolved") or "unresolved"),
                        "mapping_strategy": str(expected.get("mapping_strategy", "") or ""),
                        "fallback_used": True,
                    }
                    continue

                gradable_written_qids.append(qid)
                written_user_answers[qid] = text_user_answers.get(qid, "")
                written_answer_key[qid] = expected

            for qid in text_qids[:8]:
                _dbg(
                    f"[DBG-WORKER-ANS] qid={qid} payload={normalized_payloads.get(qid)} "
                    f"text_user={repr(text_user_answers.get(qid, ''))}"
                )

            if written_answer_key:
                written_results = check_math_paper_answer(
                    user_answers=written_user_answers,
                    answer_key=written_answer_key,
                    use_ai=self.job.use_ai,
                    subject_code=self.job.subject_code,
                    paper_number=str(self.job.paper_num),
                    year=str(self.job.year),
                    question_texts=written_question_texts,
                    ai_options=self.job.ai_options,
                    progress_callback=_ai_progress,
                    cancel_check=self._cancel_check,
                )
            else:
                written_results = {
                    "total_questions": 0,
                    "correct_count": 0,
                    "total_marks": 0.0,
                    "earned_marks": 0.0,
                    "percentage": 0.0,
                    "question_results": {},
                    "grading_errors": [],
                    "ai_used": False,
                    "ai_applied_count": 0,
                    "baseline_fallback_count": 0,
                    "ai_failed_count": 0,
                    "ai_quota_exhausted": False,
                }

            def _norm_option(value: str) -> str:
                val = (value or "").strip().upper()
                if not val:
                    return ""
                m = re.search(r"\b([A-D])\b", val)
                if m:
                    return m.group(1)
                if val and val[0] in "ABCD":
                    return val[0]
                return val

            objective_question_results: Dict[str, Dict[str, Any]] = {}
            objective_total_marks = 0.0
            objective_earned_marks = 0.0
            for qid in objective_qids:
                expected = expanded_key.get(qid, {})
                q_marks = float(expected.get("marks", resolved_marks.get(qid, 1.0)))
                objective_total_marks += q_marks
                student_raw = text_user_answers.get(qid, "")
                student_opt = _norm_option(student_raw)
                correct_raw = str(expected.get("answer", "") or "")
                correct_opt = _norm_option(correct_raw)
                is_correct = bool(student_opt) and bool(correct_opt) and student_opt == correct_opt
                earned = q_marks if is_correct else 0.0
                objective_earned_marks += earned
                objective_question_results[qid] = {
                    "student_answer": student_raw,
                    "correct_answer": correct_raw,
                    "mark_scheme_text": str(expected.get("mark_scheme_text", correct_raw) or ""),
                    "is_correct": is_correct,
                    "total_marks": q_marks,
                    "earned_marks": earned,
                    "feedback": "Objective item graded by exact option match.",
                    "warnings": [],
                    "grading_source": "objective_exact",
                    "ai_error": "",
                    "model_used": "",
                    "model_fallback_used": False,
                    "strict_ai_required": False,
                    "manual_review_required": False,
                    "manual_review_status": "",
                }

            combined_question_results = dict(written_results.get("question_results", {}))
            combined_question_results.update(written_manual_review_results)
            combined_question_results.update(objective_question_results)

            for qid in skipped_optional_qids:
                manual_choice_review = qid in choice_manual_review_qids
                skip_warnings = ["optional_unselected"]
                if manual_choice_review:
                    skip_warnings.append("choice_over_selection_manual_review")
                combined_question_results[qid] = {
                    "student_answer": "",
                    "correct_answer": "[Optional choice not selected]",
                    "mark_scheme_text": "",
                    "is_correct": False,
                    "total_marks": 0.0,
                    "earned_marks": 0.0,
                    "feedback": "Optional choice not selected; excluded from scoring.",
                    "warnings": skip_warnings,
                    "optional_unselected": True,
                    "grading_source": "optional_skipped",
                    "ai_error": "",
                    "model_used": "",
                    "model_fallback_used": False,
                    "strict_ai_required": False,
                    "manual_review_required": manual_choice_review,
                    "manual_review_status": "choice_over_selection" if manual_choice_review else "",
                }

            pending_manual_marks = 0.0
            from Core.download_service import temp_directory
            scratch_dir = temp_directory()
            for qid in drawing_qids:
                payload = normalized_payloads.get(qid, {})
                image_path = str(payload.get("image_path", "") or "").strip()
                notes = str(payload.get("notes", "") or "").strip()
                q_marks = float(expanded_key.get(qid, {}).get("marks", resolved_marks.get(qid, 1.0)))
                mark_scheme_text = str(
                    expanded_key.get(qid, {}).get(
                        "mark_scheme_text",
                        expanded_key.get(qid, {}).get("answer", ""),
                    )
                    or ""
                )

                drawing_result: Dict[str, Any] = {}
                desktop_temp_path = ""
                if self.job.use_ai and image_path and os.path.exists(image_path):
                    safe_qid = re.sub(r"[^A-Za-z0-9]+", "_", str(qid))
                    handle = tempfile.NamedTemporaryFile(dir=scratch_dir, prefix=f"ppf_drawing_grade_{safe_qid}_", suffix=".png", delete=False)
                    desktop_temp_path = handle.name
                    handle.close()
                    try:
                        shutil.copy2(image_path, desktop_temp_path)
                        drawing_result = grade_drawing_question(
                            question_id=qid,
                            question_text=self.job.question_texts.get(qid, ""),
                            mark_scheme_text=mark_scheme_text,
                            image_path=desktop_temp_path,
                            max_marks=q_marks,
                            student_notes=notes,
                            subject=self.job.subject_code,
                            paper_type=str(self.job.paper_num),
                        )
                    except Exception as exc:
                        drawing_result = {
                            "manual_review_required": True,
                            "status": "grading_failed_pending_review",
                            "marks": 0.0,
                            "feedback": f"Drawing grading failed; manual review or a retry is required: {exc}",
                            "error": str(exc),
                            "raw_response": "",
                            "parse_status": "fallback_zero",
                            "model": "",
                        }
                    finally:
                        if desktop_temp_path:
                            try:
                                os.remove(desktop_temp_path)
                            except Exception:
                                pass
                else:
                    drawing_result = {
                        "manual_review_required": True,
                        "status": "pending_manual_review" if image_path else "missing_drawing",
                        "marks": 0.0,
                        "feedback": (
                            "Drawing submitted; manual review is required while AI grading is unavailable."
                            if image_path
                            else "Drawing image is missing."
                        ),
                        "error": "" if image_path else "",
                        "raw_response": "",
                        "parse_status": "fallback_zero",
                        "model": "",
                    }

                if drawing_result.get("error") or "fallback" in str(drawing_result.get("status", "")):
                    drawing_result["manual_review_required"] = True
                    drawing_result["status"] = "grading_failed_pending_review"
                manual_review_required = bool(drawing_result.get("manual_review_required", True))
                earned_marks = float(drawing_result.get("marks", 0.0) or 0.0)
                if manual_review_required:
                    pending_manual_marks += q_marks

                status = str(drawing_result.get("status", "drawing_submitted_pending_review") or "drawing_submitted_pending_review")
                ai_error = str(drawing_result.get("error", "") or "")
                row_warnings: List[str] = []
                if manual_review_required:
                    row_warnings.append("manual_review_required")
                if ai_error:
                    row_warnings.append("drawing_ai_error")
                combined_question_results[qid] = {
                    "student_answer": notes or ("[Drawing submitted]" if image_path else ""),
                    "correct_answer": expanded_key.get(qid, {}).get("answer", "[Manual Review Required]"),
                    "mark_scheme_text": mark_scheme_text,
                    "is_correct": (not manual_review_required) and earned_marks > 0.0,
                    "total_marks": q_marks,
                    "earned_marks": max(0.0, min(q_marks, earned_marks)),
                    "feedback": str(drawing_result.get("feedback", "Drawing/diagram response auto-graded.") or ""),
                    "warnings": row_warnings,
                    "grading_source": "manual_drawing" if manual_review_required else "ai_drawing",
                    "ai_error": ai_error,
                    "manual_review_required": manual_review_required,
                    "manual_review_status": status,
                    "drawing_path": image_path,
                    "notes": notes,
                    "model_used": str(drawing_result.get("model", "") or ""),
                    "model_fallback_used": False,
                    "strict_ai_required": False,
                    "raw_response": str(drawing_result.get("raw_response", "") or ""),
                    "parse_status": str(drawing_result.get("parse_status", "") or ""),
                }

            # For subjective/open-ended prompts with placeholder keys, avoid auto-wrong behavior
            # when no definitive mark scheme entry is available.
            for qid in active_written_qids:
                expected = expanded_key.get(qid, {})
                expected_answer = expected.get("answer", "")
                if not _is_placeholder_answer(expected_answer):
                    continue
                row = dict(combined_question_results.get(qid, {}))
                if (
                    bool(row.get("manual_review_required", False))
                    and str(row.get("grading_source", "") or "") == "manual_review_unresolved_leaf"
                ):
                    combined_question_results[qid] = row
                    continue
                q_marks = float(expected.get("marks", resolved_marks.get(qid, 1.0)))
                row.setdefault("mark_scheme_text", str(expected.get("mark_scheme_text", expected_answer) or ""))
                row.setdefault("model_used", "")
                row.setdefault("model_fallback_used", False)
                row.setdefault("strict_ai_required", False)
                ai_used_here = str(row.get("grading_source", "")).lower() == "ai" and not str(row.get("ai_error", "")).strip()
                if ai_used_here:
                    row["correct_answer"] = "[Rubric-based]"
                    row.setdefault("feedback", "Rubric-based grading applied without fixed mark-scheme string.")
                    combined_question_results[qid] = row
                    continue

                row.update(
                    {
                        "correct_answer": "[Rubric-based / auto fallback]",
                        "feedback": (
                            str(row.get("feedback", "") or "").strip()
                            or "No fixed mark-scheme string; applied automatic fallback grading."
                        ),
                        "warnings": list(dict.fromkeys(list(row.get("warnings", [])) + ["no_fixed_mark_scheme_auto_fallback"])),
                        "manual_review_required": False,
                        "manual_review_status": "",
                        "grading_source": str(row.get("grading_source", "") or "") or "baseline_no_fixed_scheme",
                    }
                )
                combined_question_results[qid] = row

            for qid, row in list(combined_question_results.items()):
                expected = expanded_key.get(qid, {})
                question_text = str(self.job.question_texts.get(qid, "") or "")
                max_marks = float(
                    row.get(
                        "max_marks",
                        row.get("total_marks", expected.get("marks", resolved_marks.get(qid, 0.0))),
                    )
                    or 0.0
                )
                awarded_marks = float(row.get("awarded_marks", row.get("earned_marks", 0.0)) or 0.0)
                if max_marks > 0:
                    awarded_marks = max(0.0, min(max_marks, awarded_marks))
                else:
                    awarded_marks = max(0.0, awarded_marks)
                explanation = str(row.get("explanation", row.get("feedback", "")) or "")
                manual_review_reason = str(
                    row.get("manual_review_reason", expected.get("manual_review_reason", ""))
                    or ""
                ).strip()
                row.setdefault(
                    "mark_scheme_text",
                    str(expected.get("mark_scheme_text", expected.get("answer", row.get("correct_answer", ""))) or ""),
                )
                row.setdefault("model_used", "")
                row.setdefault("model_fallback_used", False)
                row.setdefault("strict_ai_required", False)
                row.setdefault("manual_review_required", False)
                row.setdefault("manual_review_status", "")
                row.setdefault("ai_error", "")
                row.setdefault("grading_source", "baseline")
                row.setdefault("warnings", [])
                row.setdefault("raw_response", "")
                row.setdefault("parse_status", "")
                row["question_id"] = qid
                row["question_text"] = question_text
                row["awarded_marks"] = awarded_marks
                row["max_marks"] = max_marks
                row["earned_marks"] = awarded_marks
                row["total_marks"] = max_marks
                row["explanation"] = explanation
                row["feedback"] = explanation
                row["max_marks_source"] = str(
                    row.get(
                        "max_marks_source",
                        expected.get(
                            "max_marks_source",
                            "question_paper_hint" if qid in self.job.question_mark_hints else "unresolved",
                        ),
                    )
                    or "unresolved"
                )
                row["mark_scheme_source"] = str(
                    row.get("mark_scheme_source", expected.get("mark_scheme_source", "unresolved")) or "unresolved"
                )
                row["mapping_strategy"] = str(
                    row.get("mapping_strategy", expected.get("mapping_strategy", expected.get("mapping_source", "")))
                    or ""
                )
                row["fallback_used"] = bool(
                    row.get(
                        "fallback_used",
                        expected.get("fallback_used", False)
                        or bool(row.get("manual_review_required", False))
                        or str(row.get("grading_source", "")).startswith("baseline"),
                    )
                )
                row["manual_review_reason"] = manual_review_reason
                if _GRADING_DEBUG:
                    _dbg(
                        "[DBG-LEAF] "
                        f"qid={qid} "
                        f"question={question_text[:90]!r} "
                        f"mark_scheme={str(row.get('mark_scheme_text', '') or '')[:90]!r} "
                        f"official_max={row['max_marks']!r} "
                        f"max_source={row['max_marks_source']} "
                        f"awarded={row['awarded_marks']!r} "
                        f"displayed={row['awarded_marks']!r}/{row['max_marks']!r} "
                        f"mapping={row['mapping_strategy']!r} "
                        f"fallback={row['fallback_used']!r} "
                        f"manual_review={row['manual_review_required']!r}"
                    )
                combined_question_results[qid] = row

            # Final consistency guard: enforce official total across score-bearing rows.
            if official_value > 0 and official_is_authoritative:
                scoring_totals = {
                    qid: float(row.get("total_marks", 0.0) or 0.0)
                    for qid, row in combined_question_results.items()
                    if not bool(row.get("optional_unselected", False))
                }
                scoring_sum = float(sum(scoring_totals.values()))
                if scoring_totals and abs(scoring_sum - official_value) > 0.01:
                    message = (
                        f"Resolved per-question max marks differ from official total "
                        f"({scoring_sum:.2f}/{official_value:.2f}); kept leaf max marks unchanged."
                    )
                    warnings.append(message)
                    final_total_guard_messages.append(message)

            # Recompute split totals from merged per-question rows so manual-review items
            # (drawing or no-fixed-mark-scheme) are not counted as auto-graded.
            manual_pending_count = sum(
                1
                for _qid, row in combined_question_results.items()
                if bool(row.get("manual_review_required", False))
            )
            pending_manual_marks = sum(
                float(row.get("total_marks", 0.0) or 0.0)
                for row in combined_question_results.values()
                if bool(row.get("manual_review_required", False))
            )
            auto_graded_marks = sum(
                float(row.get("earned_marks", 0.0) or 0.0)
                for row in combined_question_results.values()
                if not bool(row.get("manual_review_required", False))
            )
            auto_graded_total_marks = sum(
                float(row.get("total_marks", 0.0) or 0.0)
                for row in combined_question_results.values()
                if not bool(row.get("manual_review_required", False))
            )
            final_confirmed_marks = auto_graded_marks
            paper_total_marks = auto_graded_total_marks + pending_manual_marks
            percentage = (auto_graded_marks / auto_graded_total_marks * 100.0) if auto_graded_total_marks > 0 else 0.0

            results = dict(written_results)
            results["mode"] = self.job.paper_mode
            results["total_questions"] = len(self.job.question_ids)
            results["question_results"] = combined_question_results
            results["earned_marks"] = auto_graded_marks
            results["total_marks"] = paper_total_marks
            results["percentage"] = percentage
            results["auto_graded_marks"] = auto_graded_marks
            results["auto_graded_total_marks"] = auto_graded_total_marks
            results["pending_manual_marks"] = pending_manual_marks
            results["final_confirmed_marks"] = final_confirmed_marks
            results["pending_manual_count"] = manual_pending_count
            results["grading_errors"] = list(results.get("grading_errors", []))
            if final_total_guard_messages:
                results["grading_errors"].extend(final_total_guard_messages)
            drawing_qid_set = set(drawing_qids)
            drawing_manual_count = sum(
                1
                for qid in drawing_qids
                if bool(combined_question_results.get(qid, {}).get("manual_review_required", False))
            )
            if drawing_manual_count:
                results["grading_errors"].append(
                    f"{drawing_manual_count} drawing question(s) require manual review."
                )
            non_drawing_manual = sum(
                1
                for qid, row in combined_question_results.items()
                if qid not in drawing_qid_set and bool(row.get("manual_review_required", False))
            )
            if non_drawing_manual:
                results["grading_errors"].append(
                    f"{non_drawing_manual} text question(s) require rubric/manual review (no fixed mark scheme)."
                )
            if skipped_optional_qids:
                results["grading_errors"].append(
                    f"{len(skipped_optional_qids)} optional choice question(s) were unselected and excluded from scoring."
                )

            base_correct_count = sum(1 for qid in active_written_qids if bool(combined_question_results.get(qid, {}).get("is_correct")))
            objective_correct_count = sum(1 for qid in objective_qids if bool(combined_question_results.get(qid, {}).get("is_correct")))
            results["correct_count"] = base_correct_count + objective_correct_count

            threshold_interpretation = interpret_grade_thresholds(
                subject_code=self.job.subject_code,
                year=self.job.year,
                series=self.job.series,
                component=self.job.component_code or str(self.job.paper_num),
                candidate_score=float(results.get("final_confirmed_marks", results.get("earned_marks", 0.0)) or 0.0),
                total_mark=float(results.get("total_marks", 0.0) or 0.0),
                grade_threshold_url=self.job.grade_threshold_url,
                question_url=self.job.question_url or self.job.pdf_url or "",
                mark_scheme_url=self.job.mark_scheme_url or "",
                past_paper_code=self._resolve_past_paper_code(),
            )
            if isinstance(threshold_interpretation, dict):
                threshold_interpretation["provisional"] = bool(manual_pending_count > 0)
            results["threshold_interpretation"] = threshold_interpretation

            results.setdefault("grading_report_path", "")
            try:
                from Core.runtime_paths import user_data_path
                report_output_dir = user_data_path("reports")
                report_path = write_grading_report(
                    project_root=str(report_output_dir),
                    subject_code=self.job.subject_code,
                    subject_name=self.job.subject_name,
                    paper_number=str(self.job.paper_num),
                    year=str(self.job.year),
                    past_paper_code=self._resolve_past_paper_code(),
                    results=results,
                    source_label=source_label,
                )
                results["grading_report_path"] = report_path
            except Exception as exc:
                results["grading_report_path"] = ""
                report_error = f"Could not prepare grading report payload: {exc}"
                results["grading_errors"].append(report_error)
                warnings.append(report_error)
            results["grading_report_export_ready"] = True

            if self._cancel_check():
                self.cancelled_payload.emit(
                    GradingJobResult(
                        results=results,
                        mapping_report=mapping_report,
                        expanded_key=expanded_key,
                        resolved_marks=resolved_marks,
                        source_label=source_label,
                        warnings=warnings + ["Grading cancelled. Partial results may be shown."],
                        cancelled=True,
                        auto_graded_marks=float(results.get("auto_graded_marks", 0.0)),
                        auto_graded_total_marks=float(results.get("auto_graded_total_marks", 0.0)),
                        pending_manual_marks=float(results.get("pending_manual_marks", 0.0)),
                        final_confirmed_marks=float(results.get("final_confirmed_marks", 0.0)),
                        pending_manual_count=int(results.get("pending_manual_count", 0)),
                    )
                )
                return

            self.progress.emit("Finalizing results...", 0.98)
            self.finished_payload.emit(
                GradingJobResult(
                    results=results,
                    mapping_report=mapping_report,
                    expanded_key=expanded_key,
                    resolved_marks=resolved_marks,
                    source_label=source_label,
                    warnings=warnings,
                    cancelled=False,
                    auto_graded_marks=float(results.get("auto_graded_marks", 0.0)),
                    auto_graded_total_marks=float(results.get("auto_graded_total_marks", 0.0)),
                    pending_manual_marks=float(results.get("pending_manual_marks", 0.0)),
                    final_confirmed_marks=float(results.get("final_confirmed_marks", 0.0)),
                    pending_manual_count=int(results.get("pending_manual_count", 0)),
                )
            )
        except Exception as e:
            self.failed.emit(str(e), traceback.format_exc())

    def _build_mark_scheme_candidate_urls(self) -> List[str]:
        if not self.job.pdf_url:
            return []

        candidates = [
            self.job.pdf_url.replace("_qp_", "_ms_"),
            self.job.pdf_url.replace("_QP_", "_MS_"),
            self.job.pdf_url.replace("_qp", "_ms"),
            self.job.pdf_url.replace("_QP", "_MS"),
            self.job.pdf_url.replace("/qp/", "/ms/"),
            self.job.pdf_url.replace("/QP/", "/MS/"),
        ]
        deduped: List[str] = []
        seen = set()
        for url in candidates:
            if url and url not in seen:
                deduped.append(url)
                seen.add(url)
        return deduped

    def _download_mark_scheme_candidate(self) -> Optional[str]:
        for ms_url in self._build_mark_scheme_candidate_urls():
            if self._cancel_check():
                return None
            try:
                return download_pdf(ms_url, cancel=self._cancel_event)
            except InterruptedError:
                return None
            except Exception:
                continue
        return None

    def _load_candidate_answer_key(self) -> Tuple[Dict[str, Dict[str, Any]], str]:
        parser = MarkSchemeParser()
        mark_scheme_path = self.job.mark_scheme_path
        question_marks = _question_mark_lookup(
            getattr(self.job, "question_marks", {}),
            getattr(self.job, "question_mark_hints", {}),
        )

        if (not mark_scheme_path or not os.path.exists(mark_scheme_path)) and self.job.pdf_url:
            mark_scheme_path = self._download_mark_scheme_candidate()

        if mark_scheme_path and os.path.exists(mark_scheme_path):
            if is_math_subject_code(self.job.subject_code, self.job.subject_name):
                math_key = extract_math_mark_scheme(
                    mark_scheme_path,
                    expected_question_ids=list(self.job.question_ids or []),
                )
                if math_key:
                    return math_key, "math mark scheme extractor"
            ms_text = parser.extract_text_from_pdf(mark_scheme_path)
            written_key = parser.parse_written_mark_scheme(
                ms_text,
                expected_question_ids=list(self.job.question_ids or []),
            )
            written_key = _apply_question_paper_mark_validation(written_key, question_marks)
            if written_key:
                return written_key, "loaded/downloaded mark scheme"

        built_in = get_answer_key(self.job.subject_code, self.job.paper_num, self.job.year)
        if built_in:
            normalized = {normalize_question_id(k): dict(v) for k, v in built_in.items()}
            is_generated = normalized and all(bool(v.get("is_generated")) for v in normalized.values())
            source_label = "generated fallback key" if is_generated else "built-in key"
            return normalized, source_label

        generated = {
            q: {"answer": "[See Mark Scheme]", "marks": self.job.question_marks.get(q, 1.0)}
            for q in self.job.question_ids
        }
        return generated, "synthetic fallback key"

    def _resolve_past_paper_code(self) -> str:
        direct = str(getattr(self.job, "past_paper_code", "") or "").strip()
        if direct:
            return direct

        parsed = extract_paper_code(str(self.job.pdf_url or ""))
        if parsed:
            subject = str(parsed.get("subject", "")).strip()
            year_code = str(parsed.get("year_code", "")).strip().lower()
            paper = str(parsed.get("paper", "")).strip()
            if subject and year_code and paper:
                return f"{subject}_{year_code}_qp_{paper}"

        paper = str(self.job.paper_num or "").strip()
        if paper.isdigit() and len(paper) == 1:
            paper = f"{paper}0"
        year = str(self.job.year or "").strip()
        return f"{self.job.subject_code}_{year}_qp_{paper or self.job.paper_num}"


# ---------------------------------------------------------------------------
# Grading Results
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ManualGradeRow:
    qid: str
    display_id: str
    answer_text: str
    mark_scheme_text: str
    max_marks_int: int


class ManualGradingPanel(QWidget):
    """Manual grading pane with read-only answer text and per-row mark entry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[ManualGradeRow] = []
        self.mark_inputs: Dict[str, QLineEdit] = {}
        self._input_invalid_qids: set[str] = set()
        self._finalize_callback: Optional[Callable[[], None]] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        heading = QLabel("Manual Grading")
        heading.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        root.addWidget(heading)

        subtitle = QLabel("Review each answer and enter whole-number marks for every visible question.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {_muted_text_for_bg(Colors.BG_LIGHT)};")
        root.addWidget(subtitle)

        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(4, 4, 4, 4)
        self.rows_layout.setSpacing(10)
        self.rows_scroll.setWidget(self.rows_host)
        root.addWidget(self.rows_scroll, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.finalize_btn = QPushButton("Finalize")
        self.finalize_btn.clicked.connect(self._emit_finalize)
        actions.addWidget(self.finalize_btn)
        root.addLayout(actions)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setVisible(False)
        root.addWidget(self.summary_label)

    @staticmethod
    def _base_mark_input_style() -> str:
        bg = _input_surface_bg()
        text_color = _contrast_text_for_bg(bg)
        focus_color = _input_focus_glow_color()
        focus_bg = _mix_hex(bg, focus_color, 0.05)
        return (
            f"QLineEdit {{ background-color: {bg}; color: {text_color}; "
            f"border: 1px solid {_input_border_color()}; padding: 6px; }}"
            f"QLineEdit:focus {{ border: 1px solid {focus_color}; background-color: {focus_bg}; }}"
        )

    @staticmethod
    def _invalid_mark_input_style() -> str:
        text_color = _contrast_text_for_bg(Colors.BG_LIGHT)
        return (
            f"QLineEdit {{ background-color: {Colors.BG_LIGHT}; color: {text_color}; "
            "border: 2px solid #EF4444; padding: 6px; }}"
        )

    def set_finalize_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._finalize_callback = callback

    def _emit_finalize(self) -> None:
        if self._finalize_callback:
            self._finalize_callback()

    def content_viewport(self) -> Optional[QWidget]:
        if self.rows_scroll:
            return self.rows_scroll.viewport()
        return None

    def _clear_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def set_rows(self, rows: List[ManualGradeRow]) -> None:
        self.rows = list(rows or [])
        self.mark_inputs = {}
        self._input_invalid_qids = set()
        self.summary_label.clear()
        self.summary_label.setVisible(False)
        self.finalize_btn.setEnabled(bool(self.rows))
        self.finalize_btn.setText("Finalize")
        self._clear_rows()
        muted_host_text = _muted_text_for_bg(Colors.BG_LIGHT)
        card_text = _contrast_text_for_bg(Colors.BG_CARD)
        muted_card_text = _mix_hex(card_text, Colors.BG_CARD, 0.45)

        if not self.rows:
            placeholder = QLabel("No visible questions available for manual grading.")
            placeholder.setWordWrap(True)
            placeholder.setStyleSheet(f"color: {muted_host_text}; padding: 8px;")
            self.rows_layout.addWidget(placeholder)
            self.rows_layout.addStretch(1)
            return

        for row in self.rows:
            card = QFrame()
            card.setObjectName("manualGradingCard")
            card.setStyleSheet(
                f"QFrame#manualGradingCard {{ background-color: {Colors.BG_CARD}; border: 1px solid {Colors.BG_DARK}; border-radius: 8px; }}"
            )
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(12)

            left = QWidget()
            left_layout = QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(6)

            q_label = QLabel(f"Q{row.display_id}")
            q_label.setStyleSheet(f"color: {card_text}; font-weight: bold;")
            left_layout.addWidget(q_label)

            answer_title = QLabel("Student Answer")
            answer_title.setStyleSheet(f"color: {muted_card_text}; font-size: 12px;")
            left_layout.addWidget(answer_title)
            answer_view = QTextBrowser()
            answer_view.setReadOnly(True)
            answer_view.setOpenExternalLinks(False)
            answer_view.setPlainText(str(row.answer_text or "(No answer provided)"))
            answer_view.setMinimumHeight(72)
            answer_view.setMaximumHeight(150)
            left_layout.addWidget(answer_view)

            ms_title = QLabel("Mark Scheme")
            ms_title.setStyleSheet(f"color: {muted_card_text}; font-size: 12px;")
            left_layout.addWidget(ms_title)
            ms_view = QTextBrowser()
            ms_view.setReadOnly(True)
            ms_view.setOpenExternalLinks(False)
            ms_view.setPlainText(str(row.mark_scheme_text or "No mark scheme text available"))
            ms_view.setMinimumHeight(72)
            ms_view.setMaximumHeight(150)
            left_layout.addWidget(ms_view)

            right = QWidget()
            right_layout = QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(6)
            right_layout.addStretch(1)

            mark_label = QLabel("Awarded")
            mark_label.setStyleSheet(f"color: {muted_card_text};")
            right_layout.addWidget(mark_label, 0, Qt.AlignmentFlag.AlignRight)

            mark_row = QHBoxLayout()
            mark_row.setContentsMargins(0, 0, 0, 0)
            mark_row.setSpacing(6)
            entry = QLineEdit()
            entry.setObjectName(f"manualMarkInput_{row.qid}")
            entry.setPlaceholderText("0")
            entry.setFixedWidth(72)
            entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
            entry.setStyleSheet(self._base_mark_input_style())
            entry.textChanged.connect(lambda _text, qid=row.qid: self.set_mark_input_invalid(qid, False))
            self.mark_inputs[row.qid] = entry
            max_label = QLabel(f"/{int(row.max_marks_int)}")
            max_label.setStyleSheet(f"color: {card_text}; font-weight: bold;")
            mark_row.addWidget(entry)
            mark_row.addWidget(max_label)
            right_layout.addLayout(mark_row)
            right_layout.addStretch(1)

            card_layout.addWidget(left, 1)
            card_layout.addWidget(right, 0)
            self.rows_layout.addWidget(card)

        self.rows_layout.addStretch(1)

    def mark_input_text(self, qid: str) -> str:
        entry = self.mark_inputs.get(str(qid))
        if not entry:
            return ""
        return str(entry.text() or "").strip()

    def set_mark_input_invalid(self, qid: str, invalid: bool) -> None:
        key = str(qid or "")
        entry = self.mark_inputs.get(key)
        if not entry:
            return
        if invalid:
            self._input_invalid_qids.add(key)
            entry.setStyleSheet(self._invalid_mark_input_style())
            return
        self._input_invalid_qids.discard(key)
        entry.setStyleSheet(self._base_mark_input_style())

    def set_inputs_enabled(self, enabled: bool) -> None:
        for entry in self.mark_inputs.values():
            entry.setEnabled(bool(enabled))

    def set_finalize_enabled(self, enabled: bool) -> None:
        self.finalize_btn.setEnabled(bool(enabled))

    def show_summary(self, summary: str) -> None:
        self.summary_label.setText(str(summary or ""))
        summary_text = _contrast_text_for_bg(Colors.BG_LIGHT)
        self.summary_label.setStyleSheet(
            f"color: {summary_text}; border: 1px solid {Colors.BG_DARK}; border-radius: 8px; padding: 8px;"
        )
        self.summary_label.setVisible(True)

    def apply_runtime_theme(self) -> None:
        for qid, entry in self.mark_inputs.items():
            if qid in self._input_invalid_qids:
                entry.setStyleSheet(self._invalid_mark_input_style())
            else:
                entry.setStyleSheet(self._base_mark_input_style())
        if self.summary_label and self.summary_label.isVisible():
            summary_text = _contrast_text_for_bg(Colors.BG_LIGHT)
            self.summary_label.setStyleSheet(
                f"color: {summary_text}; border: 1px solid {Colors.BG_DARK}; border-radius: 8px; padding: 8px;"
            )


class GradingResultsPanel(QFrame):
    """Inline grading results panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)

        self.title = QLabel("Grading Results")
        self.title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(self.title)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

    def update_summary(self, text: str):
        self.summary.setText(text)

class PeriodicLookupWorker(QThread):
    """Background periodic-table page lookup."""

    finished_lookup = Signal(str, object, str)

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self):
        try:
            page = find_periodic_table_page(self.pdf_path, cancel_check=self.isInterruptionRequested)
            self.finished_lookup.emit(self.pdf_path, page, "")
        except Exception as exc:
            self.finished_lookup.emit(self.pdf_path, None, str(exc))


class MarkSchemeDownloadWorker(QThread):
    """Background downloader for explicit mark-scheme downloads."""

    progress = Signal(str)
    finished_download = Signal(str, object, str, bool)

    def __init__(self, urls: List[str]):
        super().__init__()
        self.urls = [str(u) for u in urls if str(u).strip()]
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self):
        last_error = "No mark-scheme URL candidates available."
        for ms_url in self.urls:
            if self._cancel.is_set():
                break
            try:
                self.progress.emit(f"Trying mark scheme from {urlparse(ms_url).netloc or 'source'}...")
                content = fetch_bytes(ms_url, cancel=self._cancel)
                if self._cancel.is_set():
                    break
                self.finished_download.emit(ms_url, content, "", False)
                return
            except InterruptedError:
                break
            except Exception as exc:
                last_error = str(exc)
        cancelled = self._cancel.is_set()
        self.finished_download.emit("", None, "Download cancelled." if cancelled else last_error, cancelled)


# ---------------------------------------------------------------------------
# Exam Mode Window
# ---------------------------------------------------------------------------

class ExamModeWindow(QMainWindow):
    def __init__(
        self,
        parent,
        subject_code,
        subject_name,
        paper_num,
        year,
        series: Optional[str] = None,
        pdf_url=None,
        resume_snapshot: Optional[Dict[str, Any]] = None,
        paper_resources: Optional[Dict[str, Dict[str, str]]] = None,
        manual_grading_only: bool = False,
        manual_grading_only_reason: str = "",
        session_mode: str = "exam",
    ):
        # A true top-level workspace must not inherit native visibility/state
        # from the main window that it hides.
        super().__init__(None)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        from UI.workspace_lifecycle import ExamWorkspaceLifecycle
        self._workspace_lifecycle = ExamWorkspaceLifecycle(self, parent)

        self.subject_code = str(subject_code)
        self.subject_name = subject_name
        self.paper_number_raw = str(paper_num).strip()
        try:
            self.paper_num = int(self.paper_number_raw[0])
        except Exception:
            self.paper_num = 1
        self.year = year
        self.series = str(series or "").strip().upper()
        self.exam_year = infer_exam_year(str(year), fallback_year=2026)
        self.pdf_url = pdf_url
        self.paper_resources: Dict[str, Dict[str, str]] = {
            str(k): dict(v)
            for k, v in (paper_resources or {}).items()
            if isinstance(v, dict)
        }
        self.resume_snapshot = dict(resume_snapshot or {})
        self.session_state = ExamSessionState.restore(self.resume_snapshot, session_mode)
        from Core.study_history import session_id
        import uuid
        self._study_attempt_id = session_id(self.resume_snapshot) if self.resume_snapshot else uuid.uuid4().hex
        self._study_started_at = str(self.resume_snapshot.get('first_saved_at') or
            self.resume_snapshot.get('saved_at') or datetime.now().isoformat(timespec='seconds'))
        self._study_started_recorded = False
        self._studio_workspace = None
        self._is_dev_test_attempt = bool(self.resume_snapshot.get("dev_test_entry"))
        self.manual_grading_only = bool(manual_grading_only)
        self.manual_grading_only_reason = str(manual_grading_only_reason or "").strip()
        if str(self.resume_snapshot.get("attempt_key", "")).strip():
            self._attempt_key = str(self.resume_snapshot.get("attempt_key", "")).strip()
        else:
            self._attempt_key = ExamAttemptManager.build_attempt_key(
                str(subject_code),
                str(self.paper_number_raw or self.paper_num),
                str(year),
                str(pdf_url or ""),
            ) + '-' + self._study_attempt_id[:12]
        self.paper_mode_decision: PaperModeDecision = resolve_mode(
            self.subject_code,
            self.paper_number_raw or str(self.paper_num),
            exam_year=self.exam_year,
        )
        self.is_listening = self._infer_listening_paper_flag()
        if self.is_listening and self.paper_mode_decision.mode != "MCQ_ONLY":
            self.paper_mode_decision = replace(
                self.paper_mode_decision,
                mode="MCQ_ONLY",
                gradable=True,
                has_mcq=True,
                has_written=False,
                viewer_only_reason="",
                assessment_type="listening",
            )
        self.paper_mode = self.paper_mode_decision.mode
        try:
            _official_total = float(self.paper_mode_decision.total_marks) if self.paper_mode_decision.total_marks is not None else 0.0
            self.official_total_marks: Optional[float] = _official_total if math.isfinite(_official_total) and _official_total > 0 else None
        except Exception:
            self.official_total_marks = None

        official_duration = self.paper_mode_decision.duration_minutes
        if official_duration and int(official_duration) > 0:
            self.duration = int(official_duration)
        else:
            try:
                self.duration = get_exam_duration(self.subject_code, self.paper_num, self.year)
            except Exception:
                self.duration = 60

        if self.paper_mode in {"WRITTEN_ONLY", "MIXED"}:
            self.paper_type = "Written"
        elif self.paper_mode == "MCQ_ONLY":
            self.paper_type = "MCQ"
        else:
            self.paper_type = self.paper_mode_decision.assessment_type or get_paper_type_from_subject(subject_name, self.subject_code, self.paper_num)

        self.setWindowTitle(f"Exam Mode - {subject_name} Paper {self.paper_num} ({year})")
        self.resize(1400, 900)

        self.navigator = None  # MCQ navigator removed in PySide6 layout

        self.remaining_seconds = max(30, int(self.duration) * 60)
        self.timer_paused = False
        self._timer_expiry_handled = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_timer)
        self._allow_resume_autosave = not self._is_dev_test_attempt
        self._restoring_resume_snapshot = False
        self._autosave_has_user_input = bool(self.resume_snapshot)
        self._autosave_dirty = False
        self._autosave_last_saved_monotonic = time.monotonic()
        self._autosave_error_notified = False
        self._autosave_debounce_interval_ms = 250
        self._autosave_max_staleness_seconds = 60.0

        self.question_texts: Dict[str, str] = {}
        self.question_marks: Dict[str, float] = {}
        self.question_mark_hints: Dict[str, float] = {}
        self.question_ids: List[str] = []
        self.question_items: List[QuestionLeaf] = []
        self.extraction_result = ExtractionResult()
        self.latest_mapping_report: Optional[MappingReport] = None
        self.manual_mapping_overrides: Dict[str, str] = {}
        self.answer_key = None
        self.local_pdf_path: Optional[str] = None
        self._source_local_paths: Dict[str, str] = {}
        self._source_view_states: Dict[str, dict] = {}
        self._source_remote_urls: Dict[str, str] = {}
        self._source_display_labels: Dict[str, str] = {}
        self._available_pdf_sources: List[str] = []
        self._active_pdf_source_key: str = "question"
        self._listening_audio_path: Optional[str] = None
        self._audio_url_probe_cache: Dict[str, bool] = {}
        self._resume_listening_audio_position_ms: int = 0
        self._resume_listening_audio_position_applied: bool = False
        self.mark_scheme_path: Optional[str] = None
        self.drawing_session_dir = tempfile.mkdtemp(prefix="exam_drawings_")
        self.drawing_file_prefix = f"{self.subject_code}_{self.paper_num}_{self.year}"
        self._grading_in_progress = False
        self._submission_locked_for_autograde = False
        self._autograde_submitted_at: Optional[datetime] = None
        self._grading_worker: Optional[GradingWorker] = None
        self._last_grading_payload: Optional[GradingJobResult] = None
        self.navigator = None  # Sidebar navigator removed in PySide6 layout

        self.settings = QSettings("PastPaperFinder", "ExamMode")
        self.exam_splitter: Optional[QSplitter] = None
        self._splitter_settings_key: str = ""
        self._splitter_default_sizes: List[int] = []
        self._answer_panel_position = self._normalize_answer_panel_position(
            ConfigManager.get_exam_answer_panel_position()
        )
        self._exam_splitter_pdf_widget: Optional[QWidget] = None
        self._exam_splitter_answer_widget: Optional[QWidget] = None
        self._tracked_pdf_viewer_ids: set[int] = set()
        self._last_hovered_pdf_viewer: Optional[PDFViewer] = None

        self._calculator_geometry_key = f"{self._layout_prefix()}/calculator_dialog_geometry"
        self.calculator_dialog: Optional[CalculatorDialog] = None
        self.calculator_widget: Optional[ScientificCalculatorWidget] = None
        self.top_bar: Optional[QFrame] = None
        self.top_bar_pill: Optional[QFrame] = None
        self.theme_label: Optional[QLabel] = None
        self.theme_combo: Optional[QComboBox] = None
        self.pause_btn: Optional[QPushButton] = None
        self.end_btn: Optional[QPushButton] = None
        self.reset_layout_btn: Optional[QPushButton] = None
        self.additional_tools_btn: Optional[QPushButton] = None
        self.exam_settings_btn: Optional[QPushButton] = None
        self.additional_tools_menu: Optional[QMenu] = None
        self.additional_tools_calculator_action: Optional[QAction] = None
        self.additional_tools_periodic_action: Optional[QAction] = None
        self.additional_tools_notes_action: Optional[QAction] = None
        self.additional_tools_ruler_action: Optional[QAction] = None
        self.additional_tools_settings_action: Optional[QAction] = None
        self.calculator_toggle_btn: Optional[QPushButton] = None
        self.calculator_icon_btn: Optional[QPushButton] = None
        self.utility_drawer: Optional[QFrame] = None
        self.utility_drawer_calculator_btn: Optional[QPushButton] = None
        self.utility_drawer_notes_btn: Optional[QPushButton] = None
        self.utility_drawer_ruler_btn: Optional[QPushButton] = None
        self.utility_drawer_periodic_btn: Optional[QPushButton] = None
        self._utility_drawer_animation: Optional[QPropertyAnimation] = None
        self._utility_drawer_open = False
        self.notes_dialog: Optional[NotesDialog] = None
        self.notes_widget: Optional[NotesWidget] = None
        self._notes_text_cache: str = ""
        self._notes_geometry_key = f"{self._layout_prefix()}/notes_dialog_geometry"
        self.submit_btn: Optional[QPushButton] = None
        self.grade_btn: Optional[QPushButton] = None
        self.grading_mode_btn: Optional[QPushButton] = None
        self.paper_info_btn: Optional[QPushButton] = None
        self.paper_info_menu: Optional[QMenu] = None
        self.split_global_controls_zone: Optional[QWidget] = None
        self.split_mode_toggle_btn: Optional[QPushButton] = None
        self.split_nav_prev_btn: Optional[QPushButton] = None
        self.split_nav_next_btn: Optional[QPushButton] = None
        self.split_zoom_out_btn: Optional[QPushButton] = None
        self.split_zoom_in_btn: Optional[QPushButton] = None
        self.split_rotate_ccw_btn: Optional[QPushButton] = None
        self.split_rotate_cw_btn: Optional[QPushButton] = None
        self.grading_mode_menu: Optional[QMenu] = None
        self.grading_mode_toggle_action: Optional[QAction] = None
        self.grading_mode_mapping_action: Optional[QAction] = None
        self.grading_mode_cancel_action: Optional[QAction] = None
        self.pdf_source_toggle_btn: Optional[QPushButton] = None
        self.paper_insert_toggle_btn: Optional[QPushButton] = None
        self.insert_split_view_btn: Optional[QPushButton] = None
        self.insert_page_mode_label: Optional[QLabel] = None
        self.insert_page_mode_combo: Optional[QComboBox] = None
        self.pdf_source_selector: Optional[QComboBox] = None
        self._current_pdf_source: str = "question"
        self._pdf_source_switch_allowed = False
        self._movable_ruler_enabled = False
        raw_scale_pref = ConfigManager.get_value("ui.exam_question_scale", True)
        if isinstance(raw_scale_pref, str):
            self._question_scale_visible = raw_scale_pref.strip().lower() not in {"", "0", "false", "no", "off"}
        else:
            self._question_scale_visible = bool(raw_scale_pref)
        self._mark_scheme_view_unlocked = False
        self._grading_mode_enabled = False
        self._insert_split_dialog: Optional[QDialog] = None
        self._insert_split_inline_host: Optional[QWidget] = None
        self._insert_split_inline_splitter: Optional[QSplitter] = None
        self._insert_split_enabled = False
        self._insert_split_question_viewer: Optional[PDFViewer] = None
        self._insert_split_insert_viewer: Optional[PDFViewer] = None
        self._insert_split_left_label: Optional[QLabel] = None
        self._insert_split_right_label: Optional[QLabel] = None
        self._last_question_completion_state: Dict[str, bool] = {}
        self.optional_choice_groups: Dict[str, List[str]] = {}
        self.optional_selection_map: Dict[str, List[str]] = {}
        self.optional_selector_panel: Optional[QWidget] = None
        self.optional_selectors: Dict[str, QComboBox] = {}
        self.question_confidence: Dict[str, str] = {}
        self.question_reviewed: set[str] = set()
        self.focus_mode_enabled: bool = bool(ConfigManager.get_value("ui.exam.focus_mode_enabled", False))

        self.periodic_button: Optional[QPushButton] = None
        self.periodic_icon_btn: Optional[QPushButton] = None
        self._periodic_lookup_worker: Optional[PeriodicLookupWorker] = None
        self._periodic_page_cache: Dict[str, Optional[int]] = {}
        self._periodic_snippets_cache: Dict[str, List[Tuple[int, str]]] = {}
        self.download_ms_btn: Optional[QPushButton] = None
        self.exam_stack: Optional[QStackedWidget] = None
        self.exam_page: Optional[QWidget] = None
        self.submit_review_page: Optional[QWidget] = None
        self.grading_report_page: Optional[QWidget] = None
        self.grading_report_title_label: Optional[QLabel] = None
        self.grading_report_meta_label: Optional[QLabel] = None
        self.grading_report_browser: Optional[QTextBrowser] = None
        self.grading_report_save_btn: Optional[QPushButton] = None
        self.grading_report_exit_btn: Optional[QPushButton] = None
        self._current_grading_report_path: str = ""
        self.submit_review_grid: Optional[QGridLayout] = None
        self.submit_review_grid_container: Optional[QWidget] = None
        self.submit_review_scroll: Optional[QScrollArea] = None
        self.submit_review_subtitle: Optional[QLabel] = None
        self.submit_answered_count_label: Optional[QLabel] = None
        self.submit_unanswered_count_label: Optional[QLabel] = None
        self.submit_back_btn: Optional[QPushButton] = None
        self.manual_grade_btn: Optional[QPushButton] = None
        self.answer_content_stack: Optional[QStackedWidget] = None
        self.manual_grading_panel: Optional[ManualGradingPanel] = None
        self.manual_grading_active = False
        self.manual_grading_finalized = False
        self.manual_rows_snapshot: List[ManualGradeRow] = []
        self._mark_scheme_download_worker: Optional[MarkSchemeDownloadWorker] = None
        self._mark_scheme_prefetch_thread: Optional[threading.Thread] = None
        self._mark_scheme_prefetch_started = False
        self._grading_started_monotonic: Optional[float] = None
        self._grading_last_progress_monotonic: Optional[float] = None
        self._grading_last_status_message: str = ""
        self._grading_heartbeat_timer = QTimer(self)
        self._grading_heartbeat_timer.setInterval(1000)
        self._grading_heartbeat_timer.timeout.connect(self._on_grading_heartbeat)
        self._autosave_debounce_timer = QTimer(self)
        self._autosave_debounce_timer.setSingleShot(True)
        self._autosave_debounce_timer.setInterval(self._autosave_debounce_interval_ms)
        self._autosave_debounce_timer.timeout.connect(self._on_autosave_debounce_timeout)
        self._autosave_periodic_timer = QTimer(self)
        self._autosave_periodic_timer.setInterval(12_000)
        self._autosave_periodic_timer.timeout.connect(self._on_autosave_periodic_timeout)
        self._theme_manager = get_theme_manager()
        self._theme_signal_connected = False
        self._central_widget: Optional[QWidget] = None
        self._pending_theme_change_name: Optional[str] = None
        self._theme_change_queued = False
        self._settings_window: Optional[FloatingSettingsWindow] = None
        self._available_ui_fonts: List[str] = discover_available_ui_fonts()
        self._user_docs_dialog: Optional[QDialog] = None
        self._user_docs_browser: Optional[QTextBrowser] = None
        self._restore_settings_after_user_docs = False
        self._graceful_exit_in_progress = False
        self._graceful_exit_finalizing = False
        self._graceful_exit_cleanup_started = False
        self._graceful_exit_timer = QTimer(self)
        self._graceful_exit_timer.setInterval(10)
        self._graceful_exit_timer.timeout.connect(self._advance_graceful_exit)
        self._graceful_exit_step = 0.05
        self._runtime_theme_apply_in_progress = False
        self._runtime_theme_reapply_requested = False
        self._runtime_theme_signature: Optional[Tuple[str, bool, bool]] = None
        self._floating_warning_dialogs: List[QMessageBox] = []

        self.setup_ui()
        self._apply_focus_mode_visibility()
        self._theme_manager.theme_changed.connect(self._on_theme_changed)
        self._theme_signal_connected = True
        self.apply_runtime_theme(force=True)
        QTimer.singleShot(0, self._show_groq_startup_warning_if_needed)

        self._initialize_pdf_sources()
        self._sync_duration_from_question_pdf()
        self._prefetch_mark_scheme_in_background()
        initial_sources = self._visible_pdf_sources()
        if initial_sources:
            self._show_pdf_source(initial_sources[0], emit_signal=False)
        self._update_pdf_source_toggle()

        self._apply_resume_snapshot()
        from UI.exam_workspace import ExamWorkspace
        self._studio_workspace = ExamWorkspace(self)
        if self.session_state.mode == "practice":
            self._set_mark_scheme_unlock(True)
        self.setWindowTitle(f"{self.session_state.mode.title()} · {subject_name} · Past Paper Studio")
        if self.pdf_viewer.pdf_path:
            self.pdf_viewer.fit_to_width()
        self._update_timer_label()
        self._apply_timer_visual_state()
        self._update_grading_action_visibility()
        self._autosave_last_saved_monotonic = time.monotonic()
        self._autosave_periodic_timer.start()
        self._timer_last_monotonic = time.monotonic()
        self._timer_fraction = 0.0
        self.timer.start(1000)


    def _paper_metadata_line(self) -> str:
        d = self.paper_mode_decision
        parts = self._paper_metadata_parts()
        if not parts:
            return ""
        return " | ".join(parts)

    def _paper_metadata_parts(self) -> List[str]:
        d = self.paper_mode_decision
        parts: List[str] = []
        if d.assessment_type:
            parts.append(f"Type: {d.assessment_type}")
        if d.duration_minutes:
            mins = int(d.duration_minutes)
            hours = mins // 60
            rem = mins % 60
            if hours and rem:
                duration_text = f"{hours}h {rem}m"
            elif hours:
                duration_text = f"{hours}h"
            else:
                duration_text = f"{rem}m"
            parts.append(f"Duration: {duration_text}")
        if d.total_marks:
            parts.append(f"Marks: {int(d.total_marks)}")
        if d.weight_percent:
            parts.append(f"Weight: {float(d.weight_percent):g}%")
        if d.calculator_policy:
            calc = d.calculator_policy.replace("_", " ").strip().title()
            parts.append(f"Calculator: {calc}")
        if d.notes:
            parts.append(d.notes)
        return parts

    def _show_paper_info_popover(self) -> None:
        if not self.paper_info_btn:
            return
        if self.paper_info_menu is None:
            self.paper_info_menu = QMenu(self)
        menu = self.paper_info_menu
        menu.clear()
        menu.setStyleSheet(self._additional_tools_menu_style())
        menu.setWindowOpacity(0.94)
        parts = self._paper_metadata_parts()
        if not parts:
            action = menu.addAction("No paper metadata available.")
            action.setEnabled(False)
        else:
            for item in parts:
                action = menu.addAction(str(item))
                action.setEnabled(False)
        anchor_widget = self._studio_workspace.more if self._studio_workspace else self.paper_info_btn
        anchor = anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height() + 2))
        menu.popup(anchor)

    def _layout_prefix(self) -> str:
        paper_key = self.paper_number_raw or str(self.paper_num)
        return f"layout/{self.subject_code}/{paper_key}/{self.paper_mode}"

    @staticmethod
    def _normalize_answer_panel_position(position: str) -> str:
        normalized = str(position or "").strip().lower()
        return normalized if normalized in {"left", "right", "bottom"} else "bottom"

    def _splitter_settings_key_for_position(self, position: str) -> str:
        normalized = self._normalize_answer_panel_position(position)
        return f"{self._layout_prefix()}/splitter_sizes/{normalized}"

    def _apply_answer_panel_position_to_splitter(self, *, restore_sizes: bool) -> None:
        splitter = self.exam_splitter
        pdf_widget = self._exam_splitter_pdf_widget
        answer_widget = self._exam_splitter_answer_widget
        if not isinstance(splitter, QSplitter) or not isinstance(pdf_widget, QWidget) or not isinstance(answer_widget, QWidget):
            return

        position = self._normalize_answer_panel_position(self._answer_panel_position)
        is_bottom = position == "bottom"
        splitter.setOrientation(Qt.Orientation.Vertical if is_bottom else Qt.Orientation.Horizontal)

        if position == "left":
            splitter.insertWidget(0, answer_widget)
            splitter.insertWidget(1, pdf_widget)
            splitter.setStretchFactor(0, 2)
            splitter.setStretchFactor(1, 4)
        else:
            splitter.insertWidget(0, pdf_widget)
            splitter.insertWidget(1, answer_widget)
            splitter.setStretchFactor(0, 4)
            splitter.setStretchFactor(1, 2)

        if is_bottom:
            pdf_widget.setMinimumHeight(240)
            answer_widget.setMinimumHeight(150)
            pdf_widget.setMinimumWidth(0)
            answer_widget.setMinimumWidth(0)
        else:
            pdf_widget.setMinimumWidth(380)
            answer_widget.setMinimumWidth(320)
            pdf_widget.setMinimumHeight(0)
            answer_widget.setMinimumHeight(0)

        self._splitter_settings_key = self._splitter_settings_key_for_position(position)
        if restore_sizes:
            self._restore_splitter_sizes(splitter, self._splitter_default_sizes or [770, 330])

    def _restore_splitter_sizes(self, splitter: QSplitter, default_sizes: List[int]) -> None:
        key = self._splitter_settings_key_for_position(self._answer_panel_position)
        self._splitter_settings_key = key
        self._splitter_default_sizes = list(default_sizes)

        raw = self.settings.value(key, None)
        parsed: List[int] = []
        if isinstance(raw, list):
            for item in raw:
                try:
                    parsed.append(int(item))
                except Exception:
                    pass
        elif isinstance(raw, str):
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    parsed.append(int(part))
                except Exception:
                    pass

        if len(parsed) == 2 and all(v > 20 for v in parsed):
            splitter.setSizes(parsed)
        else:
            splitter.setSizes(default_sizes)

    def _save_splitter_layout(self) -> None:
        if not self.exam_splitter or not self._splitter_settings_key:
            return
        try:
            sizes = [int(v) for v in self.exam_splitter.sizes()]
            self.settings.setValue(self._splitter_settings_key, sizes)
        except Exception:
            pass

    def _build_exam_splitter(self, pdf_widget: QWidget, answer_widget: QWidget, default_sizes: List[int]) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setStyleSheet(self._splitter_handle_style())
        splitter.splitterMoved.connect(lambda *_: self._save_splitter_layout())
        splitter.addWidget(pdf_widget)
        splitter.addWidget(answer_widget)
        self.exam_splitter = splitter
        self._exam_splitter_pdf_widget = pdf_widget
        self._exam_splitter_answer_widget = answer_widget
        self._splitter_default_sizes = list(default_sizes)
        self._apply_answer_panel_position_to_splitter(restore_sizes=True)
        return splitter

    def _build_pdf_view_host(self, primary_viewer: PDFViewer) -> QWidget:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        primary_viewer.set_edge_navigation_enabled(True)
        self._register_pdf_viewer_tracking(primary_viewer)
        primary_viewer.setVisible(True)
        host_layout.addWidget(primary_viewer, 1)

        split_host = QWidget()
        split_layout = QVBoxLayout(split_host)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(4)

        split_panes = QSplitter(Qt.Orientation.Horizontal)
        split_panes.setChildrenCollapsible(False)
        split_panes.setHandleWidth(10)
        split_panes.setStyleSheet(
            "QSplitter::handle:horizontal {"
            f"background-color: {_mix_hex(Colors.BG_LIGHT, Colors.BG_DARK, 0.45)};"
            "border-radius: 2px;"
            "margin: 0px 4px;"
            "width: 2px;"
            "}"
            "QSplitter::handle:horizontal:hover {"
            f"background-color: {_mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.18)};"
            "}"
        )

        left_holder = QWidget()
        left_layout = QVBoxLayout(left_holder)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_label = QLabel("Question Paper")
        left_label.setStyleSheet(
            f"color: {Colors.TEXT_GRAY}; font-size: 11px; letter-spacing: 0.6px; font-weight: 600;"
        )
        left_layout.addWidget(left_label)
        left_viewer = PDFViewer()
        left_viewer.set_controls_visible(False)
        left_viewer.set_edge_navigation_enabled(False)
        self._register_pdf_viewer_tracking(left_viewer)
        left_layout.addWidget(left_viewer, 1)

        right_holder = QWidget()
        right_layout = QVBoxLayout(right_holder)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)
        right_label = QLabel("Insert")
        right_label.setStyleSheet(
            f"color: {Colors.TEXT_GRAY}; font-size: 11px; letter-spacing: 0.6px; font-weight: 600;"
        )
        right_layout.addWidget(right_label)
        right_viewer = PDFViewer()
        right_viewer.set_controls_visible(False)
        right_viewer.set_edge_navigation_enabled(False)
        self._register_pdf_viewer_tracking(right_viewer)
        right_layout.addWidget(right_viewer, 1)

        split_panes.addWidget(left_holder)
        split_panes.addWidget(right_holder)
        split_panes.setStretchFactor(0, 1)
        split_panes.setStretchFactor(1, 1)
        split_panes.setSizes([1, 1])
        split_layout.addWidget(split_panes, 1)

        split_host.setVisible(False)
        host_layout.addWidget(split_host, 1)

        self._insert_split_inline_host = split_host
        self._insert_split_inline_splitter = split_panes
        self._insert_split_question_viewer = left_viewer
        self._insert_split_insert_viewer = right_viewer
        self._insert_split_left_label = left_label
        self._insert_split_right_label = right_label
        self._insert_split_enabled = False
        return host

    def _register_pdf_viewer_tracking(self, viewer: PDFViewer) -> None:
        if not isinstance(viewer, PDFViewer):
            return
        viewer_id = id(viewer)
        if viewer_id in self._tracked_pdf_viewer_ids:
            return
        self._tracked_pdf_viewer_ids.add(viewer_id)
        viewer.installEventFilter(self)
        viewer.destroyed.connect(lambda _=None, key=viewer_id: self._tracked_pdf_viewer_ids.discard(key))

    @staticmethod
    def _splitter_handle_style() -> str:
        base = _mix_hex(Colors.BG_MEDIUM, Colors.BG_DARK, 0.34)
        hover = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.28)
        border = _mix_hex(base, Colors.BG_DARK, 0.24)
        return (
            "QSplitter::handle:vertical {"
            f"background-color: {base};"
            f"border: 1px solid {border};"
            "border-radius: 3px;"
            "margin: 1px 0;"
            "}"
            "QSplitter::handle:vertical:hover {"
            f"background-color: {hover};"
            "}"
        )

    def _apply_splitter_theme(self) -> None:
        if self.exam_splitter:
            self.exam_splitter.setStyleSheet(self._splitter_handle_style())

    def _reset_layout(self):
        if self.exam_splitter and self._splitter_default_sizes:
            self.exam_splitter.setSizes(self._splitter_default_sizes)
            self._save_splitter_layout()
        self.grade_status_label.setText("Layout reset")

    def _restore_calculator_geometry(self) -> None:
        if not self.calculator_dialog:
            return
        try:
            raw = self.settings.value(self._calculator_geometry_key, None)
            if raw is not None:
                self.calculator_dialog.restoreGeometry(raw)
        except Exception:
            pass

    def _save_calculator_geometry(self) -> None:
        if not self.calculator_dialog:
            return
        try:
            self.settings.setValue(self._calculator_geometry_key, self.calculator_dialog.saveGeometry())
        except Exception:
            pass

    def _ensure_calculator_dialog(self) -> None:
        if self.calculator_dialog is not None:
            return
        widget = ScientificCalculatorWidget()
        dialog = CalculatorDialog(widget, parent=self)
        dialog.visibility_changed.connect(self._on_calculator_visibility_changed)
        self.calculator_dialog = dialog
        self.calculator_widget = widget
        if hasattr(widget, "apply_runtime_theme"):
            try:
                widget.apply_runtime_theme()
            except Exception:
                pass
        self._restore_calculator_geometry()

    def _toggle_calculator_dialog(self):
        self._ensure_calculator_dialog()
        if not self.calculator_dialog:
            return
        is_visible = self.calculator_dialog.isVisible()
        if is_visible:
            self._save_calculator_geometry()
            self.calculator_dialog.hide()
        else:
            self.calculator_dialog.show()
            self.calculator_dialog.raise_()
            self.calculator_dialog.activateWindow()

    # Backward-compatible wrappers.
    def _setup_calculator_dock(self):
        self._ensure_calculator_dialog()

    def _toggle_calculator_dock(self):
        self._toggle_calculator_dialog()

    def _on_calculator_visibility_changed(self, visible: bool):
        if self.calculator_toggle_btn:
            self.calculator_toggle_btn.setText("Hide Calculator" if visible else "Calculator")
        if self.calculator_icon_btn:
            self.calculator_icon_btn.setToolTip("Hide Calculator" if visible else "Open Calculator")
            self.calculator_icon_btn.setStyleSheet(self._quick_tool_icon_style(active=bool(visible)))
        if not visible:
            self._save_calculator_geometry()
        self._refresh_additional_tools_menu_state()
        self._sync_utility_drawer_button_states()
        if hasattr(self, "pdf_viewer") and self.pdf_viewer:
            try:
                self.pdf_viewer.refresh_view()
            except Exception:
                pass

    def _is_math_subject(self) -> bool:
        subject = str(self.subject_code).strip()
        if subject in {"0580", "0606", "0607", "0980"}:
            return True
        if str(self.paper_mode_decision.calculator_policy or "").strip():
            return True
        return "mathematics" in str(self.subject_name or "").lower()

    def _paper_base_component(self) -> str:
        raw = str(self.paper_number_raw or "").strip()
        if raw and raw[0].isdigit():
            return raw[0]
        match = re.search(r"\d", raw)
        return match.group(0) if match else str(self.paper_num or "").strip()

    def _should_show_calculator_button(self) -> bool:
        policy = str(self.paper_mode_decision.calculator_policy or "").strip().lower()
        if policy == "not_allowed":
            return False
        if policy:
            return True

        if not self._is_math_subject():
            return True

        # Fallback for 0607 component-based inputs when policy metadata is absent.
        if str(self.subject_code).strip() == "0607":
            base = self._paper_base_component()
            return base not in {"1", "2"}
        return True

    def _open_user_documentation(self) -> None:
        settings_window = self.__dict__.get("_settings_window")
        if settings_window:
            self._restore_settings_after_user_docs = True
            settings_window.hide()

        if self._user_docs_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("User Documentation")
            dialog.setModal(False)
            dialog.resize(980, 760)
            layout = QVBoxLayout(dialog)
            browser = QTextBrowser(dialog)
            browser.setReadOnly(True)
            browser.setOpenExternalLinks(True)
            layout.addWidget(browser)
            dialog.installEventFilter(self)
            self._user_docs_dialog = dialog
            self._user_docs_browser = browser
        if self._user_docs_browser:
            self._user_docs_browser.setMarkdown(build_user_documentation_markdown())
        self._user_docs_dialog.show()
        self._user_docs_dialog.raise_()
        self._user_docs_dialog.activateWindow()

    def _restore_settings_after_docs_if_needed(self) -> None:
        if not self._restore_settings_after_user_docs:
            return
        settings_window = self.__dict__.get("_settings_window")
        self._restore_settings_after_user_docs = False
        if not settings_window:
            return
        self._sync_settings_window_state()
        settings_window.apply_runtime_theme()
        settings_window.show()
        settings_window.raise_()
        settings_window.activateWindow()

    @staticmethod
    def _reset_ai_config_cache() -> None:
        try:
            import Grading.ai_config as ai_config

            ai_config._default_config = None  # type: ignore[attr-defined]
        except Exception:
            pass

    @staticmethod
    def _current_ai_values() -> tuple[str, str, str]:
        return (
            str(load_groq_api_key() or ""),
            str(load_groq_text_model() or ""),
            str(load_groq_vision_model() or ""),
        )

    def _save_ai_settings(self, api_key: str, text_model: str, vision_model: str) -> bool:
        saved = save_groq_settings(
            api_key=api_key.strip() if str(api_key or "").strip() else None,
            text_model=text_model.strip() if str(text_model or "").strip() else None,
            vision_model=vision_model.strip() if str(vision_model or "").strip() else None,
        )
        if not saved:
            show_error(self, "Error", "Could not save Groq settings.")
            return False
        self._reset_ai_config_cache()
        self._sync_settings_window_state()
        show_info(self, "Saved", "Groq settings saved and applied for this session.")
        return True

    def _ensure_settings_window(self) -> None:
        existing = self.__dict__.get("_settings_window")
        if existing is not None:
            return
        window = FloatingSettingsWindow(
            self,
            on_theme_selected=self.on_theme_changed_by_user,
            on_font_selected=self.on_font_changed_by_user,
            on_sound_toggled=self.on_sound_toggled,
            on_scale_toggled=self.on_question_scale_toggled,
            on_system_accent_toggled=self.on_system_accent_toggled,
            on_answer_panel_position_changed=self.on_answer_panel_position_changed,
            on_preference_toggled=self.on_preference_toggled,
            on_open_docs=self._open_user_documentation,
            on_save_ai=self._save_ai_settings,
            on_refresh_ai=self._current_ai_values,
            on_delete_theme=self._delete_custom_theme_by_user,
        )
        window.setWindowTitle("Settings")
        self._settings_window = window
        self._sync_settings_window_state()

    def _show_exam_settings_window(self) -> None:
        self._ensure_settings_window()
        self._available_ui_fonts = discover_available_ui_fonts()
        window = self.__dict__.get("_settings_window")
        if not window:
            return
        self._sync_settings_window_state()
        window.apply_runtime_theme()
        window.show()
        window.raise_()
        window.activateWindow()

    def _sync_settings_window_state(self) -> None:
        window = self.__dict__.get("_settings_window")
        if not window:
            return
        window.set_font_options([DEFAULT_FONT_OPTION, *self._available_ui_fonts])
        window.set_selected_font(self._current_global_font_family())
        window.set_sound_enabled(ConfigManager.get_sound_enabled())
        window.set_sound_control_state(
            True,
            "Enable listening-paper and media audio.",
            visible=True,
        )
        window.set_scale_enabled(self._question_scale_visible)
        window.set_scale_control_state(
            True,
            "Show or hide the centimeter scale overlay in exam mode.",
            visible=True,
        )
        window.set_system_accent_enabled(ConfigManager.get_dashboard_match_system_accent())
        window.set_system_accent_control_state(
            True,
            "Use operating system accent colors when available.",
            visible=True,
        )
        window.set_preferences(
            show_startup_animation=ConfigManager.get_value("ui.show_startup_animation", True),
            full_screen_on_startup=ConfigManager.get_value("ui.full_screen_on_startup", True),
            custom_theme_creator_enabled=ConfigManager.get_value("ui.custom_theme_creator_enabled", False),
        )
        window.set_theme_names(self._theme_manager.theme_names())
        window.set_selected_theme(self._current_theme_name())
        window.set_ai_values(*self._current_ai_values())
        if window.isVisible():
            window.apply_runtime_theme()

    def on_preference_toggled(self, key: str, enabled: bool) -> None:
        if key not in {"show_startup_animation", "full_screen_on_startup", "custom_theme_creator_enabled"}:
            return
        ConfigManager.set_value(f"ui.{key}", bool(enabled))
        self._sync_settings_window_state()

    def _additional_tools_button_style(self) -> str:
        base = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.16)
        border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.42)
        hover_bg = _mix_hex(base, Colors.ACCENT_CYAN, 0.16)
        hover_border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.2)
        text_color = _contrast_text_for_bg(base)
        hover_text = _contrast_text_for_bg(hover_bg)
        disabled_bg = _mix_hex(base, Colors.BG_CARD, 0.74)
        disabled_border = _mix_hex(border, Colors.BG_DARK, 0.46)
        disabled_text = _mix_hex(text_color, Colors.TEXT_GRAY, 0.72)
        return (
            "QPushButton {"
            f"background-color: {base};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 2px;"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "font-size: 13px;"
            "font-weight: bold;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {hover_bg};"
            f"color: {hover_text};"
            f"border: 1px solid {hover_border};"
            "}"
            "QPushButton:pressed {"
            f"background-color: {hover_bg};"
            f"color: {hover_text};"
            f"border: 1px solid {hover_border};"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
            "QPushButton:disabled {"
            f"background-color: {disabled_bg};"
            f"color: {disabled_text};"
            f"border: 1px solid {disabled_border};"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
        )

    def _additional_tools_menu_style(self) -> str:
        border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.3)
        hover_bg = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.24)
        hover_text = _contrast_text_for_bg(hover_bg)
        disabled_text = _mix_hex(Colors.TEXT_WHITE, Colors.TEXT_GRAY, 0.72)
        return (
            "QMenu {"
            "background-color: rgba(10, 18, 31, 224);"
            f"color: {Colors.TEXT_WHITE};"
            f"border: 1px solid {border};"
            "border-radius: 8px;"
            "padding: 4px;"
            "}"
            "QMenu::item {"
            "padding: 8px 14px;"
            "border-radius: 6px;"
            "background-color: transparent;"
            "}"
            "QMenu::item:selected {"
            f"background-color: {hover_bg};"
            f"color: {hover_text};"
            f"border: 1px solid {Colors.ACCENT_CYAN};"
            "}"
            "QMenu::item:disabled {"
            f"color: {disabled_text};"
            "background-color: transparent;"
            "}"
            "QMenu::item:disabled:selected {"
            f"color: {disabled_text};"
            "background-color: transparent;"
            "border: none;"
            "}"
            "QMenu::separator {"
            "height: 1px;"
            "background: rgba(125, 211, 252, 85);"
            "margin: 4px 10px;"
            "}"
        )

    def _selection_dialog_style(self) -> str:
        border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.28)
        control_bg = _mix_hex(Colors.BG_CARD, Colors.BG_DARK, 0.24)
        control_border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.36)
        control_text = Colors.TEXT_WHITE
        return (
            "QDialog {"
            "background-color: rgba(8, 14, 24, 222);"
            f"color: {Colors.TEXT_WHITE};"
            f"border: 1px solid {border};"
            "border-radius: 12px;"
            "}"
            "QLabel {"
            f"color: {Colors.TEXT_WHITE};"
            "background-color: transparent;"
            "}"
            "QListWidget, QComboBox {"
            f"background-color: {control_bg};"
            f"color: {control_text};"
            f"border: 1px solid {control_border};"
            "border-radius: 8px;"
            "padding: 4px 6px;"
            "}"
            "QPushButton {"
            f"background-color: {control_bg};"
            f"color: {control_text};"
            f"border: 1px solid {control_border};"
            "border-radius: 9px;"
            "padding: 7px 12px;"
            "font-weight: 700;"
            "}"
        )

    def _apply_selection_dialog_translucent_style(self, dialog: Optional[QDialog]) -> None:
        if not isinstance(dialog, QDialog):
            return
        dialog.setStyleSheet(self._selection_dialog_style())
        dialog.setWindowOpacity(0.95)

    @staticmethod
    def _utility_drawer_button_font() -> QFont:
        font = QFont("JetBrains Mono", 9, QFont.Weight.DemiBold)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        return font

    def _create_utility_drawer_button(
        self,
        label: str,
        tooltip: str,
        *,
        base_color: str,
        checkable: bool = False,
    ) -> QPushButton:
        parent = self.utility_drawer if isinstance(self.utility_drawer, QWidget) else self
        button = QPushButton(str(label or ""), parent)
        button.setToolTip(str(tooltip or ""))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCheckable(bool(checkable))
        button.setFont(self._utility_drawer_button_font())
        button.setMinimumHeight(28)
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    def _build_utility_drawer(self) -> None:
        if self.utility_drawer is not None:
            return
        host = self._central_widget
        if not isinstance(host, QWidget):
            return

        drawer = QFrame(host)
        drawer.setObjectName("examUtilityDrawer")
        drawer.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(drawer)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        calc_btn = self._create_utility_drawer_button(
            "Calculator",
            "Toggle Scientific Calculator",
            base_color=Colors.BG_LIGHT,
            checkable=True,
        )
        calc_btn.clicked.connect(self._toggle_calculator_dialog)
        layout.addWidget(calc_btn)

        notes_btn = self._create_utility_drawer_button(
            "Scratchpad",
            "Toggle Scratchpad / Notes",
            base_color=Colors.BG_LIGHT,
            checkable=True,
        )
        notes_btn.clicked.connect(self._toggle_notes_dialog)
        layout.addWidget(notes_btn)

        ruler_btn = self._create_utility_drawer_button(
            "Ruler",
            "Toggle Movable Ruler",
            base_color=Colors.BG_LIGHT,
            checkable=True,
        )
        ruler_btn.toggled.connect(self._set_movable_ruler_enabled)
        layout.addWidget(ruler_btn)

        periodic_btn = self._create_utility_drawer_button(
            "Periodic Table",
            "Open Periodic Table helper (Chemistry only)",
            base_color=Colors.ACCENT_PURPLE,
            checkable=False,
        )
        periodic_btn.clicked.connect(self._go_to_periodic_table)
        layout.addWidget(periodic_btn)

        self.utility_drawer = drawer
        self.utility_drawer_calculator_btn = calc_btn
        self.utility_drawer_notes_btn = notes_btn
        self.utility_drawer_ruler_btn = ruler_btn
        self.utility_drawer_periodic_btn = periodic_btn
        self._utility_drawer_open = False

        self._utility_drawer_animation = QPropertyAnimation(drawer, b"pos", self)
        self._utility_drawer_animation.setDuration(220)
        self._utility_drawer_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._sync_utility_drawer_button_states()
        self._refresh_utility_drawer_geometry(animate=False)
        drawer.raise_()

    def _utility_drawer_target_pos(self, open_state: bool) -> QPoint:
        drawer = self.utility_drawer
        host = self._central_widget
        if not isinstance(drawer, QWidget) or not isinstance(host, QWidget):
            return QPoint(0, 0)
        margin = 14
        right_gutter = 10
        top_bar = self.top_bar if isinstance(self.top_bar, QWidget) else None
        y = int(top_bar.geometry().bottom() + 6) if top_bar is not None else 52
        open_x = max(margin, int(host.width() - drawer.width() - margin - right_gutter))
        closed_x = int(host.width() + 8)
        return QPoint(open_x if open_state else closed_x, max(0, y))

    def _refresh_utility_drawer_geometry(self, *, animate: bool = False) -> None:
        drawer = self.utility_drawer
        if not isinstance(drawer, QWidget):
            return
        drawer.adjustSize()
        drawer.setFixedWidth(166)
        target_pos = self._utility_drawer_target_pos(self._utility_drawer_open)
        if animate and isinstance(self._utility_drawer_animation, QPropertyAnimation):
            self._utility_drawer_animation.stop()
            self._utility_drawer_animation.setStartValue(drawer.pos())
            self._utility_drawer_animation.setEndValue(target_pos)
            self._utility_drawer_animation.start()
            return
        drawer.move(target_pos)

    def _set_utility_drawer_open(self, open_state: bool, *, animate: bool = True) -> None:
        self._build_utility_drawer()
        if not isinstance(self.utility_drawer, QWidget):
            return
        self._utility_drawer_open = bool(open_state)
        self._sync_utility_drawer_button_states()
        self._refresh_utility_drawer_geometry(animate=animate)
        if self.additional_tools_btn:
            self.additional_tools_btn.setText("🛠 Tools ◂" if self._utility_drawer_open else "🛠 Tools")
        if self._utility_drawer_open:
            self.utility_drawer.raise_()

    def _toggle_utility_drawer(self) -> None:
        self._set_utility_drawer_open(not self._utility_drawer_open, animate=True)

    def _sync_utility_drawer_button_states(self) -> None:
        self._build_utility_drawer()
        calc_btn = self.utility_drawer_calculator_btn
        notes_btn = self.utility_drawer_notes_btn
        ruler_btn = self.utility_drawer_ruler_btn
        periodic_btn = self.utility_drawer_periodic_btn

        calc_visible = bool(self.calculator_dialog and self.calculator_dialog.isVisible())
        notes_visible = bool(self.notes_dialog and self.notes_dialog.isVisible())
        ruler_enabled = bool(self._movable_ruler_enabled)
        periodic_busy = bool(self._periodic_lookup_worker and self._periodic_lookup_worker.isRunning())
        is_chemistry = self._is_chemistry_subject()

        if isinstance(calc_btn, QPushButton):
            blocked = calc_btn.blockSignals(True)
            calc_btn.setChecked(calc_visible)
            calc_btn.blockSignals(blocked)
            calc_btn.setEnabled(self._should_show_calculator_button())
            calc_btn.setToolTip("Hide Scientific Calculator" if calc_visible else "Toggle Scientific Calculator")
        if isinstance(notes_btn, QPushButton):
            blocked = notes_btn.blockSignals(True)
            notes_btn.setChecked(notes_visible)
            notes_btn.blockSignals(blocked)
            notes_btn.setToolTip("Hide Scratchpad / Notes" if notes_visible else "Toggle Scratchpad / Notes")
        if isinstance(ruler_btn, QPushButton):
            blocked = ruler_btn.blockSignals(True)
            ruler_btn.setChecked(ruler_enabled)
            ruler_btn.blockSignals(blocked)
        if isinstance(periodic_btn, QPushButton):
            periodic_btn.setVisible(is_chemistry)
            periodic_btn.setEnabled(is_chemistry and (not periodic_busy))

    def _build_additional_tools_menu(self) -> None:
        if self.additional_tools_menu is None:
            self.additional_tools_menu = QMenu(self)
        menu = self.additional_tools_menu
        menu.clear()
        menu.setStyleSheet(self._additional_tools_menu_style())
        self.additional_tools_settings_action = None
        self.additional_tools_calculator_action = None
        self.additional_tools_periodic_action = None
        self.additional_tools_notes_action = None
        self.additional_tools_ruler_action = None

        if self._should_show_calculator_button():
            self.additional_tools_calculator_action = menu.addAction("Scientific Calculator")
            self.additional_tools_calculator_action.triggered.connect(self._toggle_calculator_dialog)

        if self._is_chemistry_subject():
            self.additional_tools_periodic_action = menu.addAction("Periodic Table")
            self.additional_tools_periodic_action.triggered.connect(self._go_to_periodic_table)

        self.additional_tools_notes_action = menu.addAction("Scratchpad / Notes")
        self.additional_tools_notes_action.triggered.connect(self._toggle_notes_dialog)
        self.additional_tools_ruler_action = menu.addAction("Movable Ruler")
        self.additional_tools_ruler_action.setCheckable(True)
        self.additional_tools_ruler_action.toggled.connect(self._set_movable_ruler_enabled)

    def _refresh_additional_tools_menu_state(self) -> None:
        if self.additional_tools_btn:
            self.additional_tools_btn.setStyleSheet("")
        if self.exam_settings_btn:
            self.exam_settings_btn.setStyleSheet("")
        self._build_additional_tools_menu()
        if self.additional_tools_menu:
            self.additional_tools_menu.setStyleSheet(self._additional_tools_menu_style())
        if self.additional_tools_calculator_action:
            visible = bool(self.calculator_dialog and self.calculator_dialog.isVisible())
            self.additional_tools_calculator_action.setText(
                "Hide Scientific Calculator" if visible else "Scientific Calculator"
            )
            self.additional_tools_calculator_action.setEnabled(self._should_show_calculator_button())
        if self.additional_tools_periodic_action:
            busy = bool(self._periodic_lookup_worker and self._periodic_lookup_worker.isRunning())
            self.additional_tools_periodic_action.setEnabled(self._is_chemistry_subject() and not busy)
        if self.additional_tools_notes_action:
            notes_visible = bool(self.notes_dialog and self.notes_dialog.isVisible())
            self.additional_tools_notes_action.setText(
                "Hide Scratchpad / Notes" if notes_visible else "Scratchpad / Notes"
            )
        if self.additional_tools_ruler_action:
            blocked = self.additional_tools_ruler_action.blockSignals(True)
            self.additional_tools_ruler_action.setChecked(bool(self._movable_ruler_enabled))
            self.additional_tools_ruler_action.blockSignals(blocked)
        self._apply_movable_ruler_state_to_viewers()
        self._sync_utility_drawer_button_states()

    def _show_additional_tools_menu(self) -> None:
        self._refresh_additional_tools_menu_state()
        if self._studio_workspace is not None:
            self.additional_tools_menu.setStyleSheet(self._studio_workspace.menu_style())
            self.additional_tools_menu.addAction("Reset ruler position", self.pdf_viewer.reset_ruler_position)
            self._studio_workspace.add_document_tools(self.additional_tools_menu)
            self._studio_workspace.refresh_theme()
            self.additional_tools_menu.popup(self.additional_tools_btn.mapToGlobal(QPoint(0, self.additional_tools_btn.height())))
        else:
            self._toggle_utility_drawer()

    def _build_grading_mode_menu(self) -> None:
        if self.grading_mode_menu is None:
            self.grading_mode_menu = QMenu(self)
        menu = self.grading_mode_menu
        menu.clear()
        menu.setStyleSheet(self._additional_tools_menu_style())

        self.grading_mode_toggle_action = None

        self.grading_mode_mapping_action = menu.addAction("Review Mapping")
        self.grading_mode_mapping_action.triggered.connect(self.review_mapping_overrides)
        self.grading_mode_mapping_action.setEnabled(False)

        self.grading_mode_cancel_action = menu.addAction("Cancel Grade")
        self.grading_mode_cancel_action.triggered.connect(self.cancel_auto_grade)
        self.grading_mode_cancel_action.setEnabled(False)

    def _show_grading_mode_menu(self) -> None:
        if not self.grading_mode_btn:
            return
        if self.grading_mode_menu is None:
            self._build_grading_mode_menu()
        if not self.grading_mode_menu:
            return
        self._update_grading_action_visibility()
        anchor_widget = self._studio_workspace.more if self._studio_workspace else self.grading_mode_btn
        anchor = anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height() + 2))
        self.grading_mode_menu.popup(anchor)

    def _save_notes_geometry(self) -> None:
        if not self.notes_dialog:
            return
        try:
            self.settings.setValue(self._notes_geometry_key, self.notes_dialog.saveGeometry())
        except Exception:
            pass

    def _restore_notes_geometry(self) -> None:
        if not self.notes_dialog:
            return
        try:
            raw = self.settings.value(self._notes_geometry_key, None)
            if raw is not None:
                self.notes_dialog.restoreGeometry(raw)
        except Exception:
            pass

    def _ensure_notes_dialog(self) -> None:
        if self.notes_dialog is not None and self.notes_widget is not None:
            return
        widget = NotesWidget(self)
        widget.set_notes_text(self._notes_text_cache)
        widget.notes_changed.connect(self._on_notes_text_changed)
        dialog = NotesDialog(widget, parent=self)
        dialog.visibility_changed.connect(self._on_notes_visibility_changed)
        self.notes_widget = widget
        self.notes_dialog = dialog
        self._restore_notes_geometry()

    def _on_notes_text_changed(self, text: str) -> None:
        self._notes_text_cache = str(text or "")
        self._mark_resume_snapshot_dirty()

    def _toggle_notes_dialog(self) -> None:
        self._ensure_notes_dialog()
        if not self.notes_dialog:
            return
        is_visible = self.notes_dialog.isVisible()
        if is_visible:
            self._save_notes_geometry()
            self.notes_dialog.hide()
        else:
            if self.notes_widget and self.notes_widget.notes_text() != self._notes_text_cache:
                self.notes_widget.set_notes_text(self._notes_text_cache)
            self.notes_dialog.show()
            self.notes_dialog.raise_()
            self.notes_dialog.activateWindow()

    def _on_notes_visibility_changed(self, visible: bool) -> None:
        if not visible:
            self._save_notes_geometry()
        self._refresh_additional_tools_menu_state()
        self._sync_utility_drawer_button_states()

    @staticmethod
    def _quick_tool_icon_style(active: bool = False) -> str:
        border = Colors.PRIMARY_HOVER if active else Colors.BG_MEDIUM
        bg = Colors.PRIMARY_HOVER if active else Colors.BG_LIGHT
        text_color = _contrast_text_for_bg(bg)
        hover_bg = _mix_hex(bg, Colors.PRIMARY_HOVER, 0.32)
        hover_text = _contrast_text_for_bg(hover_bg)
        return (
            "QPushButton {"
            f"background-color: {bg};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 8px;"
            "padding: 0px;"
            "font-size: 16px;"
            "font-weight: 700;"
            "min-width: 28px;"
            "max-width: 28px;"
            "min-height: 28px;"
            "max-height: 28px;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {hover_bg};"
            f"color: {hover_text};"
            "}"
            "QPushButton:disabled {"
            f"background-color: {_mix_hex(bg, Colors.BG_CARD, 0.66)};"
            f"color: {_mix_hex(text_color, Colors.TEXT_GRAY, 0.72)};"
            f"border: 1px solid {_mix_hex(border, Colors.BG_DARK, 0.42)};"
            "}"
        )

    def _build_pdf_quick_tool_button(self, symbol: str, tooltip: str, on_click: Callable[[], None]) -> QPushButton:
        button = QPushButton(symbol)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setStyleSheet(self._quick_tool_icon_style(False))
        button.clicked.connect(on_click)
        return button

    def _install_pdf_quick_tool_buttons(self) -> None:
        self.calculator_icon_btn = None
        self.periodic_icon_btn = None
        viewer = getattr(self, "pdf_viewer", None)
        if viewer is None or not hasattr(viewer, "set_quick_tool_buttons"):
            return
        viewer.set_quick_tool_buttons([])

    def _refresh_pdf_quick_tool_styles(self) -> None:
        self._refresh_additional_tools_menu_state()

    def _iter_ruler_viewers(self) -> List[PDFViewer]:
        viewers: List[PDFViewer] = []
        primary = getattr(self, "pdf_viewer", None)
        if isinstance(primary, PDFViewer):
            viewers.append(primary)
        for candidate in [self._insert_split_question_viewer, self._insert_split_insert_viewer]:
            if isinstance(candidate, PDFViewer) and candidate not in viewers:
                viewers.append(candidate)
        return viewers

    def _apply_movable_ruler_state_to_viewers(self) -> None:
        enabled = bool(self._movable_ruler_enabled)
        for viewer in self._iter_ruler_viewers():
            try:
                viewer.set_movable_ruler_enabled(enabled)
            except Exception:
                continue

    def _apply_question_scale_state_to_viewers(self) -> None:
        split_enabled = bool(self._insert_split_enabled)
        active_source = str(self._active_pdf_source_key or "").strip().lower()
        scale_visible = bool(self._question_scale_visible)

        primary = getattr(self, "pdf_viewer", None)
        if isinstance(primary, PDFViewer):
            primary_enabled = scale_visible and (not split_enabled) and active_source == "question"
            try:
                primary.set_centimeter_scale_enabled(primary_enabled)
            except Exception:
                pass

        left_viewer = self._insert_split_question_viewer
        if isinstance(left_viewer, PDFViewer):
            try:
                left_viewer.set_centimeter_scale_enabled(scale_visible and split_enabled)
            except Exception:
                pass

        right_viewer = self._insert_split_insert_viewer
        if isinstance(right_viewer, PDFViewer):
            try:
                right_viewer.set_centimeter_scale_enabled(False)
            except Exception:
                pass

    def _set_movable_ruler_enabled(self, enabled: bool) -> None:
        self._movable_ruler_enabled = bool(enabled)
        self._apply_movable_ruler_state_to_viewers()
        if self.additional_tools_ruler_action:
            blocked = self.additional_tools_ruler_action.blockSignals(True)
            self.additional_tools_ruler_action.setChecked(self._movable_ruler_enabled)
            self.additional_tools_ruler_action.blockSignals(blocked)
        self._sync_utility_drawer_button_states()

    def _iter_split_controlled_viewers(self) -> List[PDFViewer]:
        viewers: List[PDFViewer] = []
        if not self._insert_split_enabled:
            return viewers
        for candidate in [self._insert_split_question_viewer, self._insert_split_insert_viewer]:
            if isinstance(candidate, PDFViewer) and candidate not in viewers:
                viewers.append(candidate)
        return viewers

    def _split_global_prev_page(self) -> None:
        for viewer in self._iter_split_controlled_viewers():
            viewer.prev_page()

    def _split_global_next_page(self) -> None:
        for viewer in self._iter_split_controlled_viewers():
            viewer.next_page()

    def _split_global_zoom_out(self) -> None:
        for viewer in self._iter_split_controlled_viewers():
            viewer.zoom_out()

    def _split_global_zoom_in(self) -> None:
        for viewer in self._iter_split_controlled_viewers():
            viewer.zoom_in()

    def _split_global_rotate_ccw(self) -> None:
        for viewer in self._iter_split_controlled_viewers():
            viewer.rotate_current_page_ccw()

    def _split_global_rotate_cw(self) -> None:
        for viewer in self._iter_split_controlled_viewers():
            viewer.rotate_current_page_cw()

    def _update_split_global_controls_visibility(self) -> None:
        zone = self.__dict__.get("split_global_controls_zone")
        active = bool(self._insert_split_enabled)
        if isinstance(zone, QWidget):
            zone.setVisible(active)
        if isinstance(self.split_mode_toggle_btn, QPushButton):
            self.split_mode_toggle_btn.setVisible(active)
            self.split_mode_toggle_btn.setEnabled(active)
            self.split_mode_toggle_btn.setText("Single View" if active else "Split View")
        for button in [
            self.split_nav_prev_btn,
            self.split_nav_next_btn,
            self.split_zoom_out_btn,
            self.split_zoom_in_btn,
            self.split_rotate_ccw_btn,
            self.split_rotate_cw_btn,
        ]:
            if isinstance(button, QPushButton):
                button.setEnabled(active)

    def _download_ms_button_style(self, pulse: float = 0.0) -> str:
        t = max(0.0, min(1.0, float(pulse)))
        base = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.2)
        hover = _mix_hex(base, Colors.ACCENT_CYAN, 0.12 + (0.08 * t))
        border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.46 - (0.08 * t))
        text_color = _contrast_text_for_bg(base)
        return (
            "QPushButton {"
            f"background-color: {base};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 10px;"
            "padding: 8px 16px;"
            "min-height: 34px;"
            "font-size: 13px;"
            "font-weight: bold;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {hover};"
            "}"
            "QPushButton:disabled {"
            f"background-color: {_mix_hex(base, Colors.BG_CARD, 0.72)};"
            f"color: {_mix_hex(text_color, Colors.TEXT_GRAY, 0.72)};"
            f"border: 1px solid {_mix_hex(border, Colors.BG_DARK, 0.44)};"
            "}"
        )


    def _is_chemistry_subject(self) -> bool:
        return self.subject_code == "0620" or "chemistry" in str(self.subject_name).lower()

    def _go_to_periodic_table(self):
        if not self._is_chemistry_subject():
            show_warning(self, "Periodic Table", "Periodic table quick-jump is available for Chemistry only.")
            return

        pdf_path = self._ensure_local_pdf()
        if not pdf_path or not os.path.exists(pdf_path):
            show_warning(self, "Periodic Table", "No PDF is loaded.")
            return

        if pdf_path in self._periodic_page_cache:
            cached_page = self._periodic_page_cache.get(pdf_path)
            if cached_page:
                if hasattr(self, "pdf_viewer") and self.pdf_viewer:
                    try:
                        self.pdf_viewer.auto_rotate_page_if_landscape(max(0, int(cached_page) - 1), warn_if_unsupported=True)
                    except Exception:
                        pass
                self.on_question_jump_requested("periodic", int(cached_page))
                self.grade_status_label.setText(f"Periodic table found on page {cached_page}")
            else:
                self.grade_status_label.setText("Periodic table not detected; choose page manually")
                self._open_periodic_page_selector(pdf_path)
            return

        if self._periodic_lookup_worker and self._periodic_lookup_worker.isRunning():
            return

        self.grade_status_label.setText("Searching for periodic table...")
        periodic_control = (
            self.periodic_icon_btn
            or self.utility_drawer_periodic_btn
            or self.periodic_button
            or self.additional_tools_periodic_action
        )
        if periodic_control:
            periodic_control.setEnabled(False)

        self._periodic_lookup_worker = PeriodicLookupWorker(pdf_path)
        self._periodic_lookup_worker.finished_lookup.connect(self._on_periodic_lookup_finished)
        self._periodic_lookup_worker.finished.connect(self._on_periodic_lookup_thread_done)
        self._periodic_lookup_worker.finished.connect(self._periodic_lookup_worker.deleteLater)
        self._periodic_lookup_worker.start()

    def _on_periodic_lookup_thread_done(self):
        periodic_control = (
            self.periodic_icon_btn
            or self.utility_drawer_periodic_btn
            or self.periodic_button
            or self.additional_tools_periodic_action
        )
        if periodic_control:
            periodic_control.setEnabled(True)
        self._periodic_lookup_worker = None
        self._sync_utility_drawer_button_states()
        self._refresh_additional_tools_menu_state()

    def _on_periodic_lookup_finished(self, pdf_path: str, page: object, error_message: str):
        if error_message:
            show_warning(self, "Periodic Table", f"Lookup failed: {error_message}")
            self._periodic_page_cache[pdf_path] = None
            self.grade_status_label.setText("Periodic table not detected; choose page manually")
            self._open_periodic_page_selector(pdf_path)
            return

        detected_page = int(page) if isinstance(page, int) and page > 0 else None
        self._periodic_page_cache[pdf_path] = detected_page
        if detected_page:
            if hasattr(self, "pdf_viewer") and self.pdf_viewer:
                try:
                    self.pdf_viewer.auto_rotate_page_if_landscape(max(0, int(detected_page) - 1), warn_if_unsupported=True)
                except Exception:
                    pass
            self.on_question_jump_requested("periodic", detected_page)
            self.grade_status_label.setText(f"Periodic table found on page {detected_page}")
        else:
            self.grade_status_label.setText("Periodic table not detected; choose page manually")
            self._open_periodic_page_selector(pdf_path)

    def _open_periodic_page_selector(self, pdf_path: str):
        snippets = self._periodic_snippets_cache.get(pdf_path)
        if snippets is None:
            snippets = build_page_snippets(pdf_path)
            self._periodic_snippets_cache[pdf_path] = snippets

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Periodic Table Page")
        dialog.resize(680, 420)
        dialog.setModal(False)
        self._apply_selection_dialog_translucent_style(dialog)

        root = QVBoxLayout(dialog)
        label = QLabel("Periodic table page was not detected automatically. Select a page:")
        label.setWordWrap(True)
        root.addWidget(label)

        list_widget = QListWidget()
        for page_num, snippet in snippets:
            item = QListWidgetItem(f"Page {page_num}: {snippet}")
            item.setData(Qt.ItemDataRole.UserRole, page_num)
            list_widget.addItem(item)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        root.addWidget(list_widget)

        remember_cb = QCheckBox("Remember selected page for this session")
        remember_cb.setChecked(True)
        root.addWidget(remember_cb)

        btn_row = QHBoxLayout()
        jump_btn = QPushButton("Jump")
        close_btn = QPushButton("Close")
        btn_row.addStretch(1)
        btn_row.addWidget(jump_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        def _jump_selected():
            item = list_widget.currentItem()
            if not item:
                return
            page_num = item.data(Qt.ItemDataRole.UserRole)
            try:
                page_num = int(page_num)
            except Exception:
                return
            if hasattr(self, "pdf_viewer") and self.pdf_viewer:
                try:
                    self.pdf_viewer.auto_rotate_page_if_landscape(max(0, page_num - 1), warn_if_unsupported=True)
                except Exception:
                    pass
            self.on_question_jump_requested("periodic", page_num)
            self.grade_status_label.setText(f"Jumped to page {page_num}")
            if remember_cb.isChecked():
                self._periodic_page_cache[pdf_path] = page_num
            dialog.close()

        jump_btn.clicked.connect(_jump_selected)
        close_btn.clicked.connect(dialog.close)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show()

    def setup_ui(self):
        central = StaticThemeSurface()
        self._central_widget = central
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # Top bar
        self.top_bar = QFrame()
        top_shell_layout = QHBoxLayout(self.top_bar)
        top_shell_layout.setContentsMargins(0, 0, 0, 0)
        top_shell_layout.setSpacing(0)
        self.top_bar_pill = QFrame(self.top_bar)
        self.top_bar_pill.setObjectName("examTopPill")
        top_layout = QHBoxLayout(self.top_bar_pill)
        top_layout.setContentsMargins(10, 6, 10, 6)
        top_layout.setSpacing(10)
        self.timer_label = QLabel("00:00")
        self.timer_label.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.timer_label.setObjectName("examTimer")
        self.timer_label.setMinimumWidth(self.timer_label.fontMetrics().horizontalAdvance("000:00") + 20)
        self.timer_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.timer_label.setStyleSheet(f"color: {Colors.SUCCESS};")

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumWidth(78)
        self.pause_btn.clicked.connect(self.toggle_pause)

        self.end_btn = QPushButton("End Exam")
        self.end_btn.setMinimumWidth(104)
        self.end_btn.setStyleSheet(
            f"background-color: {Colors.ERROR}; color: {_contrast_text_for_bg(Colors.ERROR)};"
        )
        self.end_btn.clicked.connect(self.end_exam)

        self.reset_layout_btn = None
        self.calculator_toggle_btn = None
        theme_names = self._theme_manager.theme_names()
        self.additional_tools_btn = QPushButton("🛠 Tools")
        self.additional_tools_btn.setMinimumWidth(96)
        self.additional_tools_btn.setToolTip("Toggle utility drawer")
        self.additional_tools_btn.clicked.connect(self._show_additional_tools_menu)
        self.additional_tools_menu = QMenu(self.additional_tools_btn)
        self.exam_settings_btn = QPushButton("Settings")
        self.exam_settings_btn.setMinimumWidth(92)
        self.exam_settings_btn.setToolTip("Open exam settings")
        self.exam_settings_btn.clicked.connect(self._show_exam_settings_window)
        self.periodic_button = None
        self.question_navigator_btn = QPushButton("Navigator")
        self.question_navigator_btn.setMinimumWidth(92)
        self.question_navigator_btn.clicked.connect(self._open_question_navigator_panel)
        self.focus_mode_btn = QPushButton("Focus Mode")
        self.focus_mode_btn.setMinimumWidth(98)
        self.focus_mode_btn.clicked.connect(self._toggle_focus_mode)

        self.submit_btn = QPushButton("Submit")
        self.submit_btn.setMinimumWidth(108)
        self.submit_btn.setStyleSheet(self._submit_button_style())
        self.submit_btn.clicked.connect(self.open_submit_review_page)
        self.grading_mode_btn = QPushButton("Grading")
        self.grading_mode_btn.setMinimumWidth(92)
        self.grading_mode_btn.clicked.connect(self._show_grading_mode_menu)
        self._build_grading_mode_menu()
        self.pdf_source_toggle_btn = QPushButton("View Mark Scheme")
        self.pdf_source_toggle_btn.clicked.connect(self._toggle_pdf_source_view)
        self.pdf_source_toggle_btn.setVisible(False)
        self.paper_insert_toggle_btn = QPushButton("View Insert")
        self.paper_insert_toggle_btn.clicked.connect(self._toggle_question_insert_view)
        self.paper_insert_toggle_btn.setVisible(False)
        self.insert_split_view_btn = QPushButton("Split View")
        self.insert_split_view_btn.setMinimumWidth(96)
        self.insert_split_view_btn.clicked.connect(self._open_insert_split_view)
        self.insert_split_view_btn.setToolTip("Show Question Paper and Insert side-by-side")
        self.insert_split_view_btn.setVisible(False)
        self.pdf_source_selector = QComboBox()
        self.pdf_source_selector.setMinimumWidth(178)
        self.pdf_source_selector.setVisible(False)
        self.pdf_source_selector.currentIndexChanged.connect(self._on_pdf_source_selector_changed)
        self.insert_page_mode_label = None
        self.insert_page_mode_combo = None
        self.grade_status_label = QLabel("")
        self.grade_status_label.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
        self.grade_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.grade_status_label.setMaximumWidth(420)
        self.grade_progress_bar = QProgressBar()
        self.grade_progress_bar.setVisible(False)
        self.grade_progress_bar.setTextVisible(True)
        self.grade_progress_bar.setFixedWidth(140)
        self.grade_progress_bar.setRange(0, 100)
        self.grade_progress_bar.setValue(0)
        self.grade_progress_bar.setFormat("0%")

        self.download_ms_btn = QPushButton("Download MS")
        self.download_ms_btn.setMinimumWidth(118)
        self.download_ms_btn.clicked.connect(self.download_mark_scheme)

        def _make_top_divider() -> QFrame:
            divider = QFrame(self.top_bar_pill)
            divider.setObjectName("examTopDivider")
            divider.setFrameShape(QFrame.Shape.VLine)
            divider.setFrameShadow(QFrame.Shadow.Plain)
            divider.setFixedHeight(24)
            return divider

        left_zone = QWidget()
        left_layout = QHBoxLayout(left_zone)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.paper_info_btn = QPushButton("ℹ")
        self.paper_info_btn.setToolTip("Paper details")
        self.paper_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paper_info_btn.setMinimumWidth(40)
        self.paper_info_btn.setMaximumWidth(48)
        self.paper_info_btn.setMinimumHeight(34)
        self.paper_info_btn.clicked.connect(self._show_paper_info_popover)
        left_layout.addWidget(self.paper_info_btn)
        left_layout.addWidget(self.timer_label)
        left_layout.addWidget(self.pause_btn)

        center_zone = QWidget()
        center_layout = QHBoxLayout(center_zone)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)
        center_layout.addWidget(self.pdf_source_selector)
        center_layout.addWidget(self.insert_split_view_btn)
        center_layout.addWidget(self.download_ms_btn)

        utility_zone = QWidget()
        utility_layout = QHBoxLayout(utility_zone)
        utility_layout.setContentsMargins(0, 0, 0, 0)
        utility_layout.setSpacing(6)
        utility_layout.addWidget(self.question_navigator_btn)
        utility_layout.addWidget(self.focus_mode_btn)
        utility_layout.addWidget(self.additional_tools_btn)
        utility_layout.addWidget(self.exam_settings_btn)

        right_zone = QWidget()
        right_layout = QHBoxLayout(right_zone)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.grading_mode_btn)
        right_layout.addWidget(self.submit_btn)
        right_layout.addWidget(self.end_btn)

        top_layout.addWidget(left_zone, 0)
        top_layout.addWidget(_make_top_divider(), 0)
        top_layout.addWidget(center_zone, 0)
        top_layout.addWidget(_make_top_divider(), 0)
        top_layout.addWidget(utility_zone, 0)
        top_layout.addStretch(1)
        top_layout.addWidget(right_zone, 0)
        top_shell_layout.addStretch(1)
        top_shell_layout.addWidget(self.top_bar_pill, 0, Qt.AlignmentFlag.AlignCenter)
        top_shell_layout.addStretch(1)
        self._build_utility_drawer()

        layout.addWidget(self.top_bar)

        self.split_global_controls_zone = QWidget()
        split_row_layout = QHBoxLayout(self.split_global_controls_zone)
        split_row_layout.setContentsMargins(0, 2, 0, 0)
        split_row_layout.setSpacing(0)
        split_row_layout.addStretch(1)

        split_controls_host = QWidget()
        split_controls_layout = QHBoxLayout(split_controls_host)
        split_controls_layout.setContentsMargins(0, 0, 0, 0)
        split_controls_layout.setSpacing(6)

        self.split_mode_toggle_btn = QPushButton("Single View")
        self.split_mode_toggle_btn.setToolTip("Leave split view")
        self.split_mode_toggle_btn.clicked.connect(self._open_insert_split_view)
        self.split_nav_prev_btn = QPushButton("Page Up")
        self.split_nav_prev_btn.setToolTip("Previous page in both split panes")
        self.split_nav_prev_btn.clicked.connect(self._split_global_prev_page)
        self.split_nav_next_btn = QPushButton("Page Down")
        self.split_nav_next_btn.setToolTip("Next page in both split panes")
        self.split_nav_next_btn.clicked.connect(self._split_global_next_page)
        self.split_zoom_out_btn = QPushButton("Zoom -")
        self.split_zoom_out_btn.setToolTip("Zoom out both split panes")
        self.split_zoom_out_btn.clicked.connect(self._split_global_zoom_out)
        self.split_zoom_in_btn = QPushButton("Zoom +")
        self.split_zoom_in_btn.setToolTip("Zoom in both split panes")
        self.split_zoom_in_btn.clicked.connect(self._split_global_zoom_in)
        self.split_rotate_ccw_btn = QPushButton("Rotate -90")
        self.split_rotate_ccw_btn.setToolTip("Rotate both split panes left")
        self.split_rotate_ccw_btn.clicked.connect(self._split_global_rotate_ccw)
        self.split_rotate_cw_btn = QPushButton("Rotate +90")
        self.split_rotate_cw_btn.setToolTip("Rotate both split panes right")
        self.split_rotate_cw_btn.clicked.connect(self._split_global_rotate_cw)
        for split_btn in [
            self.split_mode_toggle_btn,
            self.split_nav_prev_btn,
            self.split_nav_next_btn,
            self.split_zoom_out_btn,
            self.split_zoom_in_btn,
            self.split_rotate_ccw_btn,
            self.split_rotate_cw_btn,
        ]:
            split_btn.setMinimumHeight(30)

        split_controls_layout.addWidget(self.split_mode_toggle_btn)
        split_controls_layout.addWidget(self.split_nav_prev_btn)
        split_controls_layout.addWidget(self.split_nav_next_btn)
        split_controls_layout.addWidget(self.split_zoom_out_btn)
        split_controls_layout.addWidget(self.split_zoom_in_btn)
        split_controls_layout.addWidget(self.split_rotate_ccw_btn)
        split_controls_layout.addWidget(self.split_rotate_cw_btn)

        split_row_layout.addWidget(split_controls_host, 0)
        split_row_layout.addStretch(1)
        self.split_global_controls_zone.setVisible(False)
        layout.addWidget(self.split_global_controls_zone)

        grading_status_row = QHBoxLayout()
        grading_status_row.setContentsMargins(0, 0, 0, 0)
        grading_status_row.setSpacing(8)
        grading_status_row.addWidget(self.grade_status_label, 1)
        grading_status_row.addWidget(self.grade_progress_bar)
        layout.addLayout(grading_status_row)

        self.paper_info_label = QLabel(self._paper_metadata_line())
        self.paper_info_label.setWordWrap(True)
        self.paper_info_label.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
        self.paper_info_label.setVisible(False)

        self.exam_stack = QStackedWidget()
        self.exam_page = QWidget()
        self.submit_review_page = self._build_submit_review_page()
        self.grading_report_page = self._build_grading_report_page()

        exam_page_layout = QVBoxLayout(self.exam_page)
        exam_page_layout.setContentsMargins(0, 0, 0, 0)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        exam_page_layout.addLayout(content, 1)

        self.exam_stack.addWidget(self.exam_page)
        self.exam_stack.addWidget(self.submit_review_page)
        self.exam_stack.addWidget(self.grading_report_page)
        layout.addWidget(self.exam_stack, 1)

        decision = self.paper_mode_decision
        if decision.mode == "VIEWER_ONLY":
            self.setup_viewer_only_mode(content, decision.viewer_only_reason)
            if self.submit_btn:
                self.submit_btn.setEnabled(False)
            if self.grade_btn:
                self.grade_btn.setEnabled(False)
                self.grade_btn.setVisible(False)
            if self.manual_grade_btn:
                self.manual_grade_btn.setEnabled(False)
                self.manual_grade_btn.setVisible(False)
            if self.grading_mode_btn:
                self.grading_mode_btn.setVisible(False)
            if self.grading_mode_cancel_action:
                self.grading_mode_cancel_action.setEnabled(False)
            if self.grading_mode_mapping_action:
                self.grading_mode_mapping_action.setEnabled(False)
            if decision.viewer_only_reason:
                self.grade_status_label.setText("Viewer-only mode")
        elif decision.mode == "MCQ_ONLY":
            self.setup_mcq_mode(content)
        elif decision.mode == "MIXED":
            self.setup_mixed_mode(content)
        elif decision.mode == "WRITTEN_ONLY":
            self.setup_ai_grading_mode(content)
        else:
            self.setup_written_mode(content)
        if self.manual_grading_only and decision.mode != "VIEWER_ONLY":
            self._apply_manual_grading_only_mode()
        self._apply_movable_ruler_state_to_viewers()
        self._apply_question_scale_state_to_viewers()
        self._install_pdf_quick_tool_buttons()
        self._refresh_additional_tools_menu_state()
        self._update_pdf_source_toggle()
        self._update_split_global_controls_visibility()
        self._update_grading_action_visibility()

        self._sync_settings_window_state()

    def _theme_combo_popup_width(self, combo: Optional[QComboBox] = None) -> int:
        target = combo or self.__dict__.get("theme_combo")
        if not target:
            return 240
        metrics = target.fontMetrics()
        longest = max((metrics.horizontalAdvance(target.itemText(i)) for i in range(target.count())), default=0)
        return max(240, int(target.minimumWidth()), int(longest) + 72)

    def _configure_theme_combo_popup(self, combo: Optional[QComboBox] = None) -> None:
        target = combo or self.__dict__.get("theme_combo")
        if not target:
            return
        target.setMinimumContentsLength(14)
        target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        target.setMaxVisibleItems(18)
        if not bool(target.property("_theme_search_configured")):
            target.setEditable(True)
            target.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            line_edit = target.lineEdit()
            if line_edit is not None:
                line_edit.setPlaceholderText("Search themes...")
                line_edit.setClearButtonEnabled(True)
                line_edit.editingFinished.connect(self._commit_theme_combo_text)

            names = [target.itemText(i) for i in range(target.count())]
            completer_model = QStringListModel(names, target)
            completer = QCompleter(completer_model, target)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            target.setCompleter(completer)
            target.setProperty("_theme_search_configured", True)

        view = target.view()
        if view is None:
            return
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setWordWrap(False)
        view.setMinimumWidth(self._theme_combo_popup_width(target))
        popup_width = self._theme_combo_popup_width(target)
        popup = view.window()
        if popup is not None:
            popup.setMinimumWidth(popup_width)

    def _set_theme_combo_value(self, theme_name: str) -> None:
        combo = self.__dict__.get("theme_combo")
        if not combo:
            return
        self._configure_theme_combo_popup(combo)
        index = combo.findText(theme_name)
        if index < 0:
            index = combo.findText("Archive Blue")
        if index < 0:
            index = 0
        was_blocked = combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(was_blocked)

    def _resolve_theme_name_input(self, theme_name: str) -> Optional[str]:
        candidate = str(theme_name or "").strip()
        if not candidate:
            return None

        manager = self._theme_manager
        if not hasattr(manager, "has_theme"):
            return candidate

        if manager.has_theme(candidate):
            return candidate

        lowered = candidate.casefold()
        for known in manager.theme_names():
            if str(known).casefold() == lowered:
                return str(known)

        aliases = getattr(manager, "THEME_ALIASES", {})
        if isinstance(aliases, dict):
            for alias in aliases.keys():
                if str(alias).casefold() == lowered:
                    return str(alias)
        return None

    def _commit_theme_combo_text(self) -> None:
        combo = self.__dict__.get("theme_combo")
        if not combo:
            return
        resolved = self._resolve_theme_name_input(combo.currentText())
        if not resolved:
            self._set_theme_combo_value(str(self._theme_manager.current_theme() or "Archive Blue"))
            return
        self.on_theme_changed_by_user(resolved)

    def _current_theme_name(self) -> str:
        return str(self._theme_manager.current_theme() or "Archive Blue")




    def _should_defer_theme_change(self) -> bool:
        combo = self.__dict__.get("theme_combo")
        if not combo:
            return False
        try:
            view = combo.view()
            return bool(view and view.isVisible())
        except RuntimeError:
            return False

    def _apply_pending_theme_change(self) -> None:
        self._theme_change_queued = False
        pending = str(self._pending_theme_change_name or "").strip()
        self._pending_theme_change_name = None
        if not pending:
            return
        app = QApplication.instance()
        if not app:
            return
        applied = self._theme_manager.apply_theme(app, pending)
        ConfigManager.set_value("ui.theme", applied)
        self._sync_settings_window_state()

    def on_theme_changed_by_user(self, theme_name: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        resolved = self._resolve_theme_name_input(theme_name)
        if not resolved:
            return
        applied = self._theme_manager.apply_theme(app, resolved)
        ConfigManager.set_value("ui.theme", applied)

    def _delete_custom_theme_by_user(self, theme_name: str) -> bool:
        candidate = str(theme_name or "").strip()
        if not candidate:
            return False
        manager = self._theme_manager
        try:
            if not manager.is_custom_theme(candidate):
                return False
        except Exception:
            return False

        removed = False
        try:
            removed = bool(manager.delete_custom_theme(candidate))  # type: ignore[attr-defined]
        except Exception:
            removed = False
        if not removed:
            return False

        current_theme = str(manager.current_theme() or "")
        if current_theme.casefold() == candidate.casefold():
            app = QApplication.instance()
            if app:
                applied = manager.apply_theme(app, ThemeManager.DEFAULT_THEME)
                ConfigManager.set_value("ui.theme", applied)
        self._sync_settings_window_state()
        return True

    def _current_global_font_family(self) -> str:
        if hasattr(self._theme_manager, "global_font_family"):
            try:
                value = str(self._theme_manager.global_font_family() or "").strip()  # type: ignore[attr-defined]
                if value:
                    return value
            except Exception:
                pass
        return ConfigManager.get_ui_font_family()

    def on_font_changed_by_user(self, font_name: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        available_fonts = self.__dict__.get("_available_ui_fonts")
        if not isinstance(available_fonts, list):
            available_fonts = discover_available_ui_fonts()
            self._available_ui_fonts = available_fonts
        selected = sanitize_font_choice(font_name, available_fonts)
        ConfigManager.set_ui_font_family(selected)
        if hasattr(self._theme_manager, "apply_font_override"):
            try:
                self._theme_manager.apply_font_override(app, selected)  # type: ignore[attr-defined]
            except Exception:
                pass
        elif hasattr(self._theme_manager, "set_global_font_family"):
            try:
                self._theme_manager.set_global_font_family(selected)  # type: ignore[attr-defined]
                self._theme_manager.apply_theme(app, self._current_theme_name())
            except Exception:
                pass
        self._sync_settings_window_state()


    def on_sound_toggled(self, enabled: bool) -> None:
        ConfigManager.set_sound_enabled(bool(enabled))
        viewer = getattr(self, "pdf_viewer", None)
        header = getattr(viewer, "audio_header", None) if viewer is not None else None
        if header is not None and hasattr(header, "refresh_sound_state"):
            try:
                header.refresh_sound_state()
            except Exception:
                pass
        self._sync_settings_window_state()

    def on_question_scale_toggled(self, enabled: bool) -> None:
        self._question_scale_visible = bool(enabled)
        ConfigManager.set_value("ui.exam_question_scale", bool(enabled))
        self._apply_question_scale_state_to_viewers()
        self._sync_settings_window_state()

    def on_system_accent_toggled(self, enabled: bool) -> None:
        ConfigManager.set_dashboard_match_system_accent(bool(enabled))
        app = QApplication.instance()
        if app:
            self._theme_manager.apply_theme(app, self._current_theme_name())
        self.apply_runtime_theme(force=True)

    def on_answer_panel_position_changed(self, position: str) -> None:
        normalized = self._normalize_answer_panel_position(position)
        self._answer_panel_position = normalized
        ConfigManager.set_exam_answer_panel_position(normalized)
        self._apply_answer_panel_position_to_splitter(restore_sizes=True)
        self._sync_settings_window_state()

    def _disconnect_theme_signal(self) -> None:
        if not bool(self._theme_signal_connected):
            return
        try:
            self._theme_manager.theme_changed.disconnect(self._on_theme_changed)
        except Exception:
            pass
        self._theme_signal_connected = False

    def _runtime_theme_signature_key(self) -> str:
        return self._current_theme_name()

    def _on_theme_changed(self, theme_name: str) -> None:
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        self.apply_runtime_theme(force=True)


    @staticmethod
    def _submit_button_style() -> str:
        submit_base = ExamModeWindow._mix_colors(Colors.SECONDARY, Colors.BG_MEDIUM, 0.36)
        submit_hover = ExamModeWindow._mix_colors(submit_base, Colors.ACCENT_CYAN, 0.18)
        submit_text = _contrast_text_for_bg(submit_base)
        border_color = ExamModeWindow._mix_colors(submit_base, Colors.BG_DARK, 0.34)
        return (
            "QPushButton {"
            f"background-color: {submit_base};"
            f"color: {submit_text};"
            f"border: 1px solid {border_color};"
            "border-radius: 8px;"
            "padding: 8px 16px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "font-size: 13px;"
            "font-weight: bold;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {submit_hover};"
            f"color: {submit_text};"
            f"border: 1px solid {border_color};"
            "}"
            "QPushButton:pressed {"
            f"background-color: {submit_hover};"
            f"color: {submit_text};"
            f"border: 1px solid {border_color};"
            "padding: 8px 16px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
        )

    @staticmethod
    def _mix_colors(start_hex: str, end_hex: str, ratio: float) -> str:
        start = QColor(start_hex)
        end = QColor(end_hex)
        t = max(0.0, min(1.0, float(ratio)))
        red = int(start.red() + (end.red() - start.red()) * t)
        green = int(start.green() + (end.green() - start.green()) * t)
        blue = int(start.blue() + (end.blue() - start.blue()) * t)
        return QColor(red, green, blue).name().upper()


    @staticmethod
    def _is_qt_object_alive(obj: object) -> bool:
        if obj is None:
            return False
        if shiboken6 is not None:
            try:
                return bool(shiboken6.isValid(obj))
            except Exception:
                pass
        try:
            obj.metaObject()
            return True
        except RuntimeError:
            return False
        except Exception:
            return False

    @staticmethod
    def _create_drop_shadow_effect(
        target_widget: QWidget,
        blur_radius: float,
    ) -> Optional[QGraphicsDropShadowEffect]:
        if target_widget is None:
            return None
        try:
            effect = QGraphicsDropShadowEffect(target_widget)
            effect.setOffset(0, 0)
            effect.setBlurRadius(float(blur_radius))
            return effect
        except RuntimeError:
            return None
        except Exception:
            return None


    def _can_apply_graphics_effect(self, widget: QWidget) -> bool:
        if not self._is_qt_object_alive(widget):
            return False
        try:
            if widget.parent() is None:
                return False
            if widget.isHidden():
                return False
        except Exception:
            return False
        return True

    def _safe_apply_graphics_effect(
        self,
        widget: QWidget,
        effect: Optional[QGraphicsDropShadowEffect],
    ) -> bool:
        if effect is None or not self._is_qt_object_alive(effect):
            return False
        if not self._can_apply_graphics_effect(widget):
            return False
        try:
            widget.setGraphicsEffect(effect)
            return True
        except RuntimeError:
            return False
        except Exception:
            return False


    @staticmethod
    def _is_mcq_option_button(widget: object) -> bool:
        if not isinstance(widget, QPushButton) or not widget.isCheckable():
            return False
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, MCQQuestionnaire):
                return True
            parent = parent.parentWidget()
        return False


    def apply_runtime_theme(self, force: bool = False) -> None:
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return

        signature = self._runtime_theme_signature_key()
        if not force and self._runtime_theme_signature == signature:
            return

        if self._runtime_theme_apply_in_progress:
            self._runtime_theme_reapply_requested = True
            return

        self._runtime_theme_apply_in_progress = True
        self._runtime_theme_signature = signature
        try:
            if self.top_bar:
                self.top_bar.setStyleSheet("QFrame { background: transparent; border: none; }")
            if self.top_bar_pill:
                pill_bg = _mix_hex(Colors.BG_CARD, Colors.BG_MEDIUM, 0.14)
                pill_border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.42)
                self.top_bar_pill.setStyleSheet(
                    "QFrame#examTopPill {"
                    f"background-color: {pill_bg};"
                    f"border: 1px solid {pill_border};"
                    "border-radius: 14px;"
                    "}"
                    "QFrame#examTopDivider {"
                    f"background-color: {_mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.64)};"
                    "border: none;"
                    "}"
                )
            if self.utility_drawer:
                drawer_bg = _mix_hex(Colors.BG_CARD, Colors.BG_MEDIUM, 0.22)
                drawer_border = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.52)
                self.utility_drawer.setStyleSheet(
                    "QFrame#examUtilityDrawer {"
                    f"background-color: {drawer_bg};"
                    f"border: 1px solid {drawer_border};"
                    "border-radius: 9px;"
                    "}"
                )
            self._apply_timer_visual_state()
            utility_base = _mix_hex(Colors.BG_LIGHT, Colors.BG_CARD, 0.16)
            secondary_base = _mix_hex(Colors.ACCENT_CYAN, Colors.BG_MEDIUM, 0.52)
            if self.end_btn:
                self.end_btn.setStyleSheet(
                    f"background-color: {Colors.ERROR}; color: {_contrast_text_for_bg(Colors.ERROR)};"
                )
            if self.submit_btn:
                submit_base = secondary_base
                self.submit_btn.setStyleSheet(self._submit_button_style())
            if self.grade_btn:
                self.grade_btn.setStyleSheet(
                    f"background-color: {Colors.SECONDARY}; color: {_contrast_text_for_bg(Colors.SECONDARY)};"
                )
            if self.manual_grade_btn:
                self.manual_grade_btn.setStyleSheet(
                    f"background-color: {Colors.PRIMARY}; color: {_contrast_text_for_bg(Colors.PRIMARY)};"
                )
            if self.grade_status_label:
                self.grade_status_label.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
            if self.paper_info_btn:
                self.paper_info_btn.setStyleSheet(
                    f"background-color: {Colors.BG_LIGHT};"
                    f"color: {_contrast_text_for_bg(Colors.BG_LIGHT)};"
                    f"border: 1px solid {Colors.BG_MEDIUM};"
                    "border-radius: 10px;"
                    "font-weight: 700;"
                    "font-size: 24px;"
                    "min-height: 34px;"
                    "min-width: 46px;"
                )
            if self.paper_info_label:
                self.paper_info_label.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
            if self.theme_label:
                self.theme_label.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
            if self.submit_review_subtitle:
                self.submit_review_subtitle.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
            if self.submit_answered_count_label:
                self.submit_answered_count_label.setStyleSheet(f"color: {Colors.TEXT_LIGHT}; font-size: 14px;")
            if self.submit_unanswered_count_label:
                self.submit_unanswered_count_label.setStyleSheet(f"color: {Colors.TEXT_LIGHT}; font-size: 14px;")
            self._apply_splitter_theme()
            self._refresh_pdf_quick_tool_styles()
            for viewer in self._iter_insert_page_mode_viewers():
                try:
                    viewer.apply_runtime_theme()
                except Exception:
                    pass
            if self.notes_widget is not None:
                self.notes_widget.apply_runtime_theme()

            if hasattr(self, "questionnaire") and self.questionnaire and hasattr(self.questionnaire, "apply_runtime_theme"):
                try:
                    self.questionnaire.apply_runtime_theme()
                except Exception:
                    pass
            if self.calculator_widget and hasattr(self.calculator_widget, "apply_runtime_theme"):
                try:
                    self.calculator_widget.apply_runtime_theme()
                except Exception:
                    pass
            if self.manual_grading_panel is not None:
                try:
                    self.manual_grading_panel.apply_runtime_theme()
                except Exception:
                    pass

            if (
                self.submit_review_page
                and self.exam_stack
                and self.exam_stack.currentWidget() is self.submit_review_page
            ):
                self._refresh_submit_review_grid()
            self._refresh_utility_drawer_geometry(animate=False)
            self._sync_settings_window_state()
        finally:
            self._runtime_theme_apply_in_progress = False
            if self._runtime_theme_reapply_requested and not (self._graceful_exit_in_progress or self._graceful_exit_finalizing):
                self._runtime_theme_reapply_requested = False
                QTimer.singleShot(0, lambda: self.apply_runtime_theme(force=True))

        if self._studio_workspace is not None:
            self._studio_workspace.refresh_theme()

    def _build_submit_review_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        heading = QLabel("Submission Review")
        heading.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        root.addWidget(heading)

        self.submit_review_title_label = heading
        self.submit_review_subtitle = QLabel("Check answered and blank questions before starting auto-grade.")
        self.submit_review_subtitle.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
        root.addWidget(self.submit_review_subtitle)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(16)
        self.submit_answered_count_label = QLabel("Questions answered: 0")
        self.submit_answered_count_label.setStyleSheet(f"color: {Colors.TEXT_LIGHT}; font-size: 14px;")
        self.submit_unanswered_count_label = QLabel("questions unanswered: 0")
        self.submit_unanswered_count_label.setStyleSheet(f"color: {Colors.TEXT_LIGHT}; font-size: 14px;")
        summary_row.addWidget(self.submit_answered_count_label)
        summary_row.addWidget(self.submit_unanswered_count_label)
        summary_row.addStretch(1)
        root.addLayout(summary_row)

        legend_row = QHBoxLayout()
        legend_row.setContentsMargins(0, 0, 0, 0)
        legend_row.setSpacing(14)

        def _legend_chip(color: str, label_text: str, text_color: str = "#0f172a") -> QWidget:
            chip = QWidget()
            chip_row = QHBoxLayout(chip)
            chip_row.setContentsMargins(0, 0, 0, 0)
            chip_row.setSpacing(8)
            square = QLabel("")
            square.setFixedSize(18, 18)
            square.setStyleSheet(
                f"background-color: {color}; border-radius: 5px; border: 1px solid #d1d5db;"
            )
            text = QLabel(label_text)
            text.setStyleSheet(f"color: {text_color};")
            chip_row.addWidget(square)
            chip_row.addWidget(text)
            return chip

        legend_row.addWidget(_legend_chip("#F59E0B", "completed questions", text_color=Colors.TEXT_LIGHT))
        legend_row.addWidget(_legend_chip("#FFFFFF", "questions left blank", text_color=Colors.TEXT_LIGHT))
        legend_row.addStretch(1)
        root.addLayout(legend_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_host = QWidget()
        self.submit_review_grid = QGridLayout(scroll_host)
        self.submit_review_grid.setContentsMargins(4, 4, 4, 4)
        self.submit_review_grid.setHorizontalSpacing(10)
        self.submit_review_grid.setVerticalSpacing(10)
        self.submit_review_grid_container = scroll_host
        scroll.setWidget(scroll_host)
        self.submit_review_scroll = scroll
        self.submit_review_scroll.setVisible(False)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.submit_back_btn = QPushButton("Back to Exam")
        self.submit_back_btn.clicked.connect(self._go_back_to_exam_page)
        self.grade_btn = QPushButton("Auto-Grade")
        self.grade_btn.setStyleSheet(
            f"background-color: {Colors.SECONDARY}; color: {_contrast_text_for_bg(Colors.SECONDARY)};"
        )
        self.grade_btn.clicked.connect(self._start_autograde_from_submit_page)
        self.manual_grade_btn = QPushButton("Manual Grade")
        self.manual_grade_btn.clicked.connect(self._start_manual_grade_from_submit_page)
        actions.addStretch(1)
        actions.addWidget(self.submit_back_btn)
        actions.addWidget(self.grade_btn)
        actions.addWidget(self.manual_grade_btn)
        root.addLayout(actions)
        return page

    def _build_grading_report_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Grading Report")
        title.setStyleSheet(f"color: {Colors.TEXT_WHITE}; font-size: 24px; font-weight: 700;")
        root.addWidget(title)
        self.grading_report_title_label = title

        meta = QLabel("")
        meta.setStyleSheet(f"color: {Colors.TEXT_GRAY}; font-size: 13px;")
        root.addWidget(meta)
        self.grading_report_meta_label = meta

        browser = QTextBrowser()
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {Colors.BG_CARD}; color: {Colors.TEXT_LIGHT}; "
            f"border: 1px solid {Colors.BG_DARK}; border-radius: 10px; padding: 10px; }}"
        )
        root.addWidget(browser, 1)
        self.grading_report_browser = browser

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        save_btn = QPushButton("Save As")
        save_btn.clicked.connect(self._save_current_grading_report)
        exit_btn = QPushButton("Exit Exam")
        exit_btn.setStyleSheet(
            f"background-color: {Colors.ERROR}; color: {_contrast_text_for_bg(Colors.ERROR)};"
        )
        exit_btn.clicked.connect(self.graceful_exit)
        actions.addStretch(1)
        actions.addWidget(save_btn)
        actions.addWidget(exit_btn)
        root.addLayout(actions)
        self.grading_report_save_btn = save_btn
        self.grading_report_exit_btn = exit_btn
        return page

    def _set_questionnaire_editable(self, editable: bool) -> None:
        questionnaire = getattr(self, "questionnaire", None)
        if questionnaire is None:
            return

        if hasattr(questionnaire, "set_answer_inputs_enabled"):
            try:
                questionnaire.set_answer_inputs_enabled(bool(editable))
                return
            except Exception:
                pass

        if hasattr(questionnaire, "set_enabled"):
            try:
                questionnaire.set_enabled(bool(editable))
                return
            except Exception:
                pass

        for editor in questionnaire.findChildren(QPlainTextEdit):
            editor.setReadOnly(not editable)
            editor.setEnabled(True)
        for editor in questionnaire.findChildren(QTextEdit):
            editor.setReadOnly(not editable)
            editor.setEnabled(True)
        for line_edit in questionnaire.findChildren(QLineEdit):
            line_edit.setReadOnly(not editable)
            line_edit.setEnabled(True)
        for combo in questionnaire.findChildren(QComboBox):
            combo.setEnabled(bool(editable))

    def _lock_submission_and_answers(self) -> None:
        if not self._submission_locked_for_autograde:
            self._submission_locked_for_autograde = True
            self._autograde_submitted_at = self._autograde_submitted_at or datetime.now()
        self._set_questionnaire_editable(False)
        if self.submit_btn:
            self.submit_btn.setVisible(False)
            self.submit_btn.setEnabled(False)
        self._update_grading_action_visibility()

    def _save_current_grading_report(self) -> None:
        report_path = str(self._current_grading_report_path or "").strip()
        if not report_path or not os.path.exists(report_path):
            show_warning(self, "Grading Report", "No grading report is available to save.")
            return
        self._prompt_grading_report_export(report_path)

    def _prompt_grading_report_export(self, report_path: str) -> Optional[str]:
        path = str(report_path or "").strip()
        if not path or not os.path.exists(path):
            return None

        parent_directory = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder for Grading Report",
            self._desktop_download_dir(),
        )
        parent = str(parent_directory or "").strip()
        if not parent:
            return None

        try:
            target = self._export_grading_report_into_folder(path, parent)
        except Exception as exc:
            show_warning(self, "Grading Report", f"Could not save grading report.\n{exc}")
            return None

        if target:
            show_download_complete_dialog(
                self,
                "Grading Report Saved",
                target,
                message_prefix="Grading report saved to",
            )
        return target

    def _export_grading_report_into_folder(self, report_path: str, parent_directory: str) -> Optional[str]:
        path = str(report_path or "").strip()
        parent = str(parent_directory or "").strip()
        if not path or not os.path.exists(path):
            return None
        if not parent or not os.path.isdir(parent):
            return None

        submitted_at = self._autograde_submitted_at or datetime.now()
        self._autograde_submitted_at = submitted_at
        timestamp = submitted_at.strftime("%Y-%m-%d %H-%M-%S")
        paper_code = str(self._derive_paper_code_for_attempt() or "paper").strip()
        safe_paper_code = re.sub(r"[^A-Za-z0-9._-]+", "_", paper_code).strip("._") or "paper"
        folder_name = f"Grading report: {safe_paper_code} {timestamp}"
        safe_folder_name = re.sub(r'[<>"/\\\\|?*]+', "_", folder_name).strip() or f"Grading report {timestamp}"
        output_dir = self._next_available_path(parent, safe_folder_name)
        os.makedirs(output_dir, exist_ok=False)

        base_name = os.path.basename(path) or "grading_report.md"
        safe_base_name = re.sub(r'[<>:"/\\\\|?*]+', "_", base_name).strip("._") or "grading_report.md"
        target_path = os.path.join(output_dir, safe_base_name)
        shutil.copy2(path, target_path)
        return target_path

    def _open_embedded_grading_report(self, report_path: str) -> None:
        path = str(report_path or "").strip()
        if not path or not os.path.exists(path):
            show_warning(self, "Grading Report", "Grading report file is unavailable.")
            return

        try:
            report_text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            show_warning(self, "Grading Report", f"Could not open grading report.\n{exc}")
            return

        self._current_grading_report_path = path
        submitted_at = self._autograde_submitted_at or datetime.now()
        self._autograde_submitted_at = submitted_at
        paper_code = str(self._derive_paper_code_for_attempt() or "").strip()
        submitted_label = submitted_at.strftime("%Y-%m-%d %H:%M:%S")
        if self.grading_report_title_label:
            suffix = f" - {paper_code}" if paper_code else ""
            self.grading_report_title_label.setText(f"Grading Report{suffix}")
        if self.grading_report_meta_label:
            self.grading_report_meta_label.setText(f"Submitted: {submitted_label}")
        if self.grading_report_browser:
            if path.lower().endswith(".md"):
                self.grading_report_browser.setMarkdown(report_text)
            else:
                self.grading_report_browser.setPlainText(report_text)

        if self.exam_stack and self.grading_report_page:
            self.exam_stack.setCurrentWidget(self.grading_report_page)

    def _question_label_order(self) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        local_state = getattr(self, "__dict__", {})

        def _append_labels(values: List[Any]) -> None:
            for raw in values:
                normalized = normalize_question_id(str(raw))
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    ordered.append(normalized)

        raw_question_ids = local_state.get("question_ids")
        if raw_question_ids:
            _append_labels([str(q) for q in raw_question_ids])

        questionnaire = local_state.get("questionnaire")
        if questionnaire and hasattr(questionnaire, "visible_question_ids"):
            try:
                visible = list(getattr(questionnaire, "visible_question_ids")())
                _append_labels([str(q) for q in visible])
            except Exception:
                pass
        elif questionnaire and hasattr(questionnaire, "question_ids"):
            _append_labels([str(q) for q in list(getattr(questionnaire, "question_ids", []))])

        question_texts = local_state.get("question_texts")
        if isinstance(question_texts, dict):
            _append_labels(list(question_texts.keys()))
        question_marks = local_state.get("question_marks")
        if isinstance(question_marks, dict):
            _append_labels(list(question_marks.keys()))
        answer_key = local_state.get("answer_key")
        if isinstance(answer_key, dict):
            _append_labels(list(answer_key.keys()))

        if questionnaire and hasattr(questionnaire, "get_answers"):
            try:
                payload = questionnaire.get_answers()
                if isinstance(payload, dict):
                    _append_labels(list(payload.keys()))
            except Exception:
                pass

        if questionnaire and hasattr(questionnaire, "num_questions"):
            try:
                count = int(getattr(questionnaire, "num_questions", 0))
                if count > 0:
                    _append_labels([str(i) for i in range(1, count + 1)])
            except Exception:
                pass

        return ordered

    @staticmethod
    def _is_substantive_answer_value(value: Any) -> bool:
        if isinstance(value, dict):
            answer_type = str(value.get("type", "")).strip().lower()
            if answer_type == "drawing":
                # Notes-only drawing responses are considered blank until an image exists.
                return bool(str(value.get("image_path", "")).strip())
            if "value" in value:
                return bool(str(value.get("value", "")).strip())
            return False
        if value is None:
            return False
        if isinstance(value, (list, tuple, set)):
            return any(ExamModeWindow._is_substantive_answer_value(item) for item in value)
        return bool(str(value).strip())

    def _completion_from_answer_payload(self, answers: Any) -> Dict[str, bool]:
        completion: Dict[str, bool] = {}
        if not isinstance(answers, dict):
            return completion
        for q_id, value in answers.items():
            q_norm = normalize_question_id(str(q_id))
            if not q_norm:
                continue
            completion[q_norm] = self._is_substantive_answer_value(value)
        return completion

    def _compute_question_completion_state(self) -> Dict[str, bool]:
        completion: Dict[str, bool] = {}
        labels = self._question_label_order()
        questionnaire = getattr(self, "questionnaire", None)
        if questionnaire:
            if hasattr(questionnaire, "get_completion_state"):
                try:
                    raw = questionnaire.get_completion_state()
                    if isinstance(raw, dict):
                        normalized = {normalize_question_id(k): bool(v) for k, v in raw.items()}
                        completion.update({k: v for k, v in normalized.items() if k})
                except Exception:
                    pass

            if hasattr(questionnaire, "get_answers"):
                try:
                    answers = questionnaire.get_answers()
                except Exception:
                    answers = {}
                completion.update(self._completion_from_answer_payload(answers))

        for q_id in labels:
            completion.setdefault(normalize_question_id(q_id), False)
        if self._studio_workspace is not None:
            return {qid: bool(completion.get(qid, False)) for qid in self._studio_workspace.question_ids()}
        return completion

    def _refresh_submit_review_grid(self) -> None:
        if self._studio_workspace is not None and self.session_state.completed:
            self._studio_workspace.refresh_completed_review()
            return
        completion = self._compute_question_completion_state()
        self._last_question_completion_state = dict(completion)
        ordered_labels = self._question_label_order()
        labels = ordered_labels or list(completion.keys())
        if completion:
            label_set = {normalize_question_id(q) for q in labels if normalize_question_id(q)}
            for q_id in completion.keys():
                q_norm = normalize_question_id(q_id)
                if q_norm and q_norm not in label_set:
                    labels.append(q_norm)
                    label_set.add(q_norm)

        total_questions = len(labels)
        answered_questions = sum(1 for raw_qid in labels if bool(completion.get(normalize_question_id(raw_qid), False)))
        unanswered_questions = max(0, total_questions - answered_questions)

        if self.submit_answered_count_label:
            self.submit_answered_count_label.setText(f"Questions answered: {answered_questions}")
        if self.submit_unanswered_count_label:
            self.submit_unanswered_count_label.setText(f"questions unanswered: {unanswered_questions}")

        if not self.submit_review_grid:
            return
        while self.submit_review_grid.count():
            item = self.submit_review_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not labels:
            placeholder = QLabel("No questions available.")
            placeholder.setStyleSheet(f"color: {Colors.TEXT_GRAY}; padding: 8px;")
            self.submit_review_grid.addWidget(placeholder, 0, 0)
            return

        cols = 8
        for idx, raw_qid in enumerate(labels):
            qid = normalize_question_id(raw_qid)
            answered = bool(completion.get(qid, False))
            tile = QFrame()
            bg = "#F59E0B" if answered else "#FFFFFF"
            fg = _contrast_text_for_bg(bg)
            tile.setFixedSize(64, 64)
            tile.setStyleSheet(
                f"QFrame {{ background-color: {bg}; border-radius: 10px; border: 1px solid #d1d5db; }}"
            )
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(4, 4, 4, 4)
            tile_layout.setSpacing(0)
            label = QLabel(format_question_display(qid))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color: {fg}; font-weight: bold;")
            tile_layout.addWidget(label)
            confidence = QComboBox(tile)
            confidence.addItems(["Confidence: low", "Confidence: medium", "Confidence: high"])
            current = str(self.question_confidence.get(qid, "medium")).lower()
            confidence.setCurrentIndex({"low": 0, "medium": 1, "high": 2}.get(current, 1))
            confidence.currentIndexChanged.connect(
                lambda i, q=qid: self.question_confidence.__setitem__(q, ("low", "medium", "high")[max(0, min(2, int(i)))])
            )
            tile_layout.addWidget(confidence)
            reviewed_cb = QCheckBox("Reviewed", tile)
            reviewed_cb.setChecked(qid in self.question_reviewed)
            reviewed_cb.toggled.connect(
                lambda checked, q=qid: (self.question_reviewed.add(q) if checked else self.question_reviewed.discard(q))
            )
            tile_layout.addWidget(reviewed_cb)
            row = idx // cols
            col = idx % cols
            self.submit_review_grid.addWidget(tile, row, col)

        if self.submit_review_grid_container:
            self.submit_review_grid_container.adjustSize()
            self.submit_review_grid_container.update()
        self._update_grading_action_visibility()

    def open_submit_review_page(self) -> None:
        if self._studio_workspace is not None and not self.session_state.completed:
            self._studio_workspace.show_finish_review()
            return
        if self._submission_locked_for_autograde:
            show_info(
                self,
                "Submission Locked",
                "This attempt has already been submitted for auto-grade.",
            )
            return
        if self.paper_mode == "VIEWER_ONLY":
            show_warning(
                self,
                "Auto-Grade",
                self.paper_mode_decision.viewer_only_reason or "This paper component is not auto-gradable.",
            )
            return
        self._set_mark_scheme_unlock(True)
        self._set_grading_mode(True)
        self._refresh_submit_review_grid()
        if self.exam_stack and self.submit_review_page:
            self.exam_stack.setCurrentWidget(self.submit_review_page)

    def _go_back_to_exam_page(self) -> None:
        if self.exam_stack and self.exam_page:
            self.exam_stack.setCurrentWidget(self.exam_page)
        self._show_questionnaire_panel()

    def _set_mark_scheme_unlock(self, unlocked: bool) -> None:
        if unlocked and self.session_state.mode == "exam" and not self.session_state.completed:
            return
        self._mark_scheme_view_unlocked = bool(unlocked)
        if not self._mark_scheme_view_unlocked and self._active_pdf_source_key == "mark_scheme":
            self._show_pdf_source("question", emit_signal=False)
        self._rebuild_pdf_source_selector()
        self._update_pdf_source_toggle()
        self._refresh_split_view_labels()

    def _visible_pdf_sources(self) -> List[str]:
        visible = []
        for key in self._available_pdf_sources:
            if key == "mark_scheme" and not self._mark_scheme_view_unlocked:
                continue
            visible.append(key)
        if not visible and self._available_pdf_sources:
            visible = [self._available_pdf_sources[0]]
        return visible

    def _on_grading_mode_toggled(self, enabled: bool) -> None:
        self._set_grading_mode(bool(enabled), update_toggle=False)

    def _set_grading_mode(self, enabled: bool, update_toggle: bool = True) -> None:
        self._grading_mode_enabled = bool(enabled)
        if self.grading_mode_btn:
            self.grading_mode_btn.setText("Grading")
        self._update_grading_action_visibility()

    def _is_exam_ready_for_grading(self) -> bool:
        completion = self._compute_question_completion_state()
        if not completion:
            return False
        return all(bool(done) for done in completion.values())

    def _update_grading_action_visibility(self) -> None:
        ready = self._is_exam_ready_for_grading()
        should_enable_grading_actions = bool(self._grading_mode_enabled or ready or self._grading_in_progress)
        in_exam_mode = self.paper_mode != "VIEWER_ONLY"
        grading_tools_available = in_exam_mode and (not self.manual_grading_only)
        has_submitted = bool(self._mark_scheme_view_unlocked)
        submission_locked = bool(self._submission_locked_for_autograde)

        if self.submit_btn:
            self.submit_btn.setVisible(in_exam_mode and (not submission_locked))
            self.submit_btn.setEnabled(in_exam_mode and (not self._grading_in_progress) and (not submission_locked))

        if self.grading_mode_btn:
            self.grading_mode_btn.setVisible(grading_tools_available and has_submitted)
            self.grading_mode_btn.setEnabled(grading_tools_available and has_submitted)

        has_mapping = bool(self.latest_mapping_report and self.latest_mapping_report.entries)
        if self.grading_mode_mapping_action:
            self.grading_mode_mapping_action.setEnabled(
                grading_tools_available and has_submitted and should_enable_grading_actions and has_mapping and (not self._grading_in_progress)
            )
        if self.grading_mode_cancel_action:
            self.grading_mode_cancel_action.setEnabled(
                grading_tools_available and has_submitted and bool(self._grading_in_progress)
            )

        if self._studio_workspace is not None:
            self._studio_workspace.apply_focus()

    def _show_non_blocking_warning(self, title: str, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(str(title or "Warning"))
        box.setText(str(message or ""))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setModal(False)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._floating_warning_dialogs.append(box)
        box.finished.connect(lambda _=0, dialog=box: self._floating_warning_dialogs.remove(dialog) if dialog in self._floating_warning_dialogs else None)
        box.show()
        box.raise_()
        box.activateWindow()

    def _show_groq_startup_warning_if_needed(self) -> None:
        if not should_show_groq_startup_warning():
            return
        message = (
            f"{groq_missing_warning_message(detailed=True)}\n\n"
            "Core paper search and PDF viewing remain available."
        )
        self._show_non_blocking_warning("Groq API Key Missing", message)

    def _manual_grading_only_warning_message(self) -> str:
        base = groq_missing_warning_message(detailed=True)
        if self.manual_grading_only_reason:
            return f"{base}\n\nDetails: {self.manual_grading_only_reason}"
        return base

    def _apply_manual_grading_only_mode(self) -> None:
        if self.submit_review_subtitle:
            self.submit_review_subtitle.setText("Manual grading only is available for this session.")
        if self.grade_btn:
            self.grade_btn.setEnabled(False)
            self.grade_btn.setText("Auto-Grade (Unavailable)")
            self.grade_btn.setToolTip("Auto-grading requires a valid Groq setup.")
        if self.grading_mode_btn:
            self.grading_mode_btn.setVisible(False)
            self.grading_mode_btn.setEnabled(False)
        if self.grading_mode_mapping_action:
            self.grading_mode_mapping_action.setEnabled(False)
        if self.grading_mode_cancel_action:
            self.grading_mode_cancel_action.setEnabled(False)
        if self.grade_status_label and not str(self.grade_status_label.text() or "").strip():
            self.grade_status_label.setText("Manual grading only (AI unavailable)")

    def _on_exam_answer_changed(self, _q_id: object = None) -> None:
        self._mark_resume_snapshot_dirty()
        if self._studio_workspace is not None:
            self._studio_workspace.answer_changed()
        self._update_grading_action_visibility()
        if self.submit_review_page and self.submit_review_scroll and self.submit_review_scroll.isVisible():
            try:
                self._refresh_submit_review_grid()
            except Exception:
                pass

    def _start_autograde_from_submit_page(self) -> None:
        if self._submission_locked_for_autograde:
            show_info(
                self,
                "Submission Locked",
                "This attempt has already been submitted for auto-grade.",
            )
            return
        if self.manual_grading_only:
            show_warning(self, "Auto-Grade Unavailable", self._manual_grading_only_warning_message())
            return
        self._set_mark_scheme_unlock(True)
        self._set_grading_mode(True)
        self._go_back_to_exam_page()
        self._pdf_source_switch_allowed = True
        self._show_mark_scheme_in_viewer()
        self._update_pdf_source_toggle()
        self.auto_grade_paper()

    def _show_questionnaire_panel(self) -> None:
        stack = self.__dict__.get("answer_content_stack")
        questionnaire = getattr(self, "questionnaire", None)
        if isinstance(stack, QStackedWidget) and questionnaire is not None:
            idx = stack.indexOf(questionnaire)
            if idx >= 0:
                stack.setCurrentIndex(idx)
        self.manual_grading_active = False

    def _show_manual_grading_panel(self) -> None:
        stack = self.__dict__.get("answer_content_stack")
        panel = self._ensure_manual_grading_panel()
        if isinstance(stack, QStackedWidget) and isinstance(panel, ManualGradingPanel):
            idx = stack.indexOf(panel)
            if idx >= 0:
                stack.setCurrentIndex(idx)
                self.manual_grading_active = True

    def _collect_manual_visible_qids(self) -> List[str]:
        qids: List[str] = []
        questionnaire = getattr(self, "questionnaire", None)
        if questionnaire and hasattr(questionnaire, "visible_question_ids"):
            try:
                qids = [normalize_question_id(str(q)) for q in list(questionnaire.visible_question_ids())]
            except Exception:
                qids = []
        if not qids:
            qids = [normalize_question_id(str(q)) for q in self._question_label_order()]

        deduped: List[str] = []
        seen: set[str] = set()
        for qid in qids:
            if not qid or qid in seen:
                continue
            seen.add(qid)
            deduped.append(qid)
        return deduped

    def _format_manual_answer_text(self, payload: Any) -> str:
        if isinstance(payload, dict):
            p_type = str(payload.get("type", "")).strip().lower()
            if p_type == "drawing":
                parts: List[str] = []
                notes = str(payload.get("notes", "") or "").strip()
                image_path = str(payload.get("image_path", "") or "").strip()
                if notes:
                    parts.append(notes)
                if image_path:
                    parts.append(f"[Drawing uploaded: {os.path.basename(image_path)}]")
                return "\n".join(parts).strip() or "(No answer provided)"
            if p_type == "table":
                table_value = str(payload.get("value", "") or "").strip()
                if table_value:
                    return table_value
                cells = payload.get("cells", {})
                if isinstance(cells, dict) and cells:
                    segments = [f"{k}={v}" for k, v in cells.items() if str(v).strip()]
                    return "; ".join(segments).strip() or "(No answer provided)"
                return "(No answer provided)"
            value = str(payload.get("value", "") or "").strip()
            return value or "(No answer provided)"
        text = str(payload or "").strip()
        return text or "(No answer provided)"

    def _load_manual_expanded_key(
        self,
        visible_qids: List[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], str]:
        if not visible_qids:
            return {}, "no visible questions"

        answer_key, source_label = self._load_candidate_answer_key()
        normalized_key = {normalize_question_id(k): dict(v) for k, v in answer_key.items() if normalize_question_id(k)}
        mapper = QuestionIDMapper()
        mapping_report = mapper.generate_mapping(
            visible_qids,
            list(normalized_key.keys()),
            question_order=visible_qids,
            manual_overrides=dict(self.manual_mapping_overrides),
        )
        self.latest_mapping_report = mapping_report
        expanded_key = mapper.expand_answer_key(
            answer_key=normalized_key,
            mapping=mapping_report,
            question_marks={qid: float(self.question_mark_hints.get(qid, 0.0) or 0.0) for qid in visible_qids},
            policy="strict_leaf",
        )
        return expanded_key, source_label

    def _build_manual_grade_rows(self) -> List[ManualGradeRow]:
        visible_qids = self._collect_manual_visible_qids()
        questionnaire = getattr(self, "questionnaire", None)
        answers_payload: Dict[str, Any] = {}
        if questionnaire and hasattr(questionnaire, "get_answers"):
            try:
                raw = questionnaire.get_answers()
                if isinstance(raw, dict):
                    answers_payload = {normalize_question_id(str(k)): v for k, v in raw.items() if normalize_question_id(str(k))}
            except Exception:
                answers_payload = {}

        expanded_key, _source_label = self._load_manual_expanded_key(visible_qids)
        rows: List[ManualGradeRow] = []
        for qid in visible_qids:
            answer_payload = answers_payload.get(qid)
            answer_text = self._format_manual_answer_text(answer_payload)
            key_entry = expanded_key.get(qid, {}) if isinstance(expanded_key, dict) else {}
            mark_scheme_text = str(key_entry.get("mark_scheme_text") or key_entry.get("answer") or "").strip()
            if not mark_scheme_text:
                mark_scheme_text = "No mark scheme text available"
            raw_marks = key_entry.get("max_marks", key_entry.get("marks", self.question_marks.get(qid, 0.0)))
            try:
                max_marks_int = max(0, int(math.floor(float(raw_marks) + 0.5)))
            except Exception:
                max_marks_int = 0
            rows.append(
                ManualGradeRow(
                    qid=qid,
                    display_id=format_question_display(qid),
                    answer_text=answer_text,
                    mark_scheme_text=mark_scheme_text,
                    max_marks_int=max_marks_int,
                )
            )
        return rows

    def _start_manual_grade_from_submit_page(self) -> None:
        if self.paper_mode == "VIEWER_ONLY":
            show_warning(
                self,
                "Manual Grade",
                self.paper_mode_decision.viewer_only_reason or "This paper component is not manually gradable here.",
            )
            return
        self._set_mark_scheme_unlock(True)
        self._set_grading_mode(True)
        self._go_back_to_exam_page()
        self._pdf_source_switch_allowed = True
        if not self._show_mark_scheme_in_viewer():
            self.grade_status_label.setText("Manual grading opened without mark-scheme PDF.")
        rows = self._build_manual_grade_rows()
        panel = self._ensure_manual_grading_panel()
        if isinstance(panel, ManualGradingPanel):
            panel.set_rows(rows)
            panel.set_inputs_enabled(True)
            panel.set_finalize_enabled(bool(rows))
        self.manual_rows_snapshot = rows
        self.manual_grading_finalized = False
        self.manual_grading_active = True
        self._sync_exam_clock()
        self.timer_paused = True
        self._apply_timer_visual_state()
        try:
            self.timer.stop()
        except Exception:
            pass
        self.grade_status_label.setText("Manual grading in progress")
        self._show_manual_grading_panel()

    def _parse_manual_mark_input(self, raw_text: str, max_marks_int: int) -> Tuple[Optional[int], str]:
        text = str(raw_text or "").strip()
        if not text:
            return 0, ""
        if not re.fullmatch(r"\d+", text):
            return None, "Only whole numbers are allowed."
        try:
            parsed = int(text)
        except Exception:
            return None, "Only whole numbers are allowed."
        clamped = max(0, min(int(max_marks_int), parsed))
        return clamped, ""

    def _finalize_manual_grade(self) -> None:
        panel = self.__dict__.get("manual_grading_panel")
        if not isinstance(panel, ManualGradingPanel):
            return
        rows = list(self.manual_rows_snapshot or [])
        if not rows:
            show_warning(self, "Manual Grade", "No visible questions available to finalize.")
            panel.set_finalize_enabled(False)
            return

        invalid_qids: List[str] = []
        earned = 0
        total = 0
        for row in rows:
            total += int(row.max_marks_int)
            raw_text = panel.mark_input_text(row.qid)
            parsed, error = self._parse_manual_mark_input(raw_text, int(row.max_marks_int))
            if error:
                invalid_qids.append(row.display_id)
                panel.set_mark_input_invalid(row.qid, True)
                continue
            panel.set_mark_input_invalid(row.qid, False)
            earned += int(parsed or 0)

        if invalid_qids:
            show_warning(
                self,
                "Manual Grade",
                "Enter whole numbers only. Invalid rows: " + ", ".join(invalid_qids),
            )
            return

        percent = (float(earned) / float(total) * 100.0) if total > 0 else 0.0
        summary = f"Final Score: {earned}/{total} ({percent:.1f}%)"
        panel.show_summary(summary)
        panel.set_inputs_enabled(False)
        panel.set_finalize_enabled(False)
        panel.finalize_btn.setText("Finalized")
        self.manual_grading_finalized = True
        self.manual_grading_active = True
        self._retain_grading_summary({
            'earned_marks': earned, 'total_marks': total, 'pending_manual_count': 0,
        })
        self.grade_status_label.setText(summary)
        if self.results_panel:
            self.results_panel.update_summary(summary)
            self.results_panel.show()

    @staticmethod
    def _has_listening_token(value: str) -> bool:
        text = str(value or "").strip().lower()
        if not text:
            return False
        return bool(re.search(r"(^|[^a-z0-9])listening([^a-z0-9]|$)", text))

    @staticmethod
    def _stem_from_url_or_path(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        source_path = parsed.path if parsed.scheme else raw
        filename = os.path.basename(str(source_path or ""))
        stem, _ = os.path.splitext(filename)
        return str(stem or "").strip()

    @staticmethod
    def _normalize_stem_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())

    def _infer_listening_paper_flag(self) -> bool:
        question_resource = self.paper_resources.get("question", {}) if isinstance(self.paper_resources, dict) else {}
        if isinstance(question_resource, dict):
            if bool(question_resource.get("is_listening")):
                return True

        if isinstance(self.resume_snapshot, dict) and bool(self.resume_snapshot.get("is_listening")):
            return True

        assessment = str(getattr(self.paper_mode_decision, "assessment_type", "") or "").strip().lower()
        if assessment == "listening":
            return True

        candidates = [
            str(self.pdf_url or ""),
            str(question_resource.get("url") if isinstance(question_resource, dict) else ""),
            str(question_resource.get("filename") if isinstance(question_resource, dict) else ""),
            str(question_resource.get("kind") if isinstance(question_resource, dict) else ""),
        ]
        return any(self._has_listening_token(item) for item in candidates)

    def _extract_front_page_metadata(self, pdf_path: str) -> Tuple[Optional[int], Optional[int]]:
        path = str(pdf_path or "").strip()
        if not path or not os.path.exists(path):
            return None, None
        if not PDF_AVAILABLE:
            return None, None
        try:
            doc = fitz.open(path)
        except Exception:
            return None, None

        try:
            chunk_texts: List[str] = []
            page_count = min(2, int(getattr(doc, "page_count", 0) or 0))
            for page_index in range(page_count):
                try:
                    chunk_texts.append(str(doc[page_index].get_text("text") or ""))
                except Exception:
                    continue
            merged = "\n".join(chunk_texts)
            detected_duration = parse_duration_minutes_from_front_page_text(merged)
            detected_total = parse_total_marks_from_front_page_text(merged)
            duration_out = int(detected_duration) if isinstance(detected_duration, int) and detected_duration > 0 else None
            total_out = int(detected_total) if isinstance(detected_total, int) and detected_total > 0 else None
            return duration_out, total_out
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def _sync_duration_from_question_pdf(self) -> None:
        try:
            question_path = self._resolve_source_path("question")
        except Exception:
            question_path = None
        if not question_path:
            question_path = str(self.local_pdf_path or "").strip() or None
        if not question_path:
            return

        detected_duration, detected_total = self._extract_front_page_metadata(question_path)

        if isinstance(detected_duration, int) and detected_duration > 0:
            self.duration = int(detected_duration)
            self.paper_mode_decision = replace(self.paper_mode_decision, duration_minutes=int(detected_duration))
            self.remaining_seconds = max(30, int(self.duration) * 60)
            self._timer_expiry_handled = False
            self._update_timer_label()

        if isinstance(detected_total, int) and detected_total > 0:
            self.official_total_marks = float(detected_total)
            self.paper_mode_decision = replace(self.paper_mode_decision, total_marks=int(detected_total))

    def _extract_paper_instruction_text(self, pdf_path: Optional[str], max_pages: int = 3) -> str:
        path = str(pdf_path or "").strip()
        if not path or not os.path.exists(path) or not PDF_AVAILABLE:
            return ""
        doc = None
        try:
            doc = fitz.open(path)
            chunks: List[str] = []
            pages_to_scan = min(max(1, int(max_pages)), len(doc))
            for page_index in range(pages_to_scan):
                try:
                    raw = str(doc[page_index].get_text("text") or "")
                except Exception:
                    raw = ""
                cleaned = re.sub(r"[ \t]+", " ", raw).strip()
                if cleaned:
                    chunks.append(cleaned)
            return "\n\n".join(chunks)[:12000]
        except Exception:
            return ""
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    @staticmethod
    def _normalize_audio_paper_id(value: str) -> str:
        stem = os.path.splitext(str(value or "").strip())[0].strip().lower()
        if not stem:
            return ""
        stem = re.sub(r"_(?:qp|ms|gt|in|tn)_(\d{1,2})$", r"_sf_\1", stem, flags=re.IGNORECASE)
        if re.fullmatch(r"\d{4}_[a-z]\d{2}_sf_\d{1,2}", stem, flags=re.IGNORECASE):
            return stem.lower()
        return ""

    @staticmethod
    def _audio_component_variants(component: str) -> List[str]:
        raw = "".join(ch for ch in str(component or "").strip() if ch.isdigit())[:2]
        if not raw:
            return []
        out: List[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            text = str(value or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            out.append(text)

        _add(raw)
        if len(raw) == 1:
            base = raw
        elif raw[0] == "0":
            base = raw[1]
        else:
            base = raw[0]
        if base:
            _add(base)
            _add(f"0{base}")
            _add(f"{base}{base}")
        return out

    def _audio_stream_url_candidates(self, paper_id: str) -> List[str]:
        stem = self._normalize_audio_paper_id(paper_id)
        if not stem:
            return []
        match = re.fullmatch(r"(?P<prefix>\d{4}_[a-z]\d{2}_sf_)(?P<component>\d{1,2})", stem, flags=re.IGNORECASE)
        bases = [str(base).rstrip("/") for base in _AUDIO_STREAM_BASE_URLS if str(base).strip()]
        if not bases:
            bases = [str(_AUDIO_STREAM_BASE_URL).rstrip("/")]
        if not match:
            return [f"{base}/{stem}.mp3" for base in bases]

        prefix = str(match.group("prefix"))
        component = str(match.group("component"))
        candidates = self._audio_component_variants(component)
        if not candidates:
            candidates = [component]
        out: List[str] = []
        for base in bases:
            for candidate in candidates:
                out.append(f"{base}/{prefix}{candidate}.mp3")
        return out

    def _audio_url_reachable(self, url: str) -> bool:
        target = str(url or "").strip()
        if not target.lower().startswith(("http://", "https://")):
            return False

        cached = self._audio_url_probe_cache.get(target)
        if cached is not None:
            return bool(cached)

        ok = False
        try:
            resp = run_io(requests.head,
                target,
                timeout=2,
                allow_redirects=True,
                headers=dict(_AUDIO_REQUEST_HEADERS),
            )
            try:
                status = int(getattr(resp, "status_code", 0) or 0)
                final_url = str(getattr(resp, "url", "") or "").strip().lower()
                content_type = str(getattr(resp, "headers", {}).get("content-type", "") or "").strip().lower()
            except Exception:
                status = 0
                final_url = ""
                content_type = ""
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

            if 200 <= status < 300 and final_url.endswith(".mp3"):
                if not (content_type.startswith("text/html") or content_type.startswith("application/xhtml+xml")):
                    ok = True
        except Exception:
            ok = False

        self._audio_url_probe_cache[target] = bool(ok)
        return bool(ok)

    def _collect_audio_stem_candidates(self, source_key: str, source_path: str) -> List[str]:
        key = str(source_key or "").strip().lower()
        question_resource = self.paper_resources.get("question", {}) if isinstance(self.paper_resources, dict) else {}
        audio_resource = self.paper_resources.get("audio", {}) if isinstance(self.paper_resources, dict) else {}
        candidate_values = [
            str(source_path or ""),
            str(self._source_remote_urls.get(key, "") or ""),
            str(self._source_remote_urls.get("audio", "") or ""),
            str(self._source_remote_urls.get("question", "") or ""),
            str(self._source_local_paths.get("question", "") or ""),
            str(self.local_pdf_path or ""),
            str(self.pdf_url or ""),
        ]
        if isinstance(question_resource, dict):
            candidate_values.extend(
                [
                    str(question_resource.get("filename") or ""),
                    str(question_resource.get("url") or ""),
                    str(question_resource.get("open_url") or ""),
                    str(question_resource.get("download_url") or ""),
                ]
            )
        if isinstance(audio_resource, dict):
            candidate_values.extend(
                [
                    str(audio_resource.get("paper_id") or ""),
                    str(audio_resource.get("filename") or ""),
                    str(audio_resource.get("url") or ""),
                    str(audio_resource.get("dynamic_url") or ""),
                    str(audio_resource.get("open_url") or ""),
                    str(audio_resource.get("download_url") or ""),
                ]
            )

        stems: List[str] = []
        seen: set[str] = set()
        for value in candidate_values:
            stem = self._stem_from_url_or_path(value)
            if not stem:
                continue
            if stem in seen:
                continue
            seen.add(stem)
            stems.append(stem)
        return stems

    def _build_audio_stream_url(self, source_key: str, source_path: str) -> str:
        first_syntactic_candidate = ""

        audio_resource = self.paper_resources.get("audio", {}) if isinstance(self.paper_resources, dict) else {}
        if isinstance(audio_resource, dict):
            for key in ("url", "dynamic_url", "open_url", "download_url"):
                candidate = str(audio_resource.get(key) or "").strip()
                if not candidate.lower().startswith(("http://", "https://")):
                    continue
                if not first_syntactic_candidate:
                    first_syntactic_candidate = candidate
                if self._audio_url_reachable(candidate):
                    return candidate

        remote_audio = str(self._source_remote_urls.get("audio", "") or "").strip()
        if remote_audio.lower().startswith(("http://", "https://")):
            if not first_syntactic_candidate:
                first_syntactic_candidate = remote_audio
            if self._audio_url_reachable(remote_audio):
                return remote_audio

        for stem in self._collect_audio_stem_candidates(source_key, source_path):
            paper_id = self._normalize_audio_paper_id(stem)
            if paper_id:
                for candidate_url in self._audio_stream_url_candidates(paper_id):
                    if not first_syntactic_candidate:
                        first_syntactic_candidate = candidate_url
                    if self._audio_url_reachable(candidate_url):
                        return candidate_url

        fallback_code = self._normalize_audio_paper_id(self._derive_paper_code_for_attempt())
        if fallback_code:
            candidates = self._audio_stream_url_candidates(fallback_code)
            for candidate_url in candidates:
                if not first_syntactic_candidate:
                    first_syntactic_candidate = candidate_url
                if self._audio_url_reachable(candidate_url):
                    return candidate_url
            if candidates:
                return candidates[0]
        return first_syntactic_candidate

    def _refresh_listening_audio_header(self, source_key: str, source_path: str) -> None:
        viewer = getattr(self, "pdf_viewer", None)
        if not isinstance(viewer, PDFViewer):
            return
        audio_header = getattr(viewer, "audio_header", None)
        if not isinstance(audio_header, ListeningHeader):
            return

        active_key = str(source_key or "").strip().lower()
        show_header = bool(self.is_listening and self.paper_mode == "MCQ_ONLY" and active_key == "question")
        if show_header:
            audio_url = self._build_audio_stream_url(active_key, source_path)
            self._listening_audio_path = audio_url
            if audio_url:
                viewer.set_listening_audio(audio_url)
                if self._resume_listening_audio_position_ms > 0 and not self._resume_listening_audio_position_applied:
                    try:
                        audio_header.set_resume_position_ms(self._resume_listening_audio_position_ms)
                    except Exception:
                        pass
                    self._resume_listening_audio_position_applied = True
            else:
                viewer.show_listening_audio_unavailable("Audio stream URL unavailable")
            audio_header.setVisible(True)
            return

        self._listening_audio_path = None
        viewer.hide_listening_audio()
        audio_header.hide()

    def _initialize_pdf_sources(self) -> None:
        self._source_local_paths = {}
        self._source_remote_urls = {}
        self._source_display_labels = {}
        self._available_pdf_sources = []

        def _resource_url(resource: object, *keys: str) -> str:
            if not isinstance(resource, dict):
                return ""
            ordered = list(keys) if keys else ["direct_url", "download_url", "url", "open_url"]
            for key in ordered:
                candidate = str(resource.get(key) or "").strip()
                if candidate:
                    return candidate
            return ""

        question_url = str(self.pdf_url or "").strip()
        question_resource = self.paper_resources.get("question", {}) if isinstance(self.paper_resources, dict) else {}
        question_resource_url = _resource_url(question_resource)
        if question_resource_url:
            question_url = question_resource_url

        if question_url:
            local_path = self._ensure_local_pdf_for_url(question_url)
            if local_path:
                self.local_pdf_path = local_path
            self._register_pdf_source("question", "Question Paper", url=question_url, local_path=local_path)

        insert_resource = self.paper_resources.get("insert", {}) if isinstance(self.paper_resources, dict) else {}
        insert_url = _resource_url(insert_resource)
        if insert_url:
            self._register_pdf_source("insert", "Insert", url=insert_url, local_path=None)

        ms_resource = self.paper_resources.get("mark_scheme", {}) if isinstance(self.paper_resources, dict) else {}
        ms_url = _resource_url(ms_resource)
        if ms_url:
            self._register_pdf_source("mark_scheme", "Mark Scheme", url=ms_url, local_path=None)

        if self.mark_scheme_path and os.path.exists(self.mark_scheme_path):
            self._register_pdf_source("mark_scheme", "Mark Scheme", url="", local_path=self.mark_scheme_path)

        self._pdf_source_switch_allowed = len(self._meaningful_visible_pdf_source_keys()) > 1
        self._rebuild_pdf_source_selector()

    def _prefetch_mark_scheme_in_background(self) -> None:
        if self._mark_scheme_prefetch_started or (self.mark_scheme_path and os.path.isfile(self.mark_scheme_path)):
            return
        self._mark_scheme_prefetch_started = True
        urls = [self._source_remote_urls.get("mark_scheme", ""), *self._build_mark_scheme_candidate_urls()]
        worker = MarkSchemeDownloadWorker(list(dict.fromkeys(url for url in urls if url)))
        self._mark_scheme_prefetch_thread = worker
        worker.finished_download.connect(self._on_mark_scheme_prefetched)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_mark_scheme_prefetched(self, source_url, content, error, cancelled):
        if cancelled or self._graceful_exit_cleanup_started or not content:
            return
        from Core.download_service import temp_directory
        handle = tempfile.NamedTemporaryFile(dir=temp_directory(), suffix=".pdf", delete=False)
        try:
            handle.write(bytes(content))
        except OSError:
            from Core.download_service import remove_owned_temporary_file
            handle.close()
            remove_owned_temporary_file(handle.name)
            logger.exception("Could not save prefetched mark scheme")
            return
        finally:
            handle.close()
        self.mark_scheme_path = handle.name
        self._register_pdf_source("mark_scheme", "Mark Scheme", url=source_url, local_path=handle.name)
        self._rebuild_pdf_source_selector()

    def _register_pdf_source(self, key: str, label: str, url: str = "", local_path: Optional[str] = None) -> None:
        source_key = str(key or "").strip().lower()
        if not source_key:
            return

        if source_key not in self._available_pdf_sources:
            self._available_pdf_sources.append(source_key)
        self._source_display_labels[source_key] = str(label or source_key.title())

        clean_url = str(url or "").strip()
        if clean_url:
            self._source_remote_urls[source_key] = clean_url

        clean_local = str(local_path or "").strip()
        if clean_local and os.path.exists(clean_local):
            self._source_local_paths[source_key] = clean_local

    def _pdf_source_identity(self, source_key: str) -> str:
        key = str(source_key or "").strip().lower()
        if not key:
            return ""
        local_path = str(self._source_local_paths.get(key, "") or "").strip()
        if local_path and os.path.exists(local_path):
            return f"local::{os.path.normcase(os.path.abspath(local_path))}"
        remote_url = str(self._source_remote_urls.get(key, "") or "").strip()
        if remote_url:
            return f"url::{remote_url.lower()}"
        return f"key::{key}"

    def _meaningful_visible_pdf_source_keys(self) -> List[str]:
        visible_keys = self._visible_pdf_sources()
        if len(visible_keys) <= 1:
            return list(visible_keys)
        out: List[str] = []
        seen: set[str] = set()
        for key in visible_keys:
            identity = self._pdf_source_identity(key)
            if identity in seen:
                continue
            seen.add(identity)
            out.append(key)
        return out

    def _rebuild_pdf_source_selector(self) -> None:
        combo = self.__dict__.get("pdf_source_selector")
        if not combo:
            return

        previous_key = str(self._active_pdf_source_key or "question")
        visible_keys = self._meaningful_visible_pdf_source_keys()
        blocked = combo.blockSignals(True)
        combo.clear()
        for key in visible_keys:
            label = self._source_display_labels.get(key, key.replace("_", " ").title())
            combo.addItem(label, key)

        target_key = previous_key if previous_key in visible_keys else ""
        if not target_key and visible_keys:
            target_key = visible_keys[0]
        if target_key:
            idx = combo.findData(target_key)
            if idx >= 0:
                combo.setCurrentIndex(idx)
                self._active_pdf_source_key = target_key

        combo.blockSignals(blocked)
        combo.setVisible(len(visible_keys) > 1)

    def _on_pdf_source_selector_changed(self, index: int) -> None:
        combo = self.__dict__.get("pdf_source_selector")
        if not combo:
            return
        key = str(combo.itemData(index) or "").strip().lower()
        if not key:
            return
        self._show_pdf_source(key, emit_signal=False)

    @staticmethod
    def _is_pdf_payload(content_type: str, payload_prefix: bytes, final_url: str) -> bool:
        _ = str(final_url or "")
        sample = bytes(payload_prefix or b"").lstrip()
        lowered = sample.lower()
        if (
            lowered.startswith(b"<!doctype html")
            or lowered.startswith(b"<html")
            or lowered.startswith(b"<?xml")
        ):
            return False
        if sample.startswith(b"%PDF-"):
            return True

        ctype = str(content_type or "").strip().lower()
        if "application/pdf" in ctype:
            return True
        if (
            ctype.startswith("text/html")
            or ctype.startswith("text/plain")
            or ctype.startswith("application/xhtml+xml")
        ):
            return False
        return False

    def _ensure_local_pdf_for_url(self, target_url: str) -> Optional[str]:
        url = str(target_url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return url if os.path.isfile(url) else None
        for source_key, remote in list(self._source_remote_urls.items()):
            cached = self._source_local_paths.get(source_key)
            if remote == url and cached and os.path.isfile(cached):
                return cached
        try:
            return download_pdf(url)
        except Exception:
            logger.exception("Could not download PDF from %s", url)
            return None

    def _resolve_source_path(self, key: str) -> Optional[str]:
        source_key = str(key or "").strip().lower()
        local = self._source_local_paths.get(source_key)
        if local and os.path.exists(local):
            return local
        url = self._source_remote_urls.get(source_key, "")
        if not url:
            return None
        resolved = self._ensure_local_pdf_for_url(url)
        if resolved:
            self._source_local_paths[source_key] = resolved
            if source_key == "question":
                self.local_pdf_path = resolved
        return resolved

    def _show_pdf_source(self, key: str, emit_signal: bool = True) -> bool:
        source_key = str(key or "").strip().lower()
        if source_key == "mark_scheme" and not self._mark_scheme_view_unlocked:
            show_info(self, "Mark Scheme Locked", "Submit first to unlock mark scheme access.")
            return False
        if source_key == "mark_scheme" and self._insert_split_enabled:
            self._set_inline_insert_split_enabled(False)
        if source_key not in self._available_pdf_sources:
            return False
        path = self._resolve_source_path(source_key)
        if not path:
            return False

        if hasattr(self, "pdf_viewer") and self.pdf_viewer:
            try:
                if self.pdf_viewer.pdf_path:
                    self._source_view_states[self._active_pdf_source_key] = self.pdf_viewer.capture_view_state()
                if self.pdf_viewer.load_pdf(path) is False:
                    return False
                self._active_pdf_source_key = source_key
                self._current_pdf_source = "mark_scheme" if source_key == "mark_scheme" else source_key
                if emit_signal and self.pdf_source_selector:
                    idx = self.pdf_source_selector.findData(source_key)
                    if idx >= 0 and self.pdf_source_selector.currentIndex() != idx:
                        blocked = self.pdf_source_selector.blockSignals(True)
                        self.pdf_source_selector.setCurrentIndex(idx)
                        self.pdf_source_selector.blockSignals(blocked)
                self._refresh_listening_audio_header(source_key, path)
                self._apply_movable_ruler_state_to_viewers()
                self._apply_question_scale_state_to_viewers()
                self._update_pdf_source_toggle()
                self._sync_insert_page_mode_control()
                if self._studio_workspace:
                    state = self._source_view_states.get(source_key)
                    if state:
                        self.pdf_viewer.restore_view_state(state)
                    else:
                        self.pdf_viewer.fit_to_width()
                    self._studio_workspace.sync_source_controls()
                    if source_key == "mark_scheme" and self.session_state.mode == "practice" and not self.session_state.completed:
                        self.session_state.assisted = True
                        self._mark_resume_snapshot_dirty()
                        self._studio_workspace.refresh_status()
                return True
            except Exception:
                return False
        return False

    def _ensure_mark_scheme_for_viewer(self) -> Optional[str]:
        if self.mark_scheme_path and os.path.exists(self.mark_scheme_path):
            self._register_pdf_source("mark_scheme", "Mark Scheme", local_path=self.mark_scheme_path)
            self._rebuild_pdf_source_selector()
            self._update_pdf_source_toggle()
            return self.mark_scheme_path

        ms_remote = self._source_remote_urls.get("mark_scheme", "")
        if ms_remote:
            ms_local = self._ensure_local_pdf_for_url(ms_remote)
            if ms_local:
                self.mark_scheme_path = ms_local
                self._register_pdf_source("mark_scheme", "Mark Scheme", url=ms_remote, local_path=ms_local)
                self._rebuild_pdf_source_selector()
                self._update_pdf_source_toggle()
                return ms_local

        ms_path = self._download_mark_scheme_candidate(silent=True)
        if ms_path:
            self.mark_scheme_path = ms_path
            self._register_pdf_source("mark_scheme", "Mark Scheme", local_path=ms_path)
            self._rebuild_pdf_source_selector()
            self._update_pdf_source_toggle()
            return ms_path
        self._update_pdf_source_toggle()
        return None

    def _show_mark_scheme_in_viewer(self) -> bool:
        if not self._mark_scheme_view_unlocked:
            show_info(self, "Mark Scheme Locked", "Submit first to unlock mark scheme access.")
            return False
        ms_path = self._ensure_mark_scheme_for_viewer()
        if not ms_path:
            show_warning(self, "Mark Scheme", "Could not load mark scheme for embedded view.")
            return False
        return self._show_pdf_source("mark_scheme")

    def _show_question_paper_in_viewer(self) -> bool:
        return self._show_pdf_source("question")

    def _toggle_pdf_source_view(self) -> None:
        visible_sources = self._visible_pdf_sources()
        if len(visible_sources) <= 1:
            return

        if self._active_pdf_source_key == "mark_scheme":
            self._show_pdf_source("question")
            return

        if self._mark_scheme_view_unlocked and "mark_scheme" in visible_sources:
            self._show_pdf_source("mark_scheme")
            return

        if "insert" in visible_sources:
            if self._active_pdf_source_key == "insert":
                self._show_pdf_source("question")
            else:
                self._show_pdf_source("insert")

    def _toggle_question_insert_view(self) -> None:
        if "insert" not in self._available_pdf_sources or "question" not in self._available_pdf_sources:
            return
        if self._insert_split_enabled:
            self._set_inline_insert_split_enabled(False)
        if self._active_pdf_source_key == "insert":
            self._show_pdf_source("question")
            return
        self._show_pdf_source("insert")

    def _supports_insert_split_view(self) -> bool:
        return True

    def _split_right_source_key(self) -> str:
        return "mark_scheme" if self._mark_scheme_view_unlocked else "insert"

    def _split_right_source_label(self) -> str:
        return "Mark Scheme" if self._split_right_source_key() == "mark_scheme" else "Insert"

    def _refresh_split_view_labels(self) -> None:
        if self._insert_split_left_label:
            self._insert_split_left_label.setText("Question Paper")
        if self._insert_split_right_label:
            self._insert_split_right_label.setText(self._split_right_source_label())

    def _on_insert_split_dialog_closed(self) -> None:
        self._insert_split_dialog = None
        self._set_inline_insert_split_enabled(False)
        self._update_insert_controls()

    def _set_inline_insert_split_enabled(self, enabled: bool) -> bool:
        target = bool(enabled)
        if target == self._insert_split_enabled:
            return True

        split_host = self._insert_split_inline_host
        primary_viewer = getattr(self, "pdf_viewer", None)
        left_viewer = self._insert_split_question_viewer
        right_viewer = self._insert_split_insert_viewer
        if not split_host or not isinstance(primary_viewer, PDFViewer) or not left_viewer or not right_viewer:
            return False

        if not target:
            split_host.setVisible(False)
            primary_viewer.setVisible(True)
            self._insert_split_enabled = False
            left_viewer.set_edge_navigation_enabled(False)
            right_viewer.set_edge_navigation_enabled(False)
            self._apply_movable_ruler_state_to_viewers()
            self._apply_question_scale_state_to_viewers()
            self._update_pdf_source_toggle()
            self._update_split_global_controls_visibility()
            return True

        right_source_key = self._split_right_source_key()
        question_path = self._resolve_source_path("question")
        if right_source_key == "mark_scheme":
            right_path = self._ensure_mark_scheme_for_viewer()
        else:
            right_path = self._resolve_source_path("insert")
        if not question_path or not right_path:
            right_name = "Mark Scheme" if right_source_key == "mark_scheme" else "Insert"
            show_warning(self, "Split View", f"Could not load both Question Paper and {right_name} for split view.")
            return False

        try:
            self._refresh_split_view_labels()
            left_viewer.load_pdf(question_path)
            right_viewer.load_pdf(right_path)
            if self._insert_split_inline_splitter:
                self._insert_split_inline_splitter.setSizes([1, 1])
            top_mode_combo = self.__dict__.get("insert_page_mode_combo")
            mode_label = str(top_mode_combo.currentText() or "").strip() if top_mode_combo else ""
            self._apply_insert_page_mode_to_viewers(mode_label or "1 page on screen")
        except Exception:
            show_warning(self, "Split View", "Could not render split view in the current window.")
            return False

        primary_viewer.setVisible(False)
        split_host.setVisible(True)
        self._insert_split_enabled = True
        left_viewer.set_edge_navigation_enabled(True)
        right_viewer.set_edge_navigation_enabled(True)
        self._apply_movable_ruler_state_to_viewers()
        self._apply_question_scale_state_to_viewers()
        self._update_pdf_source_toggle()
        self._update_split_global_controls_visibility()
        return True

    def _open_insert_split_view(self) -> None:
        if "question" not in self._available_pdf_sources:
            return
        self._set_inline_insert_split_enabled(not self._insert_split_enabled)
        self._update_insert_controls()

    def _iter_insert_page_mode_viewers(self) -> List[PDFViewer]:
        viewers: List[PDFViewer] = []
        primary = getattr(self, "pdf_viewer", None)
        if isinstance(primary, PDFViewer):
            viewers.append(primary)
        for split_viewer in [self._insert_split_question_viewer, self._insert_split_insert_viewer]:
            if isinstance(split_viewer, PDFViewer) and split_viewer not in viewers:
                viewers.append(split_viewer)
        return viewers

    def _apply_insert_page_mode_to_viewers(self, label: str) -> None:
        target = str(label or "").strip()
        if not target:
            return
        for viewer in self._iter_insert_page_mode_viewers():
            combo = getattr(viewer, "page_mode_combo", None)
            if not combo:
                continue
            idx = combo.findText(target)
            if idx >= 0 and combo.currentIndex() != idx:
                combo.setCurrentIndex(idx)

    def _sync_insert_page_mode_control(self) -> None:
        combo = self.__dict__.get("insert_page_mode_combo")
        if not combo:
            return
        current_text = ""
        primary = getattr(self, "pdf_viewer", None)
        if isinstance(primary, PDFViewer):
            viewer_combo = getattr(primary, "page_mode_combo", None)
            if viewer_combo:
                current_text = str(viewer_combo.currentText() or "").strip()
        target_text = current_text or "1 page on screen"
        idx = combo.findText(target_text)
        if idx < 0:
            idx = 0
        blocked = combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(blocked)

    def _on_insert_page_mode_changed(self, label: str) -> None:
        self._apply_insert_page_mode_to_viewers(str(label or "").strip())
        self._sync_insert_page_mode_control()

    def _update_insert_controls(self) -> None:
        insert_button = self.__dict__.get("paper_insert_toggle_btn")
        split_button = self.__dict__.get("insert_split_view_btn")
        page_mode_label = self.__dict__.get("insert_page_mode_label")
        page_mode_combo = self.__dict__.get("insert_page_mode_combo")
        has_question = "question" in self._available_pdf_sources
        has_insert = "insert" in self._available_pdf_sources
        in_exam_mode = self.paper_mode != "VIEWER_ONLY"
        post_submit = bool(self._mark_scheme_view_unlocked)
        can_toggle = in_exam_mode and has_question and (post_submit or has_insert)

        if insert_button:
            insert_button.setVisible(False)

        split_supported = can_toggle and self._supports_insert_split_view()
        if split_button:
            split_button.setVisible(split_supported and (not self._insert_split_enabled))
            split_button.setText("Split View")
            right_name = "Mark Scheme" if post_submit else "Insert"
            split_button.setToolTip(f"Show Question Paper and {right_name} side-by-side")

        if page_mode_label:
            page_mode_label.setVisible(False)
        if page_mode_combo:
            page_mode_combo.setVisible(False)
            page_mode_combo.setEnabled(False)

        if not split_supported and self._insert_split_enabled:
            self._set_inline_insert_split_enabled(False)
        self._refresh_split_view_labels()
        self._update_split_global_controls_visibility()

    def _update_pdf_source_toggle(self) -> None:
        button = self.__dict__.get("pdf_source_toggle_btn")
        combo = self.__dict__.get("pdf_source_selector")
        visible_sources = self._meaningful_visible_pdf_source_keys()
        can_switch = len(visible_sources) > 1
        self._pdf_source_switch_allowed = can_switch

        if combo:
            combo.setVisible(can_switch)
            combo.setEnabled(can_switch and not self._insert_split_enabled)

        if button:
            button.setVisible(False)
        self._update_insert_controls()

    def setup_viewer_only_mode(self, content_layout: QHBoxLayout, reason: str = ""):
        self.pdf_viewer = PDFViewer()
        pdf_host = self._build_pdf_view_host(self.pdf_viewer)

        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        title = QLabel("PDF Viewer Only")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        info_layout.addWidget(title)
        msg = QLabel(reason or "This paper component is not auto-gradable in exam mode.")
        msg.setWordWrap(True)
        info_layout.addWidget(msg)
        info_layout.addStretch(1)

        self.results_panel = GradingResultsPanel()
        self.results_panel.hide()
        info_layout.addWidget(self.results_panel)

        splitter = self._build_exam_splitter(pdf_host, info_container, [820, 190])
        content_layout.addWidget(splitter, 1)
        self._apply_question_scale_state_to_viewers()

    def setup_mixed_mode(self, content_layout: QHBoxLayout):
        # Mixed mode currently reuses the hierarchical written questionnaire
        # and marks objective rows via section_type metadata.
        self.setup_ai_grading_mode(content_layout)

    def _attach_answer_content_stack(self, answer_layout: QVBoxLayout) -> None:
        questionnaire = getattr(self, "questionnaire", None)
        self.answer_content_stack = QStackedWidget()
        if questionnaire is not None:
            self.answer_content_stack.addWidget(questionnaire)

        self.manual_grading_panel = None
        answer_layout.addWidget(self.answer_content_stack, 1)
        self._show_questionnaire_panel()

    def _ensure_manual_grading_panel(self) -> Optional[ManualGradingPanel]:
        panel = self.__dict__.get("manual_grading_panel")
        if isinstance(panel, ManualGradingPanel):
            return panel
        stack = self.__dict__.get("answer_content_stack")
        if not isinstance(stack, QStackedWidget):
            return None

        panel = ManualGradingPanel(self)
        panel.set_finalize_callback(self._finalize_manual_grade)
        stack.addWidget(panel)
        self.manual_grading_panel = panel
        return panel

    def setup_mcq_mode(self, content_layout: QHBoxLayout):
        num_questions = get_mcq_count(self.subject_code, self.paper_num) or 40

        self.pdf_viewer = PDFViewer()
        pdf_host = self._build_pdf_view_host(self.pdf_viewer)

        self.questionnaire = MCQQuestionnaire(num_questions, on_answer_change=self.on_mcq_answer_change)
        self.questionnaire.setMinimumHeight(260)
        answer_container = QWidget()
        answer_layout = QVBoxLayout(answer_container)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setSpacing(8)
        self.results_panel = GradingResultsPanel()
        self.results_panel.hide()
        answer_layout.addWidget(self.results_panel)
        self._build_optional_choice_selectors(answer_layout)
        self._attach_answer_content_stack(answer_layout)

        splitter = self._build_exam_splitter(pdf_host, answer_container, [760, 340])
        content_layout.addWidget(splitter, 1)
        self._apply_question_scale_state_to_viewers()

    def setup_written_mode(self, content_layout: QHBoxLayout):
        self.pdf_viewer = PDFViewer()
        pdf_host = self._build_pdf_view_host(self.pdf_viewer)

        num_questions = max(6, get_mcq_count(self.subject_code, self.paper_num) or 6)
        self.question_ids = [str(i) for i in range(1, num_questions + 1)]
        self.question_marks = {q: 1 for q in self.question_ids}
        self.question_texts = {q: f"Question {q}" for q in self.question_ids}
        self.questionnaire = WrittenQuestionnaire(num_questions, on_answer_change=self._on_exam_answer_changed)
        self.questionnaire.setMinimumHeight(300)
        answer_container = QWidget()
        answer_layout = QVBoxLayout(answer_container)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setSpacing(8)
        self.results_panel = GradingResultsPanel()
        self.results_panel.hide()
        answer_layout.addWidget(self.results_panel)
        self._attach_answer_content_stack(answer_layout)

        splitter = self._build_exam_splitter(pdf_host, answer_container, [770, 330])
        content_layout.addWidget(splitter, 1)
        self._apply_question_scale_state_to_viewers()

    def setup_ai_grading_mode(self, content_layout: QHBoxLayout):
        question_ids, question_marks = self._build_ai_question_structure()
        self.question_ids = question_ids
        self.question_marks = question_marks

        self.pdf_viewer = PDFViewer()
        pdf_host = self._build_pdf_view_host(self.pdf_viewer)

        self.questionnaire = MathQuestionnaire(
            lazy_workspace=True,
            question_ids=question_ids,
            question_items=self.question_items,
            on_answer_change=self._on_exam_answer_changed,
            on_jump_to_page=self.on_question_jump_requested,
            drawing_session_dir=self.drawing_session_dir,
            drawing_file_prefix=self.drawing_file_prefix,
        )
        self.questionnaire.setMinimumHeight(320)
        self.questionnaire.set_marks(question_marks)
        answer_container = QWidget()
        answer_layout = QVBoxLayout(answer_container)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        answer_layout.setSpacing(8)
        self.results_panel = GradingResultsPanel()
        self.results_panel.hide()
        answer_layout.addWidget(self.results_panel)
        self._attach_answer_content_stack(answer_layout)

        splitter = self._build_exam_splitter(pdf_host, answer_container, [770, 340])
        content_layout.addWidget(splitter, 1)
        self._apply_question_scale_state_to_viewers()

    @staticmethod
    def _optional_prompt_signature(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip().lower())
        cleaned = re.sub(r"question\s*\d+[a-zivx()\.]*", "question", cleaned)
        cleaned = re.sub(r"\b\d+[a-zivx()\.]*\b", "", cleaned)
        cleaned = re.sub(r"[^a-z\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:160]

    def _detect_optional_choice_groups(self) -> Dict[str, List[str]]:
        groups_by_sig: Dict[str, List[str]] = {}
        ordered_optional_qids: List[str] = []

        for item in self.question_items:
            qid = normalize_question_id(str(getattr(item, "canonical_id", "") or ""))
            if not qid:
                continue
            text = str(getattr(item, "text", "") or "")
            if not _is_optional_choice_question(text, subject_code=self.subject_code, paper_num=self.paper_num):
                continue
            ordered_optional_qids.append(qid)
            sig = self._optional_prompt_signature(text)
            groups_by_sig.setdefault(sig, [])
            if qid not in groups_by_sig[sig]:
                groups_by_sig[sig].append(qid)

        grouped: Dict[str, List[str]] = {}
        for qids in groups_by_sig.values():
            if len(qids) < 2:
                continue
            key = "|".join(qids)
            grouped[key] = list(qids)

        if not grouped and len(ordered_optional_qids) >= 2:
            key = "|".join(ordered_optional_qids)
            grouped[key] = list(ordered_optional_qids)
        return grouped

    def _current_optional_selection_payload(self) -> Dict[str, List[str]]:
        payload: Dict[str, List[str]] = {}
        for group_key, qids in self.optional_choice_groups.items():
            combo = self.optional_selectors.get(group_key)
            if not combo:
                continue
            selected = normalize_question_id(str(combo.currentData() or ""))
            if selected and selected in qids:
                payload[group_key] = [selected]
        return payload

    def _apply_optional_selection_visibility(self) -> None:
        questionnaire = getattr(self, "questionnaire", None)
        if not questionnaire or not hasattr(questionnaire, "set_question_visibility"):
            return

        selection = self._current_optional_selection_payload()
        self.optional_selection_map = dict(selection)

        for group_key, qids in self.optional_choice_groups.items():
            selected = set(selection.get(group_key, []))
            for qid in qids:
                visible = True if not selected else qid in selected
                questionnaire.set_question_visibility(qid, visible)

        try:
            self._refresh_submit_review_grid()
        except Exception:
            pass
        self._update_grading_action_visibility()
        if self._studio_workspace is not None:
            workspace = self._studio_workspace
            qids = workspace.question_ids()
            current = self.session_state.active_question
            workspace.select_question(current if current in qids else (qids[0] if qids else ""))
            workspace.refresh_status()

    def _build_optional_choice_selectors(self, parent_layout: QVBoxLayout) -> None:
        self.optional_choice_groups = self._detect_optional_choice_groups()
        self.optional_selectors = {}
        self.optional_selection_map = {}

        if self.optional_selector_panel:
            self.optional_selector_panel.hide()
            self.optional_selector_panel.deleteLater()
            self.optional_selector_panel = None

        if not self.optional_choice_groups:
            return

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(6)

        title = QLabel("Optional Question Selection")
        title.setStyleSheet(f"color: {Colors.TEXT_GRAY}; font-style: italic;")
        panel_layout.addWidget(title)

        snapshot_optional = {}
        if isinstance(self.resume_snapshot, dict):
            saved = self.resume_snapshot.get("optional_selection", {})
            if isinstance(saved, dict):
                snapshot_optional = saved

        for idx, (group_key, qids) in enumerate(self.optional_choice_groups.items(), start=1):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            label = QLabel(f"Choice group {idx}")
            row_layout.addWidget(label)

            combo = QComboBox()
            for qid in qids:
                combo.addItem(f"Answer Q{format_question_display(qid)}", qid)

            selected_qid = ""
            saved_selected = snapshot_optional.get(group_key, [])
            if isinstance(saved_selected, (list, tuple)) and saved_selected:
                selected_qid = normalize_question_id(str(saved_selected[0]))
            if selected_qid in qids:
                pos = combo.findData(selected_qid)
                if pos >= 0:
                    combo.setCurrentIndex(pos)

            combo.currentIndexChanged.connect(lambda _i, g=group_key: self._on_optional_selector_changed(g))
            self.optional_selectors[group_key] = combo
            row_layout.addWidget(combo)
            row_layout.addStretch(1)
            panel_layout.addWidget(row_widget)

        self.optional_selector_panel = panel
        parent_layout.addWidget(panel)
        self._apply_optional_selection_visibility()

    def _on_optional_selector_changed(self, _group_key: str) -> None:
        self._apply_optional_selection_visibility()
        self._mark_resume_snapshot_dirty()

    # ------------------------------------------------------------------
    # Question Setup
    # ------------------------------------------------------------------

    def _build_ai_question_structure(self) -> Tuple[List[str], Dict[str, float]]:
        question_ids: List[str] = []
        question_marks: Dict[str, float] = {}
        question_mark_hints: Dict[str, float] = {}

        structure = None
        if self.pdf_url:
            paper_info = extract_paper_code(self.pdf_url)
            if paper_info:
                structure = get_paper_structure(
                    paper_info["subject"],
                    paper_info["paper"],
                    paper_info["year_code"],
                )

        structure_ids: List[str] = []
        structure_marks: Dict[str, float] = {}
        if structure:
            structure_ids = [normalize_question_id(q) for q in generate_question_ids_from_structure(structure)]
            structure_marks = {
                normalize_question_id(k): float(v)
                for k, v in calculate_marks_from_structure(structure, structure_ids).items()
            }

        pdf_path = self._ensure_local_pdf()
        extractor = QuestionTextExtractor()
        unified = UnifiedQuestionExtractor(written_extractor=extractor)
        extracted = unified.extract_questions(
            pdf_path=pdf_path,
            subject_code=self.subject_code,
            paper_number=self.paper_number_raw or str(self.paper_num),
            exam_year=self.exam_year,
            mode=self.paper_mode,
            default_marks=1.0,
            expected_mcq_count=get_mcq_count(self.subject_code, self.paper_num) or 40,
        )
        confidence = dict(getattr(extracted, "confidence_summary", {}) or {})
        extracted_leaf_count = len(list(getattr(extracted, "question_ids", []) or []))
        extracted_marker_accept = float(confidence.get("marker_acceptance", 0.0) or 0.0)
        extracted_overall = float(confidence.get("overall", 0.0) or 0.0)
        extracted_low_confidence = (
            extracted_leaf_count < 3
            or extracted_marker_accept < 0.42
            or extracted_overall < 0.40
        )

        if extracted.question_ids and structure_ids and extracted_low_confidence:
            question_ids = structure_ids
            question_marks = structure_marks or {q: 1.0 for q in question_ids}
            question_mark_hints = {}
            extracted_texts = {
                normalize_question_id(k): v
                for k, v in (getattr(extracted, "question_texts", {}) or {}).items()
            }
            self.question_texts = self._match_question_texts(question_ids, extracted_texts)
            self.question_items = self._build_items_from_ids(question_ids)
        elif extracted.question_ids:
            question_ids = [normalize_question_id(q) for q in extracted.question_ids]
            self.question_texts = {normalize_question_id(k): v for k, v in extracted.question_texts.items()}
            self.question_items = extracted.question_items
            question_mark_hints = {
                normalize_question_id(q): float(v)
                for q, v in (getattr(extracted, "question_mark_hints", {}) or {}).items()
                if normalize_question_id(q)
            }
            question_marks = {
                normalize_question_id(q): float(
                    extracted.question_marks.get(q, question_mark_hints.get(normalize_question_id(q), 1.0))
                )
                for q in question_ids
            }

            if structure_marks:
                mapper = QuestionIDMapper()
                mark_map = mapper.generate_mapping(question_ids, list(structure_marks.keys()), question_order=question_ids)
                for qid, entry in mark_map.entries.items():
                    mapped = entry.answer_key_id
                    if mapped in structure_marks:
                        question_marks[qid] = float(structure_marks[mapped])
                if mark_map.coverage < 0.9:
                    show_warning(
                        self,
                        "Structure Warning",
                        (
                            f"PDF extraction and static structure differ ({mark_map.coverage*100:.1f}% alignment). "
                            "Using extracted question structure."
                        ),
                    )
        elif structure_ids:
            question_ids = structure_ids
            question_marks = structure_marks or {q: 1.0 for q in question_ids}
            question_mark_hints = {}
            self.question_texts = {q: f"Question {format_question_display(q)}" for q in question_ids}
            self.question_items = self._build_items_from_ids(question_ids)
        else:
            minimal_question_ids = self._recover_minimal_question_ids_from_pdf(pdf_path, extractor)
            if minimal_question_ids:
                question_ids = minimal_question_ids
                question_marks = {q: 1.0 for q in question_ids}
                question_mark_hints = {}
                self.question_texts = {q: f"Question {format_question_display(q)}" for q in question_ids}
                self.question_items = self._build_items_from_ids(question_ids)
            else:
                question_ids = [str(i) for i in range(1, 11)]
                question_marks = {q: 1.0 for q in question_ids}
                question_mark_hints = {}
                self.question_texts = {q: f"Question {q}" for q in question_ids}
                self.question_items = self._build_items_from_ids(question_ids)

        # Ensure section_type defaults are present
        for item in self.question_items:
            if not getattr(item, "section_type", ""):
                item.section_type = detect_section_type(item.text, mode=self.paper_mode)

        extracted_pages = {normalize_question_id(item.canonical_id): item.page for item in getattr(extracted, "question_items", []) if item.page}
        for item in self.question_items:
            if item.page is None:
                item.page = extracted_pages.get(normalize_question_id(item.canonical_id))
        self._attach_table_specs(pdf_path)
        self._attach_drawing_reference_images(pdf_path)
        self.question_mark_hints = {
            normalize_question_id(qid): float(value)
            for qid, value in question_mark_hints.items()
            if normalize_question_id(qid) and isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0
        }
        return question_ids, question_marks

    @staticmethod
    def _recover_minimal_question_ids_from_pdf(
        pdf_path: Optional[str],
        extractor: Optional[QuestionTextExtractor] = None,
    ) -> List[str]:
        path = str(pdf_path or "").strip()
        if not path or not os.path.exists(path) or not PDF_AVAILABLE:
            return []
        candidate_extractor = extractor or QuestionTextExtractor()
        doc = None
        try:
            doc = fitz.open(path)
            tokens = candidate_extractor._collect_line_tokens(doc, max_pages=50)
            if not tokens:
                tokens = candidate_extractor._collect_line_tokens_words(doc, max_pages=50)
            recovered = candidate_extractor._recover_minimal_main_result(tokens)
            if not recovered:
                return []
            return [normalize_question_id(qid) for qid in recovered.question_ids_leaf if normalize_question_id(qid)]
        except Exception:
            return []
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    @staticmethod
    def _coerce_question_page(raw_page: Any) -> Optional[int]:
        if raw_page is None or isinstance(raw_page, bool):
            return None
        if isinstance(raw_page, (int, float)):
            page = int(raw_page)
            return page if page > 0 else None
        text = str(raw_page).strip()
        if not text:
            return None
        match = re.search(r"\d+", text)
        if not match:
            return None
        try:
            parsed = int(match.group(0))
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _is_fillable_table_spec(spec: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(spec, dict):
            return False
        rows = int(spec.get("rows", 0) or 0)
        cols = int(spec.get("cols", 0) or 0)
        answer_cell_count = int(spec.get("answer_cell_count", 0) or 0)
        if rows <= 0 or cols <= 0 or answer_cell_count <= 0:
            return False
        total_cells = rows * cols
        if total_cells > 400:
            return False
        if rows >= 20 and cols >= 20:
            return False
        if total_cells > 120 and (answer_cell_count / max(1, total_cells)) > 0.8:
            return False
        return True

    def _table_question_candidate_items(self) -> List[QuestionLeaf]:
        candidates: List[QuestionLeaf] = []
        for item in self.question_items:
            item.table_spec = None
            response_type = str(getattr(item, "response_type", "") or "").strip().lower()
            if response_type == "drawing":
                continue
            question_text = str(getattr(item, "text", "") or "")
            table_score, _ = _table_intent_score(question_text)
            if response_type == "table" or table_score >= 0.75 or _has_tick_intent(question_text):
                candidates.append(item)
        return candidates

    @staticmethod
    def _table_question_probes(question_text: str) -> List[str]:
        text = re.sub(r"\s+", " ", str(question_text or "")).strip()
        if not text:
            return []
        probes: List[str] = []
        probes.append(text[:160])
        words = re.findall(r"[A-Za-z0-9\-\+\(\)/%]+", text)
        if words:
            probes.append(" ".join(words[:12]))
            probes.append(" ".join(words[:8]))
        deduped: List[str] = []
        seen: set[str] = set()
        for probe in probes:
            compact = probe.strip()
            if len(compact) < 8:
                continue
            if compact in seen:
                continue
            seen.add(compact)
            deduped.append(compact)
        return deduped

    @staticmethod
    def _find_table_anchor_y(page: Any, question_text: str) -> Optional[float]:
        for probe in ExamModeWindow._table_question_probes(question_text):
            try:
                matches = page.search_for(probe)
            except Exception:
                matches = []
            if matches:
                try:
                    return float(matches[0].y0)
                except Exception:
                    continue
        return None

    @staticmethod
    def _enrich_table_spec_for_question(spec: Dict[str, Any], question_text: str) -> Dict[str, Any]:
        enriched = dict(spec or {})
        tick_mode = _has_tick_intent(question_text)
        cells_out: List[Dict[str, Any]] = []
        for raw_cell in list(enriched.get("cells", []) or []):
            cell = dict(raw_cell or {})
            if bool(cell.get("is_answer", False)):
                if tick_mode:
                    cell["input_kind"] = "tick"
                    cell["options"] = ["No Check", "Check"]
                else:
                    cell["input_kind"] = "text"
                    cell.pop("options", None)
            else:
                cell.pop("input_kind", None)
                cell.pop("options", None)
            cells_out.append(cell)
        enriched["cells"] = cells_out
        enriched["answer_cell_count"] = sum(1 for cell in cells_out if bool(cell.get("is_answer", False)))
        return enriched

    def _attach_table_specs(self, pdf_path: Optional[str]) -> None:
        table_items = self._table_question_candidate_items()
        if not table_items:
            return
        if not PDF_AVAILABLE or not pdf_path or not os.path.exists(pdf_path):
            return

        page_tables: Dict[int, List[Dict[str, Any]]] = {}
        target_pages = {
            page
            for page in (self._coerce_question_page(getattr(item, "page", None)) for item in table_items)
            if page
        }

        doc = None
        try:
            doc = fitz.open(pdf_path)
            pages_to_scan = sorted(target_pages) if target_pages else list(range(1, len(doc) + 1))

            for page_num in pages_to_scan:
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue
                page = doc[page_idx]
                finder = page.find_tables()
                raw_tables = list(getattr(finder, "tables", []) or [])
                specs: List[Dict[str, Any]] = []
                for table in raw_tables:
                    spec = self._build_table_spec_from_fitz(table)
                    if not self._is_fillable_table_spec(spec):
                        continue
                    specs.append(dict(spec or {}))
                specs.sort(key=lambda s: float(s.get("bbox_y0", 0.0) or 0.0))
                if specs:
                    page_tables[page_num] = specs

            if not page_tables:
                return

            items_by_page: Dict[int, List[QuestionLeaf]] = {}
            for item in table_items:
                page = self._coerce_question_page(getattr(item, "page", None))
                if page and page in page_tables:
                    items_by_page.setdefault(page, []).append(item)

            for page_num, items in items_by_page.items():
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue
                page = doc[page_idx]
                available_specs = [dict(spec) for spec in page_tables.get(page_num, [])]
                for item in items:
                    if not available_specs:
                        break
                    q_text = str(getattr(item, "text", "") or "")
                    anchor_y = self._find_table_anchor_y(page, q_text)
                    chosen_idx = None
                    if anchor_y is not None:
                        forward_candidates: List[Tuple[int, float]] = []
                        for idx, spec in enumerate(available_specs):
                            y0 = float(spec.get("bbox_y0", 0.0) or 0.0)
                            if y0 >= anchor_y - 4.0:
                                forward_candidates.append((idx, y0 - anchor_y))
                        if forward_candidates:
                            chosen_idx = min(forward_candidates, key=lambda pair: pair[1])[0]
                    if chosen_idx is None:
                        chosen_idx = 0

                    assigned = available_specs.pop(chosen_idx)
                    item.table_spec = self._enrich_table_spec_for_question(assigned, q_text)
                    item.response_type = "table"

        except Exception:
            return
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    @staticmethod
    def _build_table_spec_from_fitz(table: Any) -> Optional[Dict[str, Any]]:
        try:
            row_count = int(getattr(table, "row_count", 0) or 0)
            col_count = int(getattr(table, "col_count", 0) or 0)
        except Exception:
            return None
        if row_count <= 0 or col_count <= 0:
            return None

        extracted = list(table.extract() or [])
        table_rows = list(getattr(table, "rows", []) or [])
        cells: List[Dict[str, Any]] = []
        cell_lookup: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for row_idx in range(row_count):
            row_obj = table_rows[row_idx] if row_idx < len(table_rows) else None
            row_cells = list(getattr(row_obj, "cells", []) or []) if row_obj is not None else []
            row_values = extracted[row_idx] if row_idx < len(extracted) else []
            for col_idx in range(col_count):
                bbox = row_cells[col_idx] if col_idx < len(row_cells) else None
                raw_text = row_values[col_idx] if col_idx < len(row_values) else ""
                text = "" if raw_text is None else str(raw_text).strip()
                compact = re.sub(r"\s+", "", text)
                blank_placeholder = bool(re.fullmatch(r"[_\.\-·…]{2,}", compact))
                if blank_placeholder:
                    text = ""

                missing = bbox is None
                x0 = y0 = x1 = y1 = width = height = None
                if not missing:
                    try:
                        x0, y0, x1, y1 = [float(v) for v in bbox]
                        width = max(0.0, x1 - x0)
                        height = max(0.0, y1 - y0)
                    except Exception:
                        missing = True
                        x0 = y0 = x1 = y1 = width = height = None
                is_answer = (not missing) and (text == "")
                cell_payload = {
                    "row": row_idx,
                    "col": col_idx,
                    "text": text,
                    "missing": missing,
                    "is_answer": is_answer,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "width": width,
                    "height": height,
                }
                cells.append(cell_payload)
                cell_lookup[(row_idx, col_idx)] = cell_payload

        def _cell_text(row: int, col: int) -> str:
            return str(cell_lookup.get((row, col), {}).get("text", "") or "").strip()

        def _is_header_text(value: str) -> bool:
            stripped = str(value or "").strip()
            if not stripped:
                return False
            if re.fullmatch(r"[\d\s\.,:/%\-\+]+", stripped):
                return False
            return True

        corner = cell_lookup.get((0, 0))
        if corner and bool(corner.get("is_answer", False)):
            row_headers = any(_is_header_text(_cell_text(0, col_idx)) for col_idx in range(1, col_count))
            col_headers = any(_is_header_text(_cell_text(row_idx, 0)) for row_idx in range(1, row_count))
            if row_headers and col_headers:
                corner["is_answer"] = False

        answer_cell_count = sum(1 for cell in cells if bool(cell.get("is_answer", False)))
        bbox = getattr(table, "bbox", (0.0, 0.0, 0.0, 0.0))
        try:
            bbox_y0 = float(bbox[1])
        except Exception:
            bbox_y0 = 0.0

        return {
            "rows": row_count,
            "cols": col_count,
            "cells": cells,
            "answer_cell_count": answer_cell_count,
            "bbox_y0": bbox_y0,
        }

    def _attach_drawing_reference_images(self, pdf_path: Optional[str]) -> None:
        drawing_items = [
            item for item in self.question_items
            if str(getattr(item, "response_type", "")).strip().lower() == "drawing"
        ]
        if not drawing_items:
            return
        if not PDF_AVAILABLE or not pdf_path or not os.path.exists(pdf_path):
            return

        for item in drawing_items:
            item.drawing_reference_path = None

        try:
            os.makedirs(self.drawing_session_dir, exist_ok=True)
            doc = fitz.open(pdf_path)
            for item in drawing_items:
                page_num = self._coerce_question_page(getattr(item, "page", None))
                if not page_num:
                    continue
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue

                page = doc[page_idx]
                clip = self._build_drawing_reference_clip(page, str(getattr(item, "text", "") or ""))
                item.drawing_reference_path = dict(pdf_path=pdf_path, page_index=page_idx,
                                                  clip=list(clip if clip is not None else page.rect))
            doc.close()
        except Exception:
            return

    @staticmethod
    def _build_drawing_reference_clip(page: Any, question_text: str) -> Optional[Any]:
        text = str(question_text or "").strip()
        if not text:
            return None

        probes: List[str] = []
        compact = re.sub(r"\s+", " ", text).strip()
        if compact:
            probes.append(compact[:120])
        words = re.findall(r"[A-Za-z0-9\-\+\(\)/]+", compact)
        if words:
            probes.append(" ".join(words[:12]))
            probes.append(" ".join(words[:8]))

        hit_rect = None
        for probe in probes:
            if len(probe) < 8:
                continue
            try:
                found = page.search_for(probe)
            except Exception:
                found = []
            if found:
                hit_rect = found[0]
                break

        if hit_rect is None:
            return None

        page_rect = page.rect
        page_height = float(page_rect.height)
        y_top = max(18.0, page_height * 0.03)
        y_span = max(260.0, page_height * 0.58)
        x0 = float(page_rect.x0)
        x1 = float(page_rect.x1)
        y0 = max(float(page_rect.y0), float(hit_rect.y0) - y_top)
        y1 = min(float(page_rect.y1), y0 + y_span)
        if (y1 - y0) < (page_height * 0.4):
            y1 = min(float(page_rect.y1), y0 + max(220.0, page_height * 0.5))
        if y1 - y0 < 120.0:
            return None

        return fitz.Rect(x0, y0, x1, y1)

    def _ensure_local_pdf(self) -> Optional[str]:
        if self.local_pdf_path and os.path.exists(self.local_pdf_path):
            return self.local_pdf_path

        if not self.pdf_url:
            return None

        if not self.pdf_url.startswith("http"):
            self.local_pdf_path = self.pdf_url
            return self.local_pdf_path

        resolved = self._ensure_local_pdf_for_url(self.pdf_url)
        if not resolved:
            return None
        self.local_pdf_path = resolved
        self._source_local_paths["question"] = resolved
        return self.local_pdf_path

    def _match_question_texts(self, question_ids: List[str], extracted_texts: Dict[str, str]) -> Dict[str, str]:
        normalized_texts = {normalize_question_id(k): v for k, v in extracted_texts.items()}
        normalized_ids = [normalize_question_id(q) for q in question_ids]

        mapper = QuestionIDMapper()
        report = mapper.generate_mapping(normalized_ids, list(normalized_texts.keys()), question_order=normalized_ids)

        matched: Dict[str, str] = {}
        for qid in normalized_ids:
            entry = report.entries.get(qid)
            mapped = entry.answer_key_id if entry else None
            if mapped and mapped in normalized_texts:
                matched[qid] = normalized_texts[mapped]
            else:
                matched[qid] = f"Question {format_question_display(qid)}"

        if report.coverage < 0.9:
            show_warning(
                self,
                "Question Matching Warning",
                (
                    f"Question text mapping coverage is {report.coverage*100:.1f}%.\n"
                    f"Unmatched: {', '.join(report.unmatched_extracted[:10]) or 'None'}"
                ),
            )
        return matched

    def _build_items_from_ids(self, question_ids: List[str]) -> List[QuestionLeaf]:
        items: List[QuestionLeaf] = []
        for qid in question_ids:
            parts = parse_question_id(qid)
            question_text = self.question_texts.get(normalize_question_id(qid), "")
            response_type, _, reason = detect_response_type(question_text)
            level = 0
            parent = None
            if parts.part:
                level = 1
                parent = str(parts.main) if parts.main is not None else None
            if parts.part and parts.subpart:
                level = 2
                parent = f"{parts.main}{parts.part}" if parts.main is not None else None
            items.append(
                QuestionLeaf(
                    canonical_id=normalize_question_id(qid),
                    display_id=format_question_display(qid),
                    main=parts.main,
                    part=parts.part,
                    subpart=parts.subpart,
                    page=None,
                    text=question_text,
                    parent_id=parent,
                    level=level,
                    response_type=response_type,
                    requires_manual_review=response_type == "drawing",
                    manual_review_reason=reason if response_type == "drawing" else "",
                    section_type=detect_section_type(question_text, mode=self.paper_mode),
                )
            )
        return items

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    @staticmethod
    def _is_text_entry_widget(widget: object) -> bool:
        if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(widget, QComboBox):
            return bool(widget.isEditable())
        return False

    def _resolve_arrow_navigation_target_viewer(self) -> Optional[PDFViewer]:
        if self._insert_split_enabled:
            split_viewers = self._iter_split_controlled_viewers()
            hovered = self._last_hovered_pdf_viewer
            if isinstance(hovered, PDFViewer) and hovered in split_viewers:
                return hovered
            focus_widget = QApplication.focusWidget()
            for viewer in split_viewers:
                if focus_widget is viewer:
                    return viewer
                if isinstance(focus_widget, QWidget) and viewer.isAncestorOf(focus_widget):
                    return viewer
            return split_viewers[0] if split_viewers else None

        primary = getattr(self, "pdf_viewer", None)
        if isinstance(primary, PDFViewer) and primary.isVisible():
            return primary
        return None

    def _handle_pdf_arrow_navigation(self, key: int) -> bool:
        viewer = self._resolve_arrow_navigation_target_viewer()
        if not isinstance(viewer, PDFViewer):
            return False
        if key == Qt.Key.Key_Left:
            viewer.prev_page()
            return True
        if key == Qt.Key.Key_Right:
            viewer.next_page()
            return True
        return False

    def _clear_last_hovered_pdf_viewer_if_needed(self) -> None:
        viewer = self._last_hovered_pdf_viewer
        if not isinstance(viewer, PDFViewer):
            return
        try:
            if viewer.underMouse() or (viewer.isVisible() and viewer.hasFocus()):
                return
        except Exception:
            pass
        self._last_hovered_pdf_viewer = None

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        if key in {Qt.Key.Key_Left, Qt.Key.Key_Right}:
            if not bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
                focus_widget = self.focusWidget()
                if not self._is_text_entry_widget(focus_widget):
                    if self._handle_pdf_arrow_navigation(key):
                        event.accept()
                        return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):  # type: ignore[override]
        if watched is self._user_docs_dialog:
            etype = event.type()
            if etype in {QEvent.Type.Hide, QEvent.Type.Close}:
                self._restore_settings_after_docs_if_needed()
        if isinstance(watched, PDFViewer):
            etype = event.type()
            if etype in {
                QEvent.Type.Enter,
                QEvent.Type.HoverEnter,
                QEvent.Type.HoverMove,
                QEvent.Type.MouseMove,
                QEvent.Type.FocusIn,
                QEvent.Type.Show,
            }:
                self._last_hovered_pdf_viewer = watched
            elif etype in {QEvent.Type.Leave, QEvent.Type.HoverLeave, QEvent.Type.Hide}:
                if self._last_hovered_pdf_viewer is watched:
                    QTimer.singleShot(0, self._clear_last_hovered_pdf_viewer_if_needed)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_utility_drawer_geometry(animate=False)

    def _sync_exam_clock(self):
        now = time.monotonic()
        previous = getattr(self, "_timer_last_monotonic", now)
        self._timer_last_monotonic = now
        if self.timer_paused:
            return
        elapsed = max(0.0, now - previous) + getattr(self, "_timer_fraction", 0.0)
        whole = int(elapsed)
        self._timer_fraction = elapsed - whole
        if self.session_state.completed:
            return
        self.session_state.elapsed_seconds += whole
        if self.session_state.mode == "exam":
            self.remaining_seconds = max(0, self.remaining_seconds - whole)

    def _tick_timer(self):
        self._sync_exam_clock()
        if self.timer_paused:
            return
        self._update_timer_label()
        if self.session_state.mode == "practice":
            self._apply_timer_visual_state()
        elif self.remaining_seconds <= 0:
            self.timer.stop()
            self.end_exam(from_timer=True)

    def _update_timer_label(self) -> None:
        if not getattr(self, "timer_label", None):
            return
        seconds_total = max(0, int(self.session_state.elapsed_seconds if self.session_state.mode == "practice" else self.remaining_seconds))
        minutes = seconds_total // 60
        seconds = seconds_total % 60
        self.timer_label.setText(f"{minutes:02d}:{seconds:02d}" + (f" / {self.duration}m" if self.session_state.mode == "practice" else ""))
        self.timer_label.setToolTip(f"Practice elapsed · recommended {self.duration} minutes" if self.session_state.mode == "practice" else "Exam time remaining")
        total = max(60, int(self.duration) * 60)
        elapsed = max(0, total - seconds_total)
        progress = float(elapsed) / float(total)
        coach = "On pace"
        if progress > 0.85 and seconds_total > max(120, int(total * 0.2)):
            coach = "Speed up: likely overrun"
        elif progress < 0.25 and seconds_total < int(total * 0.5):
            coach = "Good pace"
        if isinstance(getattr(self, "grade_status_label", None), QLabel):
            existing = str(self.grade_status_label.text() or "").strip()
            if "Coach:" not in existing:
                self.grade_status_label.setText(f"{existing} | Coach: {coach}".strip(" |"))

    def _derive_paper_code_for_attempt(self) -> str:
        for target in [self.pdf_url, self.local_pdf_path]:
            parsed = extract_paper_code(str(target or "").strip())
            if parsed:
                subject = str(parsed.get("subject", "")).strip()
                year_code = str(parsed.get("year_code", "")).strip().lower()
                paper = str(parsed.get("paper", "")).strip()
                if subject and year_code and paper:
                    return f"{subject}_{year_code}_qp_{paper}"

        fallback_paper = str(self.paper_number_raw or self.paper_num).strip()
        if len(fallback_paper) == 1 and fallback_paper.isdigit():
            fallback_paper = f"{fallback_paper}0"
        return f"{self.subject_code}_qp_{fallback_paper or self.paper_num}"

    def _resolve_resume_pdf_locator(self) -> str:
        question_resource = self.paper_resources.get("question", {}) if isinstance(self.paper_resources, dict) else {}
        source_remote_urls = self.__dict__.get("_source_remote_urls", {})
        source_local_paths = self.__dict__.get("_source_local_paths", {})
        candidates = [
            source_remote_urls.get("question", "") if isinstance(source_remote_urls, dict) else "",
            question_resource.get("direct_url", "") if isinstance(question_resource, dict) else "",
            question_resource.get("download_url", "") if isinstance(question_resource, dict) else "",
            question_resource.get("url", "") if isinstance(question_resource, dict) else "",
            question_resource.get("open_url", "") if isinstance(question_resource, dict) else "",
            self.pdf_url,
            source_local_paths.get("question", "") if isinstance(source_local_paths, dict) else "",
            self.local_pdf_path or "",
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return ""

    def _copy_drawing_asset_for_resume(self, q_id: str, image_path: str) -> str:
        source_path = str(image_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            return ""

        assets_dir = ExamAttemptManager.get_attempt_assets_dir(self._attempt_key)
        try:
            os.makedirs(assets_dir, exist_ok=True)
        except Exception:
            return source_path if os.path.exists(source_path) else ""

        safe_qid = re.sub(r"[^A-Za-z0-9_-]+", "_", str(q_id or "drawing"))
        ext = str(os.path.splitext(source_path)[1] or "").lower()
        if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            ext = ".png"
        target_path = os.path.join(assets_dir, f"{safe_qid}{ext}")

        try:
            if os.path.abspath(source_path) != os.path.abspath(target_path):
                shutil.copy2(source_path, target_path)
            elif not os.path.exists(target_path):
                shutil.copy2(source_path, target_path)
            return target_path
        except Exception:
            return source_path if os.path.exists(source_path) else ""

    def _filter_answers_for_resume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        filtered: Dict[str, Any] = {}
        for raw_qid, raw_value in payload.items():
            q_id = normalize_question_id(str(raw_qid))
            if not q_id:
                continue

            if isinstance(raw_value, dict):
                payload_type = str(raw_value.get("type", "")).strip().lower()
                if payload_type == "drawing":
                    drawing_path = self._copy_drawing_asset_for_resume(
                        q_id,
                        str(raw_value.get("image_path", "") or ""),
                    )
                    notes_text = str(raw_value.get("notes", "") or "")
                    if drawing_path.strip() or notes_text.strip():
                        filtered[q_id] = {
                            "type": "drawing",
                            "image_path": drawing_path,
                            "notes": notes_text,
                        }
                    continue
                if payload_type == "table":
                    cells_raw = raw_value.get("cells", {})
                    kept_cells: Dict[str, str] = {}
                    if isinstance(cells_raw, dict):
                        for key, value in cells_raw.items():
                            value_text = str(value or "")
                            if value_text.strip():
                                kept_cells[str(key)] = value_text
                    serialized = str(raw_value.get("value", "") or "")
                    if kept_cells or serialized.strip():
                        filtered[q_id] = {
                            "type": "table",
                            "cells": kept_cells,
                            "value": serialized,
                        }
                    continue

                text_value = str(raw_value.get("value", "") or "")
                if text_value.strip():
                    filtered[q_id] = {
                        "type": "text",
                        "value": text_value,
                    }
                continue

            text_value = str(raw_value or "")
            if text_value.strip():
                filtered[q_id] = text_value
        return filtered

    def _build_unfinished_attempt_entry(self) -> Dict[str, Any]:
        self._sync_exam_clock()
        answers_payload: Dict[str, Any] = {}
        questionnaire = getattr(self, "questionnaire", None)
        if questionnaire and hasattr(questionnaire, "get_answers"):
            try:
                raw_answers = questionnaire.get_answers()
                if isinstance(raw_answers, dict):
                    answers_payload = raw_answers
            except Exception:
                answers_payload = {}
        notes_text = self._current_notes_text()
        previous_attempt_key = str(self._attempt_key or "").strip()
        resume_pdf_locator = self._resolve_resume_pdf_locator()
        resolved_attempt_key = previous_attempt_key or ExamAttemptManager.build_attempt_key(
            str(self.subject_code),
            str(self.paper_number_raw or self.paper_num),
            str(self.year),
            str(resume_pdf_locator or self.pdf_url or ""),
        )
        existing_attempt: Dict[str, Any] = {}
        if resolved_attempt_key:
            existing_attempt = ExamAttemptManager.get_attempt(resolved_attempt_key) or {}
            if (not existing_attempt) and previous_attempt_key and previous_attempt_key != resolved_attempt_key:
                existing_attempt = ExamAttemptManager.get_attempt(previous_attempt_key) or {}
            if previous_attempt_key and previous_attempt_key != resolved_attempt_key:
                try:
                    ExamAttemptManager.delete_attempt(previous_attempt_key)
                except Exception:
                    pass
            self._attempt_key = resolved_attempt_key
        if not existing_attempt:
            existing_attempt = ExamAttemptManager.get_attempt(self._attempt_key) or {}
        now_stamp = datetime.now().isoformat(timespec="seconds")
        first_saved_at = str(
            existing_attempt.get("first_saved_at", "")
            or existing_attempt.get("saved_at", "")
            or getattr(self, '_study_started_at', '')
            or now_stamp
        ).strip()
        if not first_saved_at:
            first_saved_at = now_stamp
        listening_audio_state = self._capture_listening_audio_resume_state()
        normalized_question_ids: List[str] = []
        for raw_qid in list(getattr(self, "question_ids", []) or []):
            qid = normalize_question_id(str(raw_qid))
            if qid:
                normalized_question_ids.append(qid)
        normalized_question_marks: Dict[str, float] = {}
        for raw_qid, raw_marks in dict(getattr(self, "question_marks", {}) or {}).items():
            qid = normalize_question_id(str(raw_qid))
            if not qid:
                continue
            try:
                mark_value = float(raw_marks)
            except Exception:
                continue
            if not math.isfinite(mark_value) or mark_value <= 0:
                continue
            normalized_question_marks[qid] = mark_value
        if not normalized_question_marks:
            for qid in normalized_question_ids:
                normalized_question_marks[qid] = 1.0
        total_marks = float(sum(normalized_question_marks.values()))

        return {
            "attempt_key": self._attempt_key,
            "study_attempt_id": getattr(self, "_study_attempt_id", ""),
            "workspace": self.session_state.snapshot(),
            "paper_code": self._derive_paper_code_for_attempt(),
            "subject_code": str(self.subject_code),
            "subject_name": str(self.subject_name or ""),
            "paper_num": str(self.paper_number_raw or self.paper_num),
            "year": str(self.year),
            "series": str(getattr(self, "series", "") or ""),
            "paper_resources": dict(getattr(self, "paper_resources", {}) or {}),
            "pdf_url": str(resume_pdf_locator or self.pdf_url or ""),
            "remaining_seconds": max(0, int(self.remaining_seconds)),
            "answers": self._filter_answers_for_resume(answers_payload),
            "question_ids": normalized_question_ids,
            "question_marks": normalized_question_marks,
            "total_marks": total_marks,
            "optional_selection": dict(self.optional_selection_map),
            "notes_text": notes_text,
            "local_pdf_path": str(self.local_pdf_path or ""),
            "first_saved_at": first_saved_at,
            "saved_at": now_stamp,
            "is_listening": bool(listening_audio_state.get("is_listening", self.is_listening)),
            "listening_audio_position_ms": int(listening_audio_state.get("listening_audio_position_ms", 0) or 0),
            "listening_audio_timestamp": str(listening_audio_state.get("listening_audio_timestamp", "") or ""),
            "listening_audio_source": str(listening_audio_state.get("listening_audio_source", "") or ""),
        }

    def _mark_resume_snapshot_dirty(self) -> None:
        if self._restoring_resume_snapshot or not self._allow_resume_autosave:
            return
        self._autosave_has_user_input = True
        self._autosave_dirty = True
        timer = self.__dict__.get("_autosave_debounce_timer")
        if isinstance(timer, QTimer):
            timer.start()

    def _on_autosave_debounce_timeout(self) -> None:
        self._try_autosave_unfinished_attempt(force=False)

    def _on_autosave_periodic_timeout(self) -> None:
        self._try_autosave_unfinished_attempt(force=False)

    def _try_autosave_unfinished_attempt(self, force: bool = False) -> None:
        if not self._allow_resume_autosave:
            return
        if self.session_state.mode != "practice" and int(getattr(self, "remaining_seconds", 0)) <= 0:
            return
        if force and not self._autosave_has_user_input and not self._autosave_dirty:
            return
        now = time.monotonic()
        if not force:
            stale = (now - float(self._autosave_last_saved_monotonic)) >= float(self._autosave_max_staleness_seconds)
            if not self._autosave_dirty and not (self._autosave_has_user_input and stale):
                return
        self._save_unfinished_attempt(notify_on_failure=False)

    def _stop_autosave_timers(self) -> None:
        debounce_timer = self.__dict__.get("_autosave_debounce_timer")
        periodic_timer = self.__dict__.get("_autosave_periodic_timer")
        for timer in (debounce_timer, periodic_timer):
            if isinstance(timer, QTimer):
                try:
                    timer.stop()
                except Exception:
                    pass

    def _save_unfinished_attempt(self, *, notify_on_failure: bool = True) -> bool:
        if not self._allow_resume_autosave:
            return True
        entry = self._build_unfinished_attempt_entry()
        ok = ExamAttemptManager.upsert_attempt(entry)
        if ok:
            from Core.study_history import StudyHistory
            StudyHistory.record(entry, 'saved')
            self._autosave_dirty = False
            self._autosave_has_user_input = True
            self._autosave_last_saved_monotonic = time.monotonic()
            self._autosave_error_notified = False
            return True
        if not ok:
            if notify_on_failure:
                show_warning(
                    self,
                    "Save Failed",
                    "Could not save your unfinished exam session. Exiting without a resume snapshot.",
                )
            elif not self._autosave_error_notified:
                self._autosave_error_notified = True
        return False

    def _delete_unfinished_attempt(self, *, disable_autosave: bool = True) -> None:
        if not self.session_state.completed:
            from Core.study_history import StudyHistory
            StudyHistory.record(self._build_unfinished_attempt_entry(), 'abandoned')
        if disable_autosave:
            self._allow_resume_autosave = False
        self._autosave_dirty = False
        self._autosave_has_user_input = False
        self._stop_autosave_timers()
        try:
            ExamAttemptManager.delete_attempt(self._attempt_key)
        except Exception:
            pass

    def _refresh_parent_history_after_attempt_change(self) -> None:
        parent = self._workspace_lifecycle.main()
        if parent and hasattr(parent, "refresh_history"):
            try:
                parent.refresh_history()
            except Exception:
                pass

    def _has_unanswered_questions(self) -> bool:
        completion = self._compute_question_completion_state()
        if not completion:
            return False
        return any(not bool(done) for done in completion.values())

    def _prompt_save_unfinished_exam(self) -> str:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("Unfinished Exam")
        dialog.setText(
            "You have unanswered questions. Save your answers and remaining time for next time?"
        )
        dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        yes_btn = dialog.addButton("Yes", QMessageBox.ButtonRole.YesRole)
        exit_btn = dialog.addButton("Exit", QMessageBox.ButtonRole.DestructiveRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is yes_btn:
            return "save"
        if clicked is exit_btn:
            return "exit"
        return "cancel"

    def _apply_resume_snapshot(self) -> None:
        snapshot = self.resume_snapshot if isinstance(self.resume_snapshot, dict) else {}
        if not snapshot:
            self._update_timer_label()
            self._autosave_has_user_input = False
            self._autosave_dirty = False
            self._autosave_last_saved_monotonic = time.monotonic()
            return

        self._restoring_resume_snapshot = True
        try:
            try:
                restored_seconds = int(snapshot.get("remaining_seconds", self.remaining_seconds))
            except Exception:
                restored_seconds = self.remaining_seconds
            if restored_seconds > 0:
                self.remaining_seconds = restored_seconds
                self._timer_last_monotonic = time.monotonic()
                self._timer_fraction = 0.0
                self._timer_expiry_handled = False
            workspace_state = snapshot.get("workspace")
            has_saved_elapsed = isinstance(workspace_state, dict) and "elapsed_seconds" in workspace_state
            if self.session_state.mode == "exam" and not has_saved_elapsed:
                # Earlier versions saved only the countdown. Keep time already
                # spent on those attempts in the new completion summary.
                self.session_state.elapsed_seconds = max(0, int(self.duration) * 60 - self.remaining_seconds)
            self._update_timer_label()

            questionnaire = getattr(self, "questionnaire", None)
            answers = snapshot.get("answers", {})
            if questionnaire and hasattr(questionnaire, "apply_saved_answers") and isinstance(answers, dict):
                try:
                    questionnaire.apply_saved_answers(answers)
                except Exception:
                    pass

            optional_saved = snapshot.get("optional_selection", {})
            if isinstance(optional_saved, dict) and self.optional_selectors:
                for group_key, raw_selected in optional_saved.items():
                    combo = self.optional_selectors.get(str(group_key))
                    if not combo:
                        continue
                    selected_qid = ""
                    if isinstance(raw_selected, (list, tuple)) and raw_selected:
                        selected_qid = normalize_question_id(str(raw_selected[0]))
                    if not selected_qid:
                        continue
                    idx = combo.findData(selected_qid)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                self._apply_optional_selection_visibility()

            notes_text = self._extract_notes_text_from_snapshot(snapshot)
            self._notes_text_cache = notes_text
            if self.notes_widget is not None and self.notes_widget.notes_text() != self._notes_text_cache:
                self.notes_widget.set_notes_text(self._notes_text_cache)

            resume_audio_ms = 0
            try:
                resume_audio_ms = max(0, int(snapshot.get("listening_audio_position_ms", 0)))
            except Exception:
                resume_audio_ms = 0
            self._resume_listening_audio_position_ms = resume_audio_ms
            self._resume_listening_audio_position_applied = False
            if self._resume_listening_audio_position_ms > 0 and self.is_listening:
                viewer = getattr(self, "pdf_viewer", None)
                header = getattr(viewer, "audio_header", None) if viewer is not None else None
                if isinstance(header, ListeningHeader):
                    try:
                        header.set_resume_position_ms(self._resume_listening_audio_position_ms)
                        self._resume_listening_audio_position_applied = True
                    except Exception:
                        pass
        finally:
            self._restoring_resume_snapshot = False

        has_answers = isinstance(snapshot.get("answers"), dict) and bool(snapshot.get("answers"))
        has_optional_selection = isinstance(snapshot.get("optional_selection"), dict) and bool(snapshot.get("optional_selection"))
        has_notes = bool(str(self._extract_notes_text_from_snapshot(snapshot)).strip())
        self._autosave_has_user_input = bool(has_answers or has_optional_selection or has_notes)
        self._autosave_dirty = False
        self._autosave_last_saved_monotonic = time.monotonic()

    def _current_notes_text(self) -> str:
        if self.notes_widget is not None:
            try:
                text = str(self.notes_widget.notes_text() or "")
                self._notes_text_cache = text
                return text
            except Exception:
                pass
        return str(self._notes_text_cache or "")

    @staticmethod
    def _extract_notes_text_from_snapshot(snapshot: Dict[str, Any]) -> str:
        for key in ("notes_text", "notes", "scratchpad_notes"):
            value = snapshot.get(key, "")
            if value is None:
                continue
            return str(value)
        return ""

    @staticmethod
    def _format_audio_position_ms(position_ms: int) -> str:
        total = max(0, int(position_ms))
        hours = total // 3_600_000
        minutes = (total % 3_600_000) // 60_000
        seconds = (total % 60_000) // 1_000
        millis = total % 1_000
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}"
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

    def _capture_listening_audio_resume_state(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "is_listening": bool(self.is_listening),
            "listening_audio_position_ms": 0,
            "listening_audio_timestamp": "",
            "listening_audio_source": "",
        }
        if not self.is_listening:
            return payload

        viewer = getattr(self, "pdf_viewer", None)
        header = getattr(viewer, "audio_header", None) if viewer is not None else None
        if not isinstance(header, ListeningHeader):
            return payload

        try:
            position_ms = max(0, int(header.current_position_ms()))
        except Exception:
            position_ms = 0
        payload["listening_audio_position_ms"] = position_ms
        payload["listening_audio_timestamp"] = self._format_audio_position_ms(position_ms)
        try:
            payload["listening_audio_source"] = str(header.current_audio_source() or "")
        except Exception:
            payload["listening_audio_source"] = ""
        return payload

    def _apply_timer_visual_state(self) -> None:
        pause_btn = self.__dict__.get("pause_btn")
        label = self.__dict__.get("timer_label")
        if pause_btn:
            pause_btn.setText("Resume" if self.timer_paused else "Pause")
        if not label:
            return
        accent = Colors.WARNING if self.timer_paused else Colors.SUCCESS
        if self.session_state.mode == "practice" and self.session_state.elapsed_seconds > int(self.duration) * 60:
            accent = "#D93025"
        background = _mix_hex(accent, Colors.BG_DARK, 0.88)
        foreground = self._theme_manager._ensure_text_contrast(accent, background, min_ratio=4.5)
        label.setStyleSheet(
            f"color: {foreground}; background-color: {background};"
            f"border: 1px solid {_mix_hex(accent, Colors.BG_DARK, 0.5)};"
            "border-radius: 8px; padding: 2px 8px;"
        )

    def toggle_pause(self):
        if self.session_state.completed:
            return
        if not self.timer_paused:
            self._sync_exam_clock()
        self.timer_paused = not self.timer_paused
        if self.timer_paused:
            self.session_state.pause_count += 1
        self._mark_resume_snapshot_dirty()
        self._timer_last_monotonic = time.monotonic()
        self._apply_timer_visual_state()

        if self._studio_workspace:
            self._studio_workspace.refresh_status()

    def _handle_timer_expired_autosubmit(self) -> None:
        if self._timer_expiry_handled:
            return
        if self.session_state.mode == "practice":
            return
        if not self.complete_workspace_attempt(from_timer=True):
            return
        self._timer_expiry_handled = True
        self.remaining_seconds = 0
        self.timer_paused = True
        self._update_timer_label()
        self._apply_timer_visual_state()

        self._delete_unfinished_attempt()
        self._refresh_parent_history_after_attempt_change()

        if self.paper_mode == "VIEWER_ONLY":
            if self.grade_status_label:
                self.grade_status_label.setText("Time is up.")
            return

        self._set_mark_scheme_unlock(True)
        self._set_grading_mode(True)
        if self.grade_status_label:
            self.grade_status_label.setText("Time is up. Submitting answers...")
        if self.submit_review_subtitle:
            self.submit_review_subtitle.setText(
                "Time is up. Answers were submitted automatically and auto-grading started."
            )
        self._refresh_submit_review_grid()
        if self.exam_stack and self.submit_review_page:
            self.exam_stack.setCurrentWidget(self.submit_review_page)

        if self._grading_in_progress:
            return
        QTimer.singleShot(0, self._start_autograde_from_submit_page)

    def complete_workspace_attempt(self, *, from_timer: bool = False) -> bool:
        """Commit a complete attempt before exposing marking tools or closing UI."""
        if self.session_state.completed:
            return True
        self._sync_exam_clock()
        self.timer.stop()
        self.session_state.completed = True
        self.timer_paused = True
        try:
            import hashlib
            from Core.atomic_storage import atomic_write_json
            from Core.runtime_paths import user_data_path
            if self.questionnaire is not None:
                # Don't remove the last resume snapshot if reading live answers fails.
                self.questionnaire.get_answers()
            entry = self._build_unfinished_attempt_entry()
            key = hashlib.sha256(str(self._attempt_key).encode()).hexdigest()[:24]
            import uuid
            entry["completed_attempt_id"] = uuid.uuid4().hex
            destination = Path(user_data_path("completed_attempts", key, entry["completed_attempt_id"]))
            destination.mkdir(parents=True, exist_ok=True)
            # Unfinished-attempt cleanup must not remove a completed drawing.
            for qid, answer in entry.get("answers", {}).items():
                if isinstance(answer, dict) and answer.get("type") == "drawing":
                    source = str(answer.get("image_path", ""))
                    if source and os.path.isfile(source):
                        image = destination / (hashlib.sha256(qid.encode()).hexdigest()[:16] + ".png")
                        shutil.copy2(source, image)
                        answer["image_path"] = str(image)
            entry["completed_at"] = datetime.now().isoformat(timespec="seconds")
            atomic_write_json(destination / "attempt.json", entry)
            self._completed_attempt_path = str(destination / "attempt.json")
            from Core.study_history import StudyHistory
            StudyHistory.record(entry, 'completed', self._completed_attempt_path)
            if isinstance(self.questionnaire, MathQuestionnaire):
                for qid, answer in entry.get("answers", {}).items():
                    if isinstance(answer, dict) and answer.get("type") == "drawing" and answer.get("image_path"):
                        if qid in self.questionnaire.question_widgets:
                            self.questionnaire.drawing_paths[qid] = answer["image_path"]
                        elif qid in self.questionnaire._pending_answers:
                            self.questionnaire._pending_answers[qid] = dict(answer)
        except Exception as exc:
            self.session_state.completed = False
            self.timer_paused = bool(from_timer)
            if not from_timer:
                self.timer.start(1000)
            show_error(self, "Save attempt", f"Your answers remain open. The completed attempt could not be saved: {exc}")
            return False
        self._stop_autosave_timers()
        self._allow_resume_autosave = False
        self._delete_unfinished_attempt()
        self._refresh_parent_history_after_attempt_change()
        self._set_questionnaire_editable(False)
        self._set_mark_scheme_unlock(True)
        self._set_grading_mode(True)
        self._update_timer_label()
        self._apply_timer_visual_state()
        if self._studio_workspace:
            self._studio_workspace.refresh_status()
            self.submit_btn.setText("Review / Grade")
        self._refresh_submit_review_grid()
        if self.exam_stack and self.submit_review_page:
            self.exam_stack.setCurrentWidget(self.submit_review_page)
        return True

    def end_exam(self, from_timer: bool = False):
        self.timer.stop()
        if from_timer:
            self._handle_timer_expired_autosubmit()
            return

        if self._has_unanswered_questions():
            action = self._prompt_save_unfinished_exam()
            if action == "save":
                self._save_unfinished_attempt()
            elif action == "exit":
                self._delete_unfinished_attempt()
            else:
                if not self.timer_paused:
                    self.timer.start(1000)
                self._apply_timer_visual_state()
                return
        else:
            self._delete_unfinished_attempt()

        self._refresh_parent_history_after_attempt_change()
        self.graceful_exit()

    def graceful_exit(self) -> None:
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return

        self._graceful_exit_in_progress = True
        self._begin_graceful_exit_cleanup()

        if not self._supports_graceful_exit_fade():
            self._complete_graceful_exit()
            return

        try:
            self.setWindowOpacity(1.0)
        except Exception:
            self._complete_graceful_exit()
            return

        self._graceful_exit_timer.start()

    def _supports_graceful_exit_fade(self) -> bool:
        platform_name = str(os.environ.get("QT_QPA_PLATFORM", "")).strip().lower()
        if platform_name in {"offscreen", "minimal"}:
            return False
        if not self.isVisible():
            return False
        try:
            _ = self.windowHandle()
            current = float(self.windowOpacity())
            self.setWindowOpacity(current if current > 0.0 else 1.0)
            return True
        except Exception:
            return False

    def _advance_graceful_exit(self) -> None:
        try:
            current = float(self.windowOpacity())
        except Exception:
            current = 1.0

        next_opacity = max(0.0, current - float(self._graceful_exit_step))
        try:
            self.setWindowOpacity(next_opacity)
        except Exception:
            self._graceful_exit_timer.stop()
            self._complete_graceful_exit()
            return

        if next_opacity <= 0.0:
            self._graceful_exit_timer.stop()
            # Hold briefly so the fade is perceptible (~250ms total).
            QTimer.singleShot(50, self._complete_graceful_exit)

    def _begin_graceful_exit_cleanup(self) -> None:
        if self._graceful_exit_cleanup_started:
            return
        self._graceful_exit_cleanup_started = True
        self._runtime_theme_reapply_requested = False
        self._disconnect_theme_signal()
        # Release rendering immediately, rather than retaining it throughout exit.
        for viewer in self.findChildren(PDFViewer):
            viewer.release_resources()
        for canvas in self.findChildren(DrawingCanvasWidget):
            canvas.close_document_layer()

        try:
            self._try_autosave_unfinished_attempt(force=True)
        except Exception:
            pass
        if not self.session_state.completed:
            try:
                from Core.study_history import StudyHistory
                entry = self._build_unfinished_attempt_entry()
                stored = ExamAttemptManager.get_attempt(self._attempt_key)
                StudyHistory.record(entry, 'saved' if stored else 'abandoned')
            except Exception:
                logging.exception('Could not retain study activity on exit')
        self._stop_autosave_timers()

        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self._grading_heartbeat_timer.stop()
        except Exception:
            pass
        try:
            for viewer in self._iter_insert_page_mode_viewers():
                viewer.hide_listening_audio()
        except Exception:
            pass

        try:
            if self._grading_worker and self._grading_worker.isRunning():
                self._grading_worker.request_cancel()
        except Exception:
            pass
        try:
            if self._periodic_lookup_worker and self._periodic_lookup_worker.isRunning():
                self._periodic_lookup_worker.requestInterruption()
        except Exception:
            pass
        try:
            if self._mark_scheme_download_worker and self._mark_scheme_download_worker.isRunning():
                self._mark_scheme_download_worker.request_cancel()
        except Exception:
            pass

        try:
            if self.calculator_dialog:
                self.calculator_dialog.hide()
        except Exception:
            pass
        try:
            if self.notes_widget is not None:
                self._notes_text_cache = self.notes_widget.notes_text()
            if self.notes_dialog:
                self.notes_dialog.hide()
        except Exception:
            pass
        try:
            if self._settings_window:
                self._settings_window.hide()
        except Exception:
            pass
        try:
            if self._insert_split_dialog:
                self._insert_split_dialog.close()
        except Exception:
            pass


    def _complete_graceful_exit(self) -> None:
        if self._graceful_exit_finalizing:
            return
        self._graceful_exit_in_progress = False
        self._graceful_exit_finalizing = True
        self.close()

    def closeEvent(self, event):
        from Core.background_tasks import gui_work_pending
        if gui_work_pending():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        if not self._graceful_exit_finalizing:
            event.ignore()
            self.graceful_exit()
            return

        try:
            self._save_splitter_layout()
        except Exception:
            pass
        try:
            self._save_calculator_geometry()
            if self.calculator_dialog:
                self.calculator_dialog.hide()
        except Exception:
            pass
        try:
            if self.notes_widget is not None:
                self._notes_text_cache = self.notes_widget.notes_text()
            self._save_notes_geometry()
            if self.notes_dialog:
                self.notes_dialog.hide()
        except Exception:
            pass
        try:
            if self._settings_window:
                self._settings_window.hide()
        except Exception:
            pass
        try:
            if self._insert_split_dialog:
                self._insert_split_dialog.close()
        except Exception:
            pass
        prefetch = getattr(self, "_mark_scheme_prefetch_thread", None)
        try:
            if prefetch is not None and prefetch.isRunning():
                prefetch.request_cancel()
                event.ignore()
                QTimer.singleShot(75, self.close)
                return
        except RuntimeError:
            pass
        try:
            if self._grading_worker and self._grading_worker.isRunning():
                self._grading_worker.request_cancel()
                if self._grading_worker.isRunning():
                    event.ignore()
                    QTimer.singleShot(75, self.close)
                    return
        except Exception:
            pass
        try:
            if self._periodic_lookup_worker and self._periodic_lookup_worker.isRunning():
                self._periodic_lookup_worker.requestInterruption()
                if self._periodic_lookup_worker.isRunning():
                    event.ignore()
                    QTimer.singleShot(75, self.close)
                    return
        except Exception:
            pass
        try:
            if self._mark_scheme_download_worker and self._mark_scheme_download_worker.isRunning():
                self._mark_scheme_download_worker.request_cancel()
                if self._mark_scheme_download_worker.isRunning():
                    event.ignore()
                    QTimer.singleShot(75, self.close)
                    return
        except Exception:
            pass
        try:
            if self.drawing_session_dir and os.path.exists(self.drawing_session_dir):
                shutil.rmtree(self.drawing_session_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            if self._graceful_exit_timer.isActive():
                self._graceful_exit_timer.stop()
        except Exception:
            pass
        self._disconnect_theme_signal()
        self._stop_autosave_timers()
        for viewer in self.findChildren(PDFViewer):
            viewer.release_resources()
        from Core.download_service import remove_owned_temporary_file
        for path in [*self._source_local_paths.values(), self.local_pdf_path, self.mark_scheme_path]:
            remove_owned_temporary_file(path)
        super().closeEvent(event)
        if event.isAccepted():
            self._workspace_lifecycle.leave()

    def showEvent(self, event):
        super().showEvent(event)
        self._workspace_lifecycle.enter()
        if not getattr(self, '_study_started_recorded', False):
            self._study_started_recorded = True
            from Core.study_history import StudyHistory
            StudyHistory.record(self._build_unfinished_attempt_entry(), 'saved' if self.resume_snapshot else 'started')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def on_navigator_select(self, question_num: int):
        if hasattr(self.questionnaire, "scroll_to_question"):
            try:
                self.questionnaire.scroll_to_question(question_num)
            except Exception:
                pass

    def on_mcq_answer_change(self, q_num: int):
        self._on_exam_answer_changed(q_num)

    def on_question_jump_requested(self, q_id: str, page_num: int):
        if self._studio_workspace is not None and q_id in self._studio_workspace.question_ids():
            self._studio_workspace.select_question(q_id)
            return
        page_value: Optional[int] = None
        try:
            page_value = int(page_num)
        except Exception:
            try:
                match = re.search(r"\d+", str(page_num))
                if match:
                    page_value = int(match.group(0))
            except Exception:
                page_value = None
        if page_value is None or page_value <= 0:
            return

        q_id_text = str(q_id or "").strip().lower()
        is_periodic_jump = q_id_text in {"periodic", "periodic_table", "periodictable"}
        if hasattr(self, "pdf_viewer") and self.pdf_viewer:
            try:
                if is_periodic_jump:
                    self.pdf_viewer.auto_rotate_page_if_landscape(max(0, page_value - 1), warn_if_unsupported=True)
                self.pdf_viewer.go_to_page(max(0, page_value - 1))
            except Exception:
                pass
        if hasattr(self.questionnaire, "scroll_to_question"):
            try:
                self.questionnaire.scroll_to_question(q_id)
            except Exception:
                pass
        try:
            self.grade_status_label.setText(f"Jumped to page {page_value}")
        except Exception:
            pass

    def _toggle_focus_mode(self) -> None:
        self.focus_mode_enabled = not bool(self.focus_mode_enabled)
        ConfigManager.set_value("ui.exam.focus_mode_enabled", bool(self.focus_mode_enabled))
        self._apply_focus_mode_visibility()

    def _apply_focus_mode_visibility(self) -> None:
        if self._studio_workspace is not None:
            self._studio_workspace.apply_focus()
            return
        focused = bool(self.focus_mode_enabled)
        if isinstance(getattr(self, "top_bar", None), QWidget):
            self.top_bar.show()
        for name in ("timer_label", "pause_btn", "focus_mode_btn"):
            widget = getattr(self, name, None)
            if isinstance(widget, QWidget):
                widget.show()
        for name in ("paper_info_btn", "question_navigator_btn", "additional_tools_btn", "exam_settings_btn", "grading_mode_btn", "grade_status_label"):
            widget = getattr(self, name, None)
            if isinstance(widget, QWidget):
                widget.setVisible(not focused)
        if isinstance(getattr(self, "focus_mode_btn", None), QPushButton):
            self.focus_mode_btn.setText("Exit Focus" if focused else "Focus Mode")

    def _open_question_navigator_panel(self) -> None:
        if self._studio_workspace is not None:
            self._studio_workspace.toggle_navigator()
            return
        labels = self._question_label_order()
        if not labels:
            show_info(self, "Navigator", "No questions available.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Question Navigator")
        dialog.resize(320, 460)
        root = QVBoxLayout(dialog)
        listing = QListWidget(dialog)
        completion = self._compute_question_completion_state()
        for qid in labels:
            qnorm = normalize_question_id(qid)
            answered = bool(completion.get(qnorm, False))
            reviewed = qnorm in self.question_reviewed
            state = "reviewed" if reviewed else ("attempted" if answered else "unanswered")
            item = QListWidgetItem(f"Q{format_question_display(qnorm)} - {state}")
            item.setData(Qt.ItemDataRole.UserRole, qnorm)
            listing.addItem(item)
        root.addWidget(listing, 1)
        jump = QPushButton("Jump", dialog)
        root.addWidget(jump)

        def _jump() -> None:
            row = listing.currentItem()
            if row is None:
                return
            qnorm = str(row.data(Qt.ItemDataRole.UserRole) or "").strip()
            if not qnorm:
                return
            page_num = 1
            for item in list(getattr(self, "question_items", []) or []):
                if normalize_question_id(str(getattr(item, "canonical_id", ""))) == qnorm:
                    try:
                        page_num = int(getattr(item, "mapped_page", 1) or 1)
                    except Exception:
                        page_num = 1
                    break
            self.on_question_jump_requested(qnorm, page_num)
            dialog.accept()

        jump.clicked.connect(_jump)
        listing.itemDoubleClicked.connect(lambda *_: _jump())
        dialog.exec()

    def open_mark_scheme(self):
        if not self._mark_scheme_view_unlocked:
            show_info(self, "Mark Scheme Locked", "Submit first to unlock mark scheme access.")
            return
        if self.mark_scheme_path and os.path.exists(self.mark_scheme_path):
            if self.session_state.mode == "practice" and not self.session_state.completed:
                self.session_state.assisted = True
                self._mark_resume_snapshot_dirty()
                if self._studio_workspace:
                    self._studio_workspace.refresh_status()
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.mark_scheme_path))
        else:
            show_warning(self, "Mark Scheme", "No mark scheme loaded.")

    def load_mark_scheme(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Mark Scheme", "", "PDF Files (*.pdf)")
        if path:
            self.mark_scheme_path = path
            self._register_pdf_source("mark_scheme", "Mark Scheme", local_path=path)
            self._rebuild_pdf_source_selector()
            self._update_pdf_source_toggle()

    def _desktop_download_dir(self) -> str:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if desktop and os.path.isdir(desktop):
            return desktop
        home = os.path.expanduser("~")
        fallback = os.path.join(home, "Desktop")
        if os.path.isdir(fallback):
            return fallback
        return home

    def _safe_mark_scheme_filename(self, source_url: str) -> str:
        name = os.path.basename(urlparse(source_url).path)
        if not name.lower().endswith(".pdf"):
            name = f"{self.subject_code}_{self.paper_num}_{self.year}_ms.pdf"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
        if not safe:
            safe = f"{self.subject_code}_{self.paper_num}_{self.year}_ms.pdf"
        if not safe.lower().endswith(".pdf"):
            safe = f"{safe}.pdf"
        return safe

    def _next_available_path(self, directory: str, filename: str) -> str:
        candidate = os.path.join(directory, filename)
        if not os.path.exists(candidate):
            return candidate
        stem, ext = os.path.splitext(filename)
        index = 1
        while True:
            candidate = os.path.join(directory, f"{stem} ({index}){ext}")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def download_mark_scheme(self):
        if self.session_state.mode == "exam" and not self.session_state.completed:
            show_info(self, "Mark scheme locked", "Finish the exam to access its mark scheme.")
            return
        if self.session_state.mode == "practice" and not self.session_state.completed:
            self.session_state.assisted = True
            self._mark_resume_snapshot_dirty()
        if self._mark_scheme_download_worker and self._mark_scheme_download_worker.isRunning():
            self.grade_status_label.setText("Cancelling mark-scheme download...")
            self._mark_scheme_download_worker.request_cancel()
            return

        urls = self._build_mark_scheme_candidate_urls()
        if not urls:
            show_error(self, "Download Error", "No PDF URL available.")
            return

        self._set_mark_scheme_download_busy(True)
        self.grade_status_label.setText("Downloading mark scheme...")
        worker = MarkSchemeDownloadWorker(urls)
        worker.progress.connect(self._on_mark_scheme_download_progress)
        worker.finished_download.connect(self._on_mark_scheme_download_finished)
        worker.finished.connect(self._on_mark_scheme_download_thread_done)
        worker.finished.connect(worker.deleteLater)
        self._mark_scheme_download_worker = worker
        worker.start()

    def _set_mark_scheme_download_busy(self, busy: bool) -> None:
        if self.download_ms_btn:
            self.download_ms_btn.setText("Cancel MS Download" if busy else "Download MS")

    def _on_mark_scheme_download_progress(self, message: str) -> None:
        try:
            self.grade_status_label.setText(str(message))
        except Exception:
            pass

    def _on_mark_scheme_download_finished(self, source_url: str, content: object, error_message: str, cancelled: bool) -> None:
        if cancelled:
            self.grade_status_label.setText("Mark-scheme download cancelled")
            return

        payload = bytes(content) if isinstance(content, (bytes, bytearray)) else b""
        if payload:
            try:
                desktop_dir = self._desktop_download_dir()
                filename = self._safe_mark_scheme_filename(source_url or "mark_scheme.pdf")
                out_path = self._next_available_path(desktop_dir, filename)
                with open(out_path, "wb", buffering=_FILE_BUFFER_BYTES) as out_file:
                    out_file.write(payload)
                self.mark_scheme_path = out_path
                self._register_pdf_source("mark_scheme", "Mark Scheme", local_path=out_path)
                self._rebuild_pdf_source_selector()
                self._update_pdf_source_toggle()
                self.grade_status_label.setText("Mark scheme downloaded")
                show_download_complete_dialog(
                    self,
                    "Download Complete",
                    out_path,
                    message_prefix="Mark scheme saved to",
                )
                return
            except Exception as exc:
                error_message = str(exc)

        self.grade_status_label.setText("Mark-scheme download failed")
        show_error(self, "Download Failed", error_message or "Unable to fetch mark scheme.")

    def _on_mark_scheme_download_thread_done(self) -> None:
        self._set_mark_scheme_download_busy(False)
        self._mark_scheme_download_worker = None

    def _build_mark_scheme_candidate_urls(self) -> List[str]:
        if not self.pdf_url:
            return []

        candidates = [
            self.pdf_url.replace("_qp_", "_ms_"),
            self.pdf_url.replace("_QP_", "_MS_"),
            self.pdf_url.replace("_qp", "_ms"),
            self.pdf_url.replace("_QP", "_MS"),
        ]

        # Some mirrors may use path segments rather than filename tags.
        candidates.append(self.pdf_url.replace("/qp/", "/ms/"))
        candidates.append(self.pdf_url.replace("/QP/", "/MS/"))

        deduped: List[str] = []
        seen = set()
        for url in candidates:
            if url and url not in seen:
                deduped.append(url)
                seen.add(url)
        return deduped

    def _download_mark_scheme_candidate(self, silent: bool = True) -> Optional[str]:
        for url in self._build_mark_scheme_candidate_urls():
            try:
                return download_pdf(url)
            except Exception:
                logger.warning("Mark scheme candidate unavailable: %s", url)
        if not silent:
            show_warning(self, "Mark Scheme", "Could not download a valid mark scheme.")
        return None

    def _report_runtime_error(self, context: str, exc: Exception) -> None:
        try:
            trace = traceback.format_exc()
            print(f"[ExamModeError] {context}: {exc}\\n{trace}")
            log_path = os.path.join(tempfile.gettempdir(), "exam_mode_errors.log")
            with open(log_path, "a", encoding="utf-8", buffering=_FILE_BUFFER_BYTES) as f:
                f.write(f"\\n[{datetime.now().isoformat()}] {context}\\n{exc}\\n{trace}\\n")
        except Exception:
            pass

    def auto_grade_paper(self):
        if self.manual_grading_only:
            self.grade_status_label.setText("Manual grading only")
            show_warning(self, "Auto-Grade Unavailable", self._manual_grading_only_warning_message())
            return

        if self._grading_in_progress:
            self.grade_status_label.setText("Grading already in progress")
            show_warning(self, "Auto-Grade", "Grading is already in progress.")
            return

        if self.paper_mode == "VIEWER_ONLY":
            show_warning(
                self,
                "Auto-Grade",
                self.paper_mode_decision.viewer_only_reason or "This paper component is not auto-gradable.",
            )
            return

        if self.paper_mode == "MCQ_ONLY":
            self._grading_in_progress = True
            self._set_grading_controls(True)
            self._set_grading_status("Starting auto-grading...", None)
            try:
                self._auto_grade_mcq()
            except Exception as e:
                self._report_runtime_error("Auto-grade failed", e)
                show_error(self, "Auto-Grade Error", f"Grading failed: {e}")
            finally:
                self._grading_in_progress = False
                self._set_grading_controls(False)
            return

        try:
            self._start_written_grading_worker()
        except Exception as e:
            self._report_runtime_error("Auto-grade failed (written startup)", e)
            self._grading_in_progress = False
            self._set_grading_controls(False)
            self.grade_status_label.setText("Auto-grade failed")
            show_error(self, "Auto-Grade Error", f"Could not start grading: {e}")

    def cancel_auto_grade(self):
        if self._grading_worker and self._grading_worker.isRunning():
            self._grading_worker.request_cancel()
            self._set_grading_status("Cancelling after current step...", None)

    def _set_grading_controls(self, in_progress: bool):
        if self.grade_btn:
            self.grade_btn.setEnabled((not in_progress) and (not self.manual_grading_only))
            if self.manual_grading_only:
                self.grade_btn.setText("Auto-Grade (Unavailable)")
            else:
                self.grade_btn.setText("Auto-Grading..." if in_progress else "Auto-Grade")
        if self.manual_grade_btn:
            self.manual_grade_btn.setEnabled(not in_progress and self.paper_mode != "VIEWER_ONLY")
        if self.submit_btn:
            self.submit_btn.setVisible((self.paper_mode != "VIEWER_ONLY") and (not self._submission_locked_for_autograde))
            self.submit_btn.setEnabled(
                (not in_progress)
                and self.paper_mode != "VIEWER_ONLY"
                and (not self._submission_locked_for_autograde)
            )
        if self.grading_mode_cancel_action:
            self.grading_mode_cancel_action.setEnabled(in_progress)
        if in_progress:
            self._timer_paused_before_grading = self.timer_paused
            self._sync_exam_clock()
            self.timer_paused = True
            self._apply_timer_visual_state()
            try:
                self.timer.stop()
            except Exception:
                pass
            now = time.monotonic()
            self._grading_started_monotonic = now
            self._grading_last_progress_monotonic = now
            self._grading_last_status_message = "Starting auto-grading..."
            self._grading_heartbeat_timer.start()
            self.grade_progress_bar.setVisible(True)
            self.grade_progress_bar.setRange(0, 0)
            self.grade_progress_bar.setFormat("Working...")
            self._update_grading_action_visibility()
            return

        if not self._submission_locked_for_autograde:
            self.timer_paused = getattr(self, '_timer_paused_before_grading', self.timer_paused)
            self._timer_last_monotonic = time.monotonic()
            if not self.timer_paused:
                self.timer.start(1000)
        self._grading_heartbeat_timer.stop()
        self._grading_started_monotonic = None
        self._grading_last_progress_monotonic = None
        self._grading_last_status_message = ""
        self.grade_progress_bar.setVisible(False)
        self.grade_progress_bar.setRange(0, 100)
        self.grade_progress_bar.setValue(0)
        self.grade_progress_bar.setFormat("0%")
        self._apply_timer_visual_state()
        self._update_grading_action_visibility()

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = max(0, int(seconds))
        mins = total // 60
        secs = total % 60
        return f"{mins:02d}:{secs:02d}"

    def _on_grading_heartbeat(self) -> None:
        if not self._grading_in_progress:
            self._grading_heartbeat_timer.stop()
            return

        started = self._grading_started_monotonic or time.monotonic()
        elapsed = time.monotonic() - started
        elapsed_text = self._format_elapsed(elapsed)
        base_message = self._grading_last_status_message or "Auto-grading in progress"

        last_progress = self._grading_last_progress_monotonic or started
        idle_seconds = time.monotonic() - last_progress
        if idle_seconds >= 45:
            status_tail = f"still working ({elapsed_text})"
        else:
            status_tail = f"{elapsed_text} elapsed"
        self.grade_status_label.setText(f"{base_message} | {status_tail}")

    def _set_grading_status(self, message: str, fraction: Optional[float]) -> None:
        now = time.monotonic()
        message_text = str(message or "").strip()
        self._grading_last_status_message = message_text
        if self._grading_in_progress:
            self._grading_last_progress_monotonic = now
            started = self._grading_started_monotonic or now
            elapsed_text = self._format_elapsed(now - started)
            self.grade_status_label.setText(f"{message_text} | {elapsed_text} elapsed")
        else:
            self.grade_status_label.setText(message_text)
        if not self._grading_in_progress:
            return

        self.grade_progress_bar.setVisible(True)
        if fraction is None:
            self.grade_progress_bar.setRange(0, 0)
            self.grade_progress_bar.setFormat("Working...")
            return

        pct = int(max(0.0, min(1.0, float(fraction))) * 100.0)
        self.grade_progress_bar.setRange(0, 100)
        self.grade_progress_bar.setValue(pct)
        self.grade_progress_bar.setFormat(f"{pct}%")

    @staticmethod
    def _resource_url_from_payload(payload: Optional[Dict[str, Any]]) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("direct_url", "download_url", "url", "open_url"):
            candidate = str(payload.get(key) or "").strip()
            if candidate:
                return candidate
        return ""

    @staticmethod
    def _series_from_year_code_token(code: str) -> str:
        token = str(code or "").strip().lower()[:1]
        return {"s": "MJ", "w": "ON", "m": "FM", "y": "SP"}.get(token, "")

    def _resolve_series_for_threshold(self) -> str:
        explicit = str(getattr(self, "series", "") or "").strip().upper()
        if explicit in {"MJ", "ON", "FM", "SP"}:
            return explicit
        for candidate in [self.pdf_url, str(self._source_remote_urls.get("question", "") or "")]:
            parsed = extract_paper_code(str(candidate or "").strip())
            if parsed:
                series = self._series_from_year_code_token(str(parsed.get("year_code", "") or ""))
                if series:
                    return series
        return ""

    def _resolve_component_code_for_threshold(self) -> str:
        digits = "".join(ch for ch in str(self.paper_number_raw or "").strip() if ch.isdigit())
        if len(digits) >= 2:
            return digits[:2]
        for candidate in [self.pdf_url, str(self._source_remote_urls.get("question", "") or "")]:
            parsed = extract_paper_code(str(candidate or "").strip())
            if parsed:
                code = "".join(ch for ch in str(parsed.get("paper", "") or "") if ch.isdigit())
                if len(code) >= 2:
                    return code[:2]
        return ""

    def _resolve_grade_threshold_url(self) -> str:
        resource = self.paper_resources.get("grade_threshold", {}) if isinstance(self.paper_resources, dict) else {}
        url = self._resource_url_from_payload(resource)
        if url:
            return url
        return str(self._source_remote_urls.get("grade_threshold", "") or "").strip()

    @staticmethod
    def _format_threshold_mark(value: Any) -> str:
        if value is None:
            return "-"
        try:
            numeric = float(value)
        except Exception:
            return "-"
        if not math.isfinite(numeric):
            return "-"
        return str(int(round(numeric)))

    def _format_threshold_summary_block(self, interpretation: Dict[str, Any], *, provisional: bool) -> str:
        if not isinstance(interpretation, dict):
            return ""
        candidate_score = float(interpretation.get("candidate_score", 0.0) or 0.0)
        display_total = interpretation.get("max_raw_mark")
        if display_total is None:
            display_total = interpretation.get("total_mark", 0.0)
        try:
            total_mark = float(display_total or 0.0)
        except Exception:
            total_mark = 0.0

        lines: List[str] = [
            "",
            "Grade Thresholds",
            f"Candidate Score: {candidate_score:g} / {total_mark:g}",
        ]

        if not bool(interpretation.get("available", False)):
            message = str(interpretation.get("message", "") or "").strip()
            if not message:
                message = "Grade threshold data unavailable for this paper/session"
            lines.append(message)
            return "\n".join(lines)

        rows = interpretation.get("threshold_rows", [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                grade = str(row.get("grade", "") or "").strip()
                if not grade:
                    continue
                lines.append(f"{grade}: {self._format_threshold_mark(row.get('mark'))}")

        estimated_grade = str(interpretation.get("estimated_grade", "") or "").strip()
        if estimated_grade:
            label = "Estimated Grade (Provisional)" if provisional else "Estimated Grade"
            lines.append(f"{label}: {estimated_grade}")

        next_grade = str(interpretation.get("next_grade_label", "") or "").strip()
        marks_to_next_raw = interpretation.get("marks_to_next")
        if marks_to_next_raw is not None and next_grade:
            try:
                marks_to_next = max(0, int(marks_to_next_raw))
            except Exception:
                marks_to_next = 0
            lines.append(f"Marks to {next_grade}: {marks_to_next}")

        return "\n".join(lines)

    def _build_threshold_interpretation(
        self,
        *,
        candidate_score: float,
        total_mark: float,
    ) -> Dict[str, Any]:
        question_url = str(self._source_remote_urls.get("question", "") or self.pdf_url or "")
        mark_scheme_url = str(self._source_remote_urls.get("mark_scheme", "") or "")
        return run_io(interpret_grade_thresholds, title="Loading grade thresholds…",
            subject_code=self.subject_code,
            year=self.year,
            series=self._resolve_series_for_threshold(),
            component=self._resolve_component_code_for_threshold(),
            candidate_score=float(candidate_score),
            total_mark=float(total_mark),
            grade_threshold_url=self._resolve_grade_threshold_url(),
            question_url=question_url,
            mark_scheme_url=mark_scheme_url,
            past_paper_code=self._derive_paper_code_for_attempt(),
        )

    def _start_written_grading_worker(self):
        answers = self.questionnaire.get_answers()
        if not answers:
            self.grade_status_label.setText("No answers to grade.")
            show_warning(self, "Auto-Grade", "No answers to grade.")
            return

        response_types = {
            normalize_question_id(item.canonical_id): item.response_type
            for item in self.question_items
        }
        section_types = {
            normalize_question_id(item.canonical_id): getattr(item, "section_type", "written")
            for item in self.question_items
        }

        def _has_substantive_response() -> bool:
            for payload in answers.values():
                if isinstance(payload, dict):
                    p_type = str(payload.get("type", "")).strip().lower()
                    if p_type == "drawing":
                        if str(payload.get("image_path", "")).strip():
                            return True
                    else:
                        if str(payload.get("value", "")).strip():
                            return True
                elif str(payload).strip():
                    return True
            return False

        has_drawing_questions = any(v == "drawing" for v in response_types.values())
        if (not _has_substantive_response()) and (not has_drawing_questions):
            self.grade_status_label.setText("No answers to grade.")
            show_warning(self, "Auto-Grade", "No answers to grade.")
            return

        use_ai = should_use_ai_grading(self.subject_code, self.paper_number_raw or str(self.paper_num), self.exam_year)
        if self.paper_mode not in {"WRITTEN_ONLY", "MIXED"}:
            use_ai = False
        if use_ai and not is_ai_configured():
            show_warning(
                self,
                "AI Grading",
                (
                    f"{groq_missing_warning_message(detailed=True)}\n\n"
                    "Short responses may fall back; long-form responses will require manual review."
                ),
            )

        self._grading_in_progress = True
        self._set_grading_controls(True)
        self._set_grading_status("Preparing grading job...", None)

        try:
            question_pdf_path = self._ensure_local_pdf()
            paper_instruction_text = self._extract_paper_instruction_text(question_pdf_path, max_pages=3)
            normalized_marks: Dict[str, float] = {}
            for qid, value in self.question_marks.items():
                q_norm = normalize_question_id(qid)
                try:
                    parsed = float(value)
                    normalized_marks[q_norm] = parsed if math.isfinite(parsed) and parsed > 0 else 1.0
                except Exception:
                    normalized_marks[q_norm] = 1.0

            normalized_mark_hints: Dict[str, float] = {}
            for qid, value in dict(getattr(self, "question_mark_hints", {}) or {}).items():
                q_norm = normalize_question_id(qid)
                if not q_norm:
                    continue
                try:
                    parsed = float(value)
                except Exception:
                    continue
                if math.isfinite(parsed) and parsed > 0:
                    normalized_mark_hints[q_norm] = parsed

            official_total_marks: Optional[float] = None
            for candidate in (
                getattr(self, "official_total_marks", None),
                getattr(self.paper_mode_decision, "total_marks", None),
            ):
                try:
                    parsed = float(candidate)
                except Exception:
                    continue
                if math.isfinite(parsed) and parsed > 0:
                    official_total_marks = float(parsed)
                    break
            if official_total_marks is None:
                parsed_total = parse_total_marks_from_front_page_text(paper_instruction_text)
                if isinstance(parsed_total, int) and parsed_total > 0:
                    official_total_marks = float(parsed_total)

            threshold_series = self._resolve_series_for_threshold()
            threshold_component = self._resolve_component_code_for_threshold()
            grade_threshold_url = self._resolve_grade_threshold_url()
            question_url = str(self._source_remote_urls.get("question", "") or self.pdf_url or "")
            mark_scheme_url = str(self._source_remote_urls.get("mark_scheme", "") or "")

            job = GradingJobInput(
                answers={normalize_question_id(k): v if isinstance(v, dict) else {"type": "text", "value": str(v)} for k, v in answers.items()},
                question_ids=list(self.question_ids),
                question_texts={normalize_question_id(k): v for k, v in self.question_texts.items()},
                question_marks=normalized_marks,
                question_response_types=response_types,
                question_section_types=section_types,
                subject_code=self.subject_code,
                paper_num=self.paper_num,
                year=str(self.year),
                subject_name=str(self.subject_name or ""),
                past_paper_code=self._derive_paper_code_for_attempt(),
                exam_year=int(self.exam_year),
                paper_mode=self.paper_mode,
                pdf_url=self.pdf_url,
                question_pdf_path=question_pdf_path,
                paper_instruction_text=paper_instruction_text,
                mark_scheme_path=self.mark_scheme_path,
                series=threshold_series,
                component_code=threshold_component,
                grade_threshold_url=grade_threshold_url,
                question_url=question_url,
                mark_scheme_url=mark_scheme_url,
                manual_overrides=dict(self.manual_mapping_overrides),
                optional_selection=dict(self.optional_selection_map),
                use_ai=use_ai,
                ai_options=AIGradingOptions(max_ai_calls=0, max_wall_time_sec=0, generate_model_answers=False),
                official_total_marks=official_total_marks,
                question_mark_hints=normalized_mark_hints,
            )

            self._grading_worker = GradingWorker(job)
            self._grading_worker.progress.connect(self._on_grading_progress)
            self._grading_worker.resolved_marks_ready.connect(self._on_resolved_marks_ready)
            self._grading_worker.finished_payload.connect(self._on_grading_finished)
            self._grading_worker.cancelled_payload.connect(self._on_grading_cancelled)
            self._grading_worker.failed.connect(self._on_grading_failed)
            self._grading_worker.finished.connect(self._on_grading_worker_thread_done)
            self._grading_worker.finished.connect(self._grading_worker.deleteLater)
            self._grading_worker.start()
            self._lock_submission_and_answers()
        except Exception:
            self._grading_in_progress = False
            self._set_grading_controls(False)
            raise

    def _on_grading_worker_thread_done(self):
        self._grading_in_progress = False
        self._set_grading_controls(False)
        self._grading_worker = None
        self._update_grading_action_visibility()

    def _on_grading_progress(self, message: str, fraction: float):
        pct = max(0.0, min(1.0, float(fraction))) * 100.0
        self._set_grading_status(f"{message} ({pct:.0f}%)", float(fraction))

    def _on_resolved_marks_ready(self, resolved_marks: Dict[str, float]):
        normalized = {normalize_question_id(k): float(v) for k, v in resolved_marks.items()}
        self.question_marks = normalized
        if hasattr(self.questionnaire, "set_marks"):
            self.questionnaire.set_marks(normalized)

    def _on_grading_finished(self, payload: GradingJobResult):
        try:
            self._last_grading_payload = payload
            self.latest_mapping_report = payload.mapping_report
            self.question_marks = {normalize_question_id(k): float(v) for k, v in payload.resolved_marks.items()}

            if hasattr(self.questionnaire, "set_marks"):
                self.questionnaire.set_marks(self.question_marks)
            if hasattr(self.questionnaire, "set_mapping_status"):
                self.questionnaire.set_mapping_status(payload.mapping_report)

            self._apply_grading_results(payload.results, payload.mapping_report, payload.source_label)
            report_path = str(payload.results.get("grading_report_path", "") or "").strip()
            if report_path:
                self._offer_grading_report_open(report_path)

            if payload.warnings:
                show_warning(self, "Answer Key Mapping", "\n".join(payload.warnings))
            self._grading_last_status_message = "Auto-grading complete."
            self.grade_status_label.setText("Auto-grading complete.")
            self._update_grading_action_visibility()
        except Exception as e:
            self._report_runtime_error("Failed to apply grading results", e)
            show_error(self, "Auto-Grade Error", f"Failed to apply grading results: {e}")
            self.grade_status_label.setText("Auto-grade failed")
            self._update_grading_action_visibility()

    @staticmethod
    def _open_grading_report_path(path: str, *, reveal: bool = False) -> bool:
        target_path = str(path or "").strip()
        if not target_path:
            return False
        if reveal:
            target_path = str(Path(target_path).resolve().parent)
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(target_path)))

    def _offer_grading_report_open(self, report_path: str) -> None:
        path = str(report_path or "").strip()
        if not path or not os.path.exists(path):
            return

        download_dialog = QMessageBox(self)
        download_dialog.setIcon(QMessageBox.Icon.Question)
        download_dialog.setWindowTitle("Grading Report")
        download_dialog.setText("Auto-grade completed.")
        download_dialog.setInformativeText("Do you want to download the grading report?")
        download_yes_btn = download_dialog.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        download_no_btn = download_dialog.addButton("No", QMessageBox.ButtonRole.RejectRole)
        download_dialog.setDefaultButton(download_yes_btn)
        download_dialog.exec()

        clicked = download_dialog.clickedButton()
        if clicked is download_yes_btn:
            self._prompt_grading_report_export(path)
            return
        if clicked is not download_no_btn:
            return

        open_dialog = QMessageBox(self)
        open_dialog.setIcon(QMessageBox.Icon.Question)
        open_dialog.setWindowTitle("Open Grading Report")
        open_dialog.setText("Do you want to open the grading report in Exam Mode?")
        open_yes_btn = open_dialog.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        exit_btn = open_dialog.addButton("Exit", QMessageBox.ButtonRole.DestructiveRole)
        open_dialog.setDefaultButton(open_yes_btn)
        open_dialog.exec()

        open_clicked = open_dialog.clickedButton()
        if open_clicked is open_yes_btn:
            self._open_embedded_grading_report(path)
            return
        if open_clicked is exit_btn:
            self.graceful_exit()

    def _on_grading_cancelled(self, payload: GradingJobResult):
        try:
            self._last_grading_payload = payload
            self.latest_mapping_report = payload.mapping_report
            if payload.resolved_marks:
                self.question_marks = {normalize_question_id(k): float(v) for k, v in payload.resolved_marks.items()}
                if hasattr(self.questionnaire, "set_marks"):
                    self.questionnaire.set_marks(self.question_marks)
            if payload.mapping_report and hasattr(self.questionnaire, "set_mapping_status"):
                self.questionnaire.set_mapping_status(payload.mapping_report)
            if payload.results:
                self._apply_grading_results(payload.results, payload.mapping_report, payload.source_label)
            warning = "\n".join(payload.warnings or ["Grading cancelled."])
            show_warning(self, "Auto-Grade", warning)
            self._grading_last_status_message = "Auto-grading cancelled."
            self.grade_status_label.setText("Auto-grading cancelled.")
            self._update_grading_action_visibility()
        except Exception as e:
            self._report_runtime_error("Failed to apply cancelled grading payload", e)
            show_error(self, "Auto-Grade", f"Cancelled, but result handling failed: {e}")
            self.grade_status_label.setText("Auto-grading cancelled.")
            self._update_grading_action_visibility()

    def _on_grading_failed(self, error_message: str, trace: str):
        try:
            print(f"[ExamModeError] Worker failure: {error_message}\n{trace}")
            log_path = os.path.join(tempfile.gettempdir(), "exam_mode_errors.log")
            with open(log_path, "a", encoding="utf-8", buffering=_FILE_BUFFER_BYTES) as f:
                f.write(
                    f"\n[{datetime.now().isoformat()}] Worker failure\n"
                    f"{error_message}\n{trace}\n"
                )
        except Exception:
            pass
        show_error(self, "Auto-Grade Error", error_message)
        self._grading_last_status_message = "Auto-grade failed"
        self.grade_status_label.setText("Auto-grade failed")

    def _retain_grading_summary(self, results: Dict[str, Any]) -> None:
        """Attach actual marking results to the existing completed answer save."""
        completed_path = getattr(self, '_completed_attempt_path', '')
        if completed_path:
            try:
                from Core.atomic_storage import atomic_write_json
                from Core.study_history import StudyHistory
                with open(completed_path, encoding='utf-8') as handle:
                    saved = json.load(handle)
                saved['grading_summary'] = {key: results.get(key) for key in
                    ('earned_marks', 'total_marks', 'pending_manual_count')}
                atomic_write_json(completed_path, saved)
                StudyHistory.record(saved, 'completed', completed_path)
            except (OSError, ValueError, TypeError):
                logging.exception('Could not retain the grading summary')

    def _apply_grading_results(self, results: Dict[str, Any], mapping_report: MappingReport, source_label: str):
        self._retain_grading_summary(results)
        self.questionnaire.highlight_results(results.get("question_results", {}))
        score = float(results.get("earned_marks", 0) or 0)
        total = float(results.get("total_marks", 0) or 0)
        percent = float(results.get("percentage", 0) or 0)
        auto_graded = float(results.get("auto_graded_marks", score) or 0)
        auto_total = float(results.get("auto_graded_total_marks", total) or 0)
        pending_manual_marks = float(results.get("pending_manual_marks", max(total - auto_total, 0)) or 0)
        final_confirmed = float(results.get("final_confirmed_marks", auto_graded) or 0)
        pending_manual_count = int(results.get("pending_manual_count", 0) or 0)
        ai_applied_count = int(results.get("ai_applied_count", 0) or 0)
        baseline_fallback_count = int(results.get("baseline_fallback_count", 0) or 0)
        short_fallback_count = int(results.get("short_fallback_count", baseline_fallback_count) or 0)
        strict_manual_review_count = int(results.get("strict_manual_review_count", 0) or 0)
        ai_failed_count = int(results.get("ai_failed_count", 0) or 0)
        ai_quota_exhausted = bool(results.get("ai_quota_exhausted", False))
        mode_label = str(results.get("mode", self.paper_mode))

        summary = (
            f"Mode: {mode_label} | Key source: {source_label}\n"
            f"Auto-graded: {auto_graded}/{auto_total} ({percent:.1f}%)\n"
            f"Pending manual: {pending_manual_marks} marks across {pending_manual_count} question(s)\n"
            f"Final confirmed: {final_confirmed}\n"
            f"Mapping coverage: {mapping_report.coverage*100:.1f}% ({source_label})"
        )

        if bool(results.get("ai_used", False)):
            summary += (
                f"\nAI applied: {ai_applied_count}, "
                f"short fallback: {short_fallback_count}, "
                f"strict manual review: {strict_manual_review_count}, "
                f"AI failed: {ai_failed_count}"
            )
        if ai_quota_exhausted:
            summary += "\nAI quota exceeded; grading continued with baseline fallback."
        errors = results.get("grading_errors") or []
        if errors:
            summary += f"\nWarnings: {_summarize_grading_warning(errors)}"
        threshold_payload = results.get("threshold_interpretation")
        if isinstance(threshold_payload, dict):
            threshold_block = self._format_threshold_summary_block(
                threshold_payload,
                provisional=bool(pending_manual_count > 0),
            )
            if threshold_block:
                summary += f"\n{threshold_block}"

        if self.results_panel:
            self.results_panel.update_summary(summary)
            self.results_panel.show()
        self.timer.stop()

    def _auto_grade_written(self):
        # Kept for compatibility; written grading now runs in a background worker.
        self._start_written_grading_worker()

    def review_mapping_overrides(self):
        report = self.latest_mapping_report
        if not report or not report.entries:
            show_warning(self, "Mapping Overrides", "No mapping report available yet.")
            return

        answer_key_ids: List[str] = []
        if self._last_grading_payload and self._last_grading_payload.expanded_key:
            answer_key_ids = list(self._last_grading_payload.expanded_key.keys())
        if not answer_key_ids:
            answer_key_ids = [e.answer_key_id for e in report.entries.values() if e.answer_key_id]
        answer_key_ids = sorted(set(normalize_question_id(k) for k in answer_key_ids if k))
        if not answer_key_ids:
            show_warning(self, "Mapping Overrides", "No answer-key IDs available to map.")
            return

        issue_ids = [
            q_id
            for q_id in self.question_ids
            if not report.entries.get(q_id)
            or not report.entries[q_id].answer_key_id
            or report.entries[q_id].confidence < 0.85
        ]
        if not issue_ids:
            issue_ids = list(self.question_ids)

        dialog = QDialog(self)
        dialog.setWindowTitle("Review Mapping Overrides")
        dialog.resize(760, 460)
        self._apply_selection_dialog_translucent_style(dialog)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Adjust mappings below if any question is linked to the wrong answer key.\n"
            "Apply overrides, then click Auto-Grade again."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        rows = QWidget()
        grid = QGridLayout(rows)
        grid.addWidget(QLabel("Detected Question"), 0, 0)
        grid.addWidget(QLabel("Current Map"), 0, 1)
        grid.addWidget(QLabel("Override"), 0, 2)

        combos: Dict[str, QComboBox] = {}
        for idx, q_id in enumerate(issue_ids[:30], start=1):
            entry = report.entries.get(q_id)
            current = entry.answer_key_id if entry else ""
            grid.addWidget(QLabel(format_question_display(q_id)), idx, 0)
            grid.addWidget(QLabel(current or "Unmapped"), idx, 1)
            combo = QComboBox()
            combo.addItem("")
            for c in answer_key_ids:
                combo.addItem(c)
            if current:
                pos = combo.findText(current)
                if pos >= 0:
                    combo.setCurrentIndex(pos)
            combos[q_id] = combo
            grid.addWidget(combo, idx, 2)

        layout.addWidget(rows)

        button_row = QHBoxLayout()
        close_btn = QPushButton("Close")
        apply_btn = QPushButton("Apply Overrides")
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        button_row.addWidget(apply_btn)
        layout.addLayout(button_row)

        close_btn.clicked.connect(dialog.close)

        def _apply():
            count = 0
            for q_id, combo in combos.items():
                selected = normalize_question_id(combo.currentText())
                if selected:
                    self.manual_mapping_overrides[q_id] = selected
                    count += 1
            dialog.close()
            if count:
                show_info(self, "Mapping Overrides Saved", f"Saved {count} overrides. Re-run Auto-Grade to apply.")

        apply_btn.clicked.connect(_apply)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show()

    def _auto_grade_mcq(self):
        answers = self.questionnaire.get_answers()
        if not answers:
            self.grade_status_label.setText("No answers to grade.")
            show_warning(self, "Auto-Grade", "No answers to grade.")
            return

        if not getattr(self, "mark_scheme_path", None):
            self._set_grading_status("Downloading mark scheme for grading...", 0.1)
            auto_path = self._download_mark_scheme_candidate(silent=True)
            if auto_path:
                self.mark_scheme_path = auto_path
                self._register_pdf_source("mark_scheme", "Mark Scheme", local_path=auto_path)
                self._rebuild_pdf_source_selector()
                self._update_pdf_source_toggle()
            if not getattr(self, "mark_scheme_path", None):
                self.grade_status_label.setText("Mark scheme unavailable.")
                show_warning(self, "Auto-Grade", "Could not load mark scheme for auto-grading.")
                return

        self._set_grading_status("Parsing mark scheme...", 0.35)
        parser = MarkSchemeParser()
        ms_text = parser.extract_text_from_pdf(self.mark_scheme_path)
        expected_ids = {str(i) for i in range(1, int(getattr(self.questionnaire, "num_questions", 0) or len(getattr(self.questionnaire, "radio_buttons", {})) or get_mcq_count(self.subject_code, self.paper_num) or 40) + 1)}
        try:
            correct_answers = parser.validated_mcq_key(ms_text, expected_ids)
        except ValueError as exc:
            self.grade_status_label.setText("Mark scheme incomplete; grading can be retried.")
            show_warning(self, "Cannot Grade Yet", str(exc))
            return
        self._lock_submission_and_answers()

        self._set_grading_status("Comparing answers...", 0.7)
        correct_count = 0
        for q, ans in answers.items():
            if correct_answers.get(q) == ans:
                correct_count += 1

        total = len(correct_answers) if correct_answers else len(answers)
        percent = (correct_count / total * 100) if total > 0 else 0
        threshold_interpretation = self._build_threshold_interpretation(
            candidate_score=float(correct_count),
            total_mark=float(total),
        )
        summary = f"Score: {correct_count}/{total} ({percent:.1f}%)"
        threshold_block = self._format_threshold_summary_block(
            threshold_interpretation if isinstance(threshold_interpretation, dict) else {},
            provisional=False,
        )
        if threshold_block:
            summary = f"{summary}\n{threshold_block}"

        self.questionnaire.highlight_results(correct_answers)
        if self.navigator:
            try:
                self.navigator.update_results(correct_answers, answers)
            except Exception:
                pass
        self.questionnaire.set_enabled(False)
        self.timer.stop()
        self._set_grading_status("Finalizing...", 1.0)
        self.grade_status_label.setText(f"Auto-graded: {correct_count}/{total} ({percent:.1f}%)")
        reflection = self._build_post_exam_reflection(correct_count, total, threshold_interpretation)
        if reflection:
            summary = f"{summary}\n\n{reflection}"

        if self.results_panel:
            self.results_panel.update_summary(summary)
            self.results_panel.show()
        show_info(self, "Auto-Grade", summary)

    def _build_post_exam_reflection(
        self,
        correct_count: int,
        total: int,
        threshold_interpretation: Optional[Dict[str, Any]],
    ) -> str:
        if int(total) <= 0:
            return ""
        percent = (float(correct_count) / float(max(1, total))) * 100.0
        weak_patterns: List[str] = []
        if percent < 50:
            weak_patterns.append("Foundational concept gaps")
            weak_patterns.append("Low answer confidence consistency")
        elif percent < 75:
            weak_patterns.append("Accuracy under time pressure")
            weak_patterns.append("Incomplete final checks")
        else:
            weak_patterns.append("High baseline; optimize speed")
            weak_patterns.append("Refine edge-case handling")
        weak_patterns.append("Exam pacing in final third")
        suggestions = [
            f"Next paper: {self.subject_code} similar component",
            f"Next paper: newer session ({self.series or 'MJ'})",
            "Next paper: one difficulty step up",
        ]
        tasks = [
            "Review low-confidence questions first",
            "Retry incorrect questions in 24h",
            "Run one timed paper this week",
        ]
        lines = ["## Post-Exam Reflection", ""]
        lines.append("Top weak patterns:")
        lines.extend([f"- {entry}" for entry in weak_patterns[:3]])
        lines.append("")
        lines.append("Recommended next papers:")
        lines.extend([f"- {entry}" for entry in suggestions[:3]])
        lines.append("")
        lines.append("Suggested review tasks:")
        lines.extend([f"- {entry}" for entry in tasks[:3]])
        if isinstance(threshold_interpretation, dict):
            grade = str(threshold_interpretation.get("estimated_grade", "") or "").strip()
            if grade:
                lines.append("")
                lines.append(f"- Provisional grade context: {grade}")
        return "\n".join(lines)

    def _load_candidate_answer_key(self) -> Tuple[Dict[str, Dict[str, Any]], str]:
        parser = MarkSchemeParser()
        question_marks = _question_mark_lookup(
            getattr(self, "question_marks", {}),
            getattr(self, "question_mark_hints", {}),
        )

        if (not self.mark_scheme_path or not os.path.exists(self.mark_scheme_path)) and self.pdf_url:
            auto_path = self._download_mark_scheme_candidate(silent=True)
            if auto_path:
                self.mark_scheme_path = auto_path
                self._register_pdf_source("mark_scheme", "Mark Scheme", local_path=auto_path)
                self._rebuild_pdf_source_selector()
                self._update_pdf_source_toggle()

        if self.mark_scheme_path and os.path.exists(self.mark_scheme_path):
            if is_math_subject_code(self.subject_code, self.subject_name):
                math_key = extract_math_mark_scheme(
                    self.mark_scheme_path,
                    expected_question_ids=list(self.question_ids or []),
                )
                if math_key:
                    return math_key, "math mark scheme extractor"
            ms_text = parser.extract_text_from_pdf(self.mark_scheme_path)
            written_key = parser.parse_written_mark_scheme(
                ms_text,
                expected_question_ids=list(self.question_ids or []),
            )
            written_key = _apply_question_paper_mark_validation(written_key, question_marks)
            if written_key:
                return written_key, "loaded/downloaded mark scheme"

        built_in = get_answer_key(self.subject_code, self.paper_num, self.year)
        if built_in:
            normalized = {normalize_question_id(k): dict(v) for k, v in built_in.items()}
            is_generated = normalized and all(bool(v.get("is_generated")) for v in normalized.values())
            source_label = "generated fallback key" if is_generated else "built-in key"
            return normalized, source_label

        generated = {q: {"answer": "[See Mark Scheme]", "marks": self.question_marks.get(q, 1.0)} for q in self.question_ids}
        return generated, "synthetic fallback key"

    def _prompt_mapping_overrides(self, report: MappingReport, answer_key_ids: List[str]) -> Dict[str, str]:
        issue_ids: List[str] = []
        for q_id in self.question_ids:
            entry = report.entries.get(q_id)
            if not entry or not entry.answer_key_id or entry.confidence < 0.65:
                issue_ids.append(q_id)

        if not issue_ids:
            return {}

        dialog = QDialog(self)
        dialog.setWindowTitle("Mapping Overrides (Optional)")
        dialog.resize(720, 420)
        self._apply_selection_dialog_translucent_style(dialog)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Low-confidence or unmatched mappings were detected.\n"
            "You can optionally override them before grading."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        rows = QWidget()
        grid = QGridLayout(rows)
        grid.addWidget(QLabel("Detected Question"), 0, 0)
        grid.addWidget(QLabel("Current Map"), 0, 1)
        grid.addWidget(QLabel("Override"), 0, 2)

        combos: Dict[str, QComboBox] = {}
        candidates = sorted(set(normalize_question_id(k) for k in answer_key_ids))
        for idx, q_id in enumerate(issue_ids[:18], start=1):
            entry = report.entries.get(q_id)
            current = entry.answer_key_id if entry else ""
            grid.addWidget(QLabel(format_question_display(q_id)), idx, 0)
            grid.addWidget(QLabel(current or "Unmapped"), idx, 1)
            combo = QComboBox()
            combo.addItem("")
            for c in candidates:
                combo.addItem(c)
            if current:
                pos = combo.findText(current)
                if pos >= 0:
                    combo.setCurrentIndex(pos)
            combos[q_id] = combo
            grid.addWidget(combo, idx, 2)

        layout.addWidget(rows)

        button_row = QHBoxLayout()
        skip_btn = QPushButton("Skip")
        apply_btn = QPushButton("Apply Overrides")
        button_row.addStretch(1)
        button_row.addWidget(skip_btn)
        button_row.addWidget(apply_btn)
        layout.addLayout(button_row)

        skip_btn.clicked.connect(dialog.reject)
        apply_btn.clicked.connect(dialog.accept)

        overrides: Dict[str, str] = {}
        if dialog.exec():
            for q_id, combo in combos.items():
                selected = normalize_question_id(combo.currentText())
                if selected:
                    overrides[q_id] = selected
        return overrides


# ---------------------------------------------------------------------------
# Mark Scheme Parser
# ---------------------------------------------------------------------------

def _line_is_numeric_mark_value(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(re.fullmatch(r"\d{1,2}", stripped) and 0 <= int(stripped) <= 25)


def _line_has_descriptive_mark_scheme_content(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or re.fullmatch(r"\d{1,3}", stripped):
        return False
    return bool(re.search(r"[A-Za-z<>≤≥=+\-*/()%]", stripped))


def _remove_mark_scheme_artifact_lines(lines: List[str]) -> List[str]:
    if len(lines) < 3:
        return list(lines)

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

    cleaned: List[str] = []
    for idx, line in enumerate(lines):
        stripped = str(line or "").strip()
        if re.fullmatch(r"\d{1,3}", stripped):
            prev_line = _prev_non_empty(idx)
            next_line = _next_non_empty(idx)
            if (
                _line_has_descriptive_mark_scheme_content(prev_line)
                and _line_has_descriptive_mark_scheme_content(next_line)
                and not _line_is_numeric_mark_value(prev_line)
                and not _line_is_numeric_mark_value(next_line)
            ):
                continue
        cleaned.append(str(line or ""))
    return cleaned


def _validate_max_marks(
    extracted_max: float,
    question_paper_total: Optional[float],
    question_id: str,
) -> float:
    if question_paper_total is None:
        return float(extracted_max)
    if abs(float(extracted_max) - float(question_paper_total)) > 1e-9:
        logger.warning(
            "%s: extracted max marks (%s) differs from question paper total (%s). Using question paper total.",
            question_id,
            extracted_max,
            question_paper_total,
        )
        return float(question_paper_total)
    return float(extracted_max)


def _question_mark_lookup(*sources: Optional[Dict[str, Any]]) -> Dict[str, float]:
    resolved: Dict[str, float] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for raw_qid, raw_marks in source.items():
            qid = normalize_question_id(str(raw_qid or ""))
            if not qid:
                continue
            try:
                mark_value = float(raw_marks)
            except Exception:
                continue
            if not math.isfinite(mark_value) or mark_value <= 0.0:
                continue
            resolved[qid] = mark_value
    return resolved


def _apply_question_paper_mark_validation(
    answer_key: Dict[str, Dict[str, Any]],
    question_marks: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    if not answer_key:
        return {}

    validated: Dict[str, Dict[str, Any]] = {}
    for raw_qid, payload in answer_key.items():
        qid = normalize_question_id(str(raw_qid or ""))
        row = dict(payload or {})
        try:
            extracted_marks = float(row.get("marks", 0.0) or 0.0)
        except Exception:
            extracted_marks = 0.0
        question_paper_total = question_marks.get(qid) if qid else None
        resolved_marks = _validate_max_marks(extracted_marks, question_paper_total, qid or str(raw_qid or ""))
        if abs(resolved_marks - extracted_marks) > 1e-9:
            row["marks"] = resolved_marks
            row["max_marks_source"] = "question_paper_hint"
        validated[raw_qid] = row
    return validated


class MarkSchemeParser:
    @staticmethod
    def parse_mark_scheme(ms_text: str) -> Dict[str, str]:
        answers = {}
        pairs = re.compile(r"(?:question\s+|q)?(\d{1,3})[.:]?\s+([A-D])\b", re.I)
        for line in re.split(r"[\r\n]+", str(ms_text)):
            if not re.fullmatch(r"\s*(?:(?:question\s+|q)?\d{1,3}[.:]?\s+[A-D]\s*)+", line, re.I):
                continue
            for number, answer in pairs.findall(line):
                key = str(int(number))
                if key in answers and answers[key] != answer.upper():
                    raise ValueError(f"Conflicting mark-scheme answers for question {key}")
                answers[key] = answer.upper()
        # MuPDF may place a table cell on its own line.
        for number, answer in re.findall(r"(?im)^\s*(\d{1,3})[.:]?[^\S\n]*\n[^\S\n]*([A-D])[^\S\n]*$", str(ms_text)):
            key = str(int(number))
            if key in answers and answers[key] != answer.upper():
                raise ValueError(f"Conflicting mark-scheme answers for question {key}")
            answers[key] = answer.upper()
        return answers

    @staticmethod
    def validated_mcq_key(text: str, expected_ids) -> Dict[str, str]:
        answers = MarkSchemeParser.parse_mark_scheme(text)
        expected = {str(key) for key in expected_ids}
        if not expected or set(answers) != expected:
            missing = sorted(expected - set(answers), key=int)
            extra = sorted(set(answers) - expected, key=int)
            details = []
            if missing:
                details.append("missing questions " + ", ".join(missing))
            if extra:
                details.append("unexpected questions " + ", ".join(extra))
            raise ValueError("The mark scheme does not cover the complete paper (" + "; ".join(details) + "). Load a complete, readable mark scheme and retry.")
        return answers

    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> str:
        if not PDF_AVAILABLE:
            return ""
        try:
            with fitz.open(pdf_path) as doc:
                return "\n".join(page.get_text() for page in doc)
        except Exception:
            logging.getLogger(__name__).warning("Could not read mark scheme", exc_info=True)
            return ""

    @staticmethod
    def parse_written_mark_scheme(
        ms_text: str,
        expected_question_ids: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Parse Cambridge written mark schemes into per-question answer-key rows."""
        if not ms_text:
            return {}

        expected_set = {
            normalize_question_id(qid)
            for qid in (expected_question_ids or [])
            if normalize_question_id(qid)
        }
        expected_main_set = {
            int(parts.main)
            for qid in expected_set
            for parts in [parse_question_id(qid)]
            if parts.valid and parts.main is not None
        }

        lines = [re.sub(r"\s+", " ", str(line or "").strip()) for line in ms_text.splitlines()]
        lines = [line for line in lines if line]

        skip_patterns = [
            r"^cambridge\b",
            r"^\d{4}/\d{2}",
            r"^published$",
            r"^mark scheme$",
            r"^maximum mark",
            r"^page\s+\d+\s+of\s+\d+",
            r"^may/june\s+\d{4}",
            r"^©\s*ucles\s*\d{4}",
            r"^generic marking principles",
            r"^science-specific",
            r"^this document consists of",
            r"^for examiner use",
            r"^additional materials",
        ]
        pure_header_lines = {
            "question",
            "answer",
            "answers",
            "mark",
            "marks",
            "question answer marks",
            "question answer mark",
            "question answers marks",
        }

        qid_pattern = re.compile(
            r"(?<![A-Za-z0-9])(?:Q\s*)?(\d{1,2}(?:\s*\([a-z]\)\s*(?:\([ivx]{1,5}\))?|\s*[a-z](?:[ivx]{1,5})?)?)(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        row_start_pattern = re.compile(
            r"^\s*(?:Q\s*)?(\d{1,2}(?:\s*\([a-z]\)\s*(?:\([ivx]{1,5}\))?|\s*[a-z](?:[ivx]{1,5})?)?)(?:\s+(.*))?$",
            re.IGNORECASE,
        )

        def is_skip(text: str) -> bool:
            low = str(text or "").strip().lower()
            if not low:
                return True
            if low in pure_header_lines:
                return True
            return any(re.match(pattern, low) for pattern in skip_patterns)

        def normalize_qid_candidate(raw_qid: str) -> Optional[str]:
            sample = re.sub(r"\s+", "", str(raw_qid or "").strip().lower())
            sample = sample.rstrip(".,;:|")
            sample = re.sub(r"^q", "", sample)
            if not sample or not re.match(r"^\d", sample):
                return None
            if re.fullmatch(r"\d{4}", sample):
                return None

            qid = normalize_question_id(sample)
            parts = parse_question_id(qid)
            if not parts.valid or parts.main is None:
                return None
            if int(parts.main) < 1 or int(parts.main) > 40:
                return None

            if not expected_set:
                return qid

            if qid in expected_set:
                return qid

            # Keep hierarchical IDs strict when expected IDs are known to avoid algebra false positives.
            if parts.part or parts.subpart:
                return None

            return qid if int(parts.main) in expected_main_set else None

        def line_is_mark_value(text: str) -> Optional[float]:
            stripped = str(text or "").strip()
            if not _line_is_numeric_mark_value(stripped):
                return None
            value = int(stripped)
            return float(value)

        def contains_table_header() -> bool:
            for idx, line in enumerate(lines):
                low = str(line or "").strip().lower()
                if low != "question":
                    continue
                nxt = [str(item or "").strip().lower() for item in lines[idx + 1 : idx + 4]]
                if "answer" in nxt and "marks" in nxt:
                    return True
            return False

        authoritative_table_mode = contains_table_header()

        def can_treat_trailing_int_as_marks(prefix: str, prefix_token_count: int) -> bool:
            text = str(prefix or "").strip()
            if not text:
                return False
            if re.search(r"[<>≤≥⩽⩾]", text):
                return False
            if re.search(r"\bpH\b", text, re.IGNORECASE):
                return False
            if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
                return True
            if re.search(r"[=+\-*/^:%]", text):
                return True
            if prefix_token_count >= 2:
                return True
            return bool(re.search(r"[A-Za-z]", text))

        def split_inline_answer_and_marks(chunk: str) -> Tuple[str, Optional[float]]:
            cleaned = re.sub(r"\s+", " ", str(chunk or "").strip())
            cleaned = re.sub(r"^(?:answer|answers|ans)\s*[:\-]\s*", "", cleaned, flags=re.IGNORECASE)
            if not cleaned:
                return "", None

            explicit = re.search(
                r"(?:\[\s*(\d{1,2})\s*\]|\(\s*(\d{1,2})\s*\)|\bmarks?\s*[:=]?\s*(\d{1,2}))\s*$",
                cleaned,
                flags=re.IGNORECASE,
            )
            if explicit:
                mark_raw = next((group for group in explicit.groups() if group), "")
                if mark_raw:
                    value = int(mark_raw)
                    if 0 <= value <= 25:
                        answer = cleaned[: explicit.start()].strip(" |;:-")
                        return answer, float(value)

            tokens = cleaned.split()
            if len(tokens) >= 2 and re.fullmatch(r"\d{1,2}", tokens[-1]):
                candidate = int(tokens[-1])
                prefix = " ".join(tokens[:-1]).strip(" |;:-")
                if 0 <= candidate <= 25 and can_treat_trailing_int_as_marks(prefix, len(tokens) - 1):
                    return prefix, float(candidate)

            return cleaned, None

        def iter_qid_spans(line: str) -> List[Tuple[int, int, str]]:
            def _prev_non_space(pos: int) -> str:
                idx = pos - 1
                while idx >= 0 and line[idx].isspace():
                    idx -= 1
                return line[idx] if idx >= 0 else ""

            def _next_non_space(pos: int) -> str:
                idx = pos
                while idx < len(line) and line[idx].isspace():
                    idx += 1
                return line[idx] if idx < len(line) else ""

            spans: List[Tuple[int, int, str]] = []
            for match in qid_pattern.finditer(line):
                raw_qid = match.group(1)
                start = int(match.start(1))
                end = int(match.end(1))
                prev_char = line[start - 1] if start > 0 else ""
                next_char = line[end] if end < len(line) else ""
                prev_non_space = _prev_non_space(start)
                next_non_space = _next_non_space(end)
                compact_raw = re.sub(r"\s+", "", str(raw_qid or "").strip())

                # Reject decimal/math-fragment matches such as ".03" or "/15".
                if prev_char in {".", "/", "%"} or next_char in {".", "/", "%"}:
                    continue
                # Reject bracketed mark tokens such as "[1]".
                if (
                    re.fullmatch(r"\d{1,2}", compact_raw)
                    and prev_non_space in {"[", "("}
                    and next_non_space in {"]", ")"}
                ):
                    continue
                # Reject likely algebra fragments for inline candidates.
                if start > 0 and prev_non_space in {"=", "+", "-", "*", "/", "^", ".", "(", "["}:
                    continue

                qid = normalize_qid_candidate(raw_qid)
                if not qid:
                    continue
                if expected_set and qid not in expected_set and start > 2:
                    continue
                parts = parse_question_id(qid)
                if start > 0 and not (parts.part or parts.subpart) and not next_non_space:
                    continue
                spans.append((start, end, qid))

            if not spans:
                return []

            # Drop overlapping/unlikely jumps within one OCR-merged line.
            pruned: List[Tuple[int, int, str]] = []
            last_end = -1
            last_main: Optional[int] = None
            for start, end, qid in spans:
                if start < last_end:
                    continue
                parts = parse_question_id(qid)
                main_num = int(parts.main or 0)
                if last_main is not None and main_num:
                    delta = main_num - last_main
                    if delta > 4 or delta < 0:
                        continue
                    if delta == 0 and not (parts.part or parts.subpart):
                        continue
                pruned.append((start, end, qid))
                last_end = end
                if main_num:
                    last_main = main_num
            return pruned

        def split_line_segments(line: str) -> List[Tuple[Optional[str], str]]:
            spans = iter_qid_spans(line)
            direct = row_start_pattern.match(line)
            if direct and len(spans) <= 1:
                qid = normalize_qid_candidate(str(direct.group(1) or ""))
                if qid:
                    return [(qid, str(direct.group(2) or "").strip(" |;:-"))]

            if not spans:
                return [(None, line)]
            if len(spans) == 1 and spans[0][0] > 2:
                return [(None, line)]

            out: List[Tuple[Optional[str], str]] = []
            first_start = spans[0][0]
            prefix = line[:first_start].strip(" |;:-")
            if prefix:
                out.append((None, prefix))

            for idx, (start, end, qid) in enumerate(spans):
                nxt_start = spans[idx + 1][0] if idx + 1 < len(spans) else len(line)
                segment_text = line[end:nxt_start].strip(" |;:-")
                out.append((qid, segment_text))

            return out or [(None, line)]

        entries: Dict[str, Dict[str, Any]] = {}
        current_qid: Optional[str] = None
        chunk_buffer: List[str] = []

        def flush() -> None:
            nonlocal current_qid, chunk_buffer
            if not current_qid:
                chunk_buffer = []
                return

            working = [re.sub(r"\s+", " ", str(seg or "").strip(" |;:-")) for seg in chunk_buffer if str(seg or "").strip()]
            working = [seg for seg in working if seg and not is_skip(seg) and str(seg).strip().lower() not in pure_header_lines]
            working = [
                re.sub(r"\s+", " ", str(seg or "").strip(" |;:-"))
                for seg in _remove_mark_scheme_artifact_lines(working)
                if str(seg or "").strip()
            ]
            answer_lines: List[str] = []
            if not working:
                marks_value = 0.0 if authoritative_table_mode else 1.0
            else:
                marks_value: Optional[float] = None
                trailing_mark = line_is_mark_value(working[-1])
                if trailing_mark is not None and len(working) >= 2:
                    marks_value = trailing_mark
                    working = working[:-1]

                if working:
                    inline_answer, inline_mark = split_inline_answer_and_marks(working[-1])
                    working[-1] = inline_answer
                    if marks_value is None and inline_mark is not None:
                        marks_value = inline_mark

                answer_lines = [str(seg or "").strip() for seg in working if str(seg or "").strip()]
                if marks_value is None:
                    marks_value = 0.0 if authoritative_table_mode else 1.0

            answer_text = "\n".join(answer_lines).strip()
            if not answer_text:
                answer_text = "[See Mark Scheme]"

            payload = {
                "answer": answer_text,
                "mark_scheme_text": answer_text,
                "marks": float(marks_value),
                "source": "mark_scheme_pdf",
                "max_marks_source": "mark_scheme_row" if float(marks_value) > 0 else "unresolved",
                "mark_scheme_source": "mark_scheme_pdf" if answer_text != "[See Mark Scheme]" else "unresolved",
            }

            existing = entries.get(current_qid)
            if existing:
                prev_answer = str(existing.get("answer", "") or "").strip()
                if (
                    (not prev_answer or prev_answer.startswith("[See"))
                    and payload["answer"]
                    and not str(payload["answer"]).startswith("[See")
                ):
                    existing["answer"] = payload["answer"]
                    existing["mark_scheme_text"] = payload["answer"]
                elif payload["answer"] and len(str(payload["answer"])) > len(prev_answer):
                    existing["answer"] = payload["answer"]
                    existing["mark_scheme_text"] = payload["answer"]
                existing["marks"] = max(float(existing.get("marks", 0.0)), float(payload["marks"]))
                if float(existing.get("marks", 0.0) or 0.0) > 0:
                    existing["max_marks_source"] = "mark_scheme_row"
                if payload["answer"] and payload["answer"] != "[See Mark Scheme]":
                    existing["mark_scheme_source"] = "mark_scheme_pdf"
            else:
                entries[current_qid] = payload

            current_qid = None
            chunk_buffer = []

        in_table = not authoritative_table_mode
        header_pending = 0

        for idx, line in enumerate(lines):
            low = str(line or "").strip().lower()

            if authoritative_table_mode and not in_table:
                if low == "question":
                    nxt = [str(item or "").strip().lower() for item in lines[idx + 1 : idx + 4]]
                    if "answer" in nxt and "marks" in nxt:
                        in_table = True
                        header_pending = 2
                continue

            if header_pending > 0:
                header_pending -= 1
                continue

            if low in pure_header_lines:
                continue
            if is_skip(line) and not current_qid:
                continue
            if current_qid and authoritative_table_mode and line_is_mark_value(line) is not None:
                chunk_buffer.append(str(line).strip())
                continue
            if current_qid and authoritative_table_mode and expected_set:
                direct = row_start_pattern.match(line)
                if direct:
                    possible_qid = normalize_qid_candidate(str(direct.group(1) or ""))
                    if possible_qid and possible_qid not in expected_set:
                        chunk_buffer.append(str(line).strip())
                        continue

            segments = split_line_segments(line)
            has_qid = any(seg_qid for seg_qid, _ in segments)

            if not has_qid:
                if current_qid and not is_skip(line):
                    chunk_buffer.append(line)
                continue

            for seg_qid, seg_text in segments:
                seg_clean = re.sub(r"\s+", " ", str(seg_text or "").strip())
                if seg_qid:
                    flush()
                    current_qid = seg_qid
                    chunk_buffer = []
                    if seg_clean:
                        chunk_buffer.append(seg_clean)
                elif current_qid and seg_clean and not is_skip(seg_clean):
                    chunk_buffer.append(seg_clean)

        flush()
        return entries


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch_exam_mode(
    parent,
    subject_code,
    subject_name,
    paper_num,
    year,
    series: Optional[str] = None,
    pdf_url=None,
    resume_snapshot=None,
    paper_resources: Optional[Dict[str, Dict[str, str]]] = None,
    manual_grading_only: bool = False,
    manual_grading_only_reason: str = "",
    session_mode: Optional[str] = None,
):
    if session_mode is None and not resume_snapshot:
        from UI.exam_workspace import choose_session_mode
        session_mode = choose_session_mode(parent)
        if session_mode is None:
            return None
    window = ExamModeWindow(
        parent,
        subject_code,
        subject_name,
        paper_num,
        year,
        series=series,
        pdf_url=pdf_url,
        resume_snapshot=resume_snapshot,
        paper_resources=paper_resources,
        manual_grading_only=manual_grading_only,
        manual_grading_only_reason=manual_grading_only_reason,
        session_mode=session_mode or "exam",
    )
    if isinstance(parent, QWidget):
        import weakref
        parent._active_exam_window = window
        owner = weakref.ref(parent)
        def release_owner(*_):
            main = owner()
            if main is not None:
                try:
                    main._active_exam_window = None
                except RuntimeError:
                    pass
        window.destroyed.connect(release_owner)
    from PySide6.QtWidgets import QLayout
    # The adaptive workspace owns its minimum sizes. Let the native full-screen
    # window fit the screen even while the splitter changes orientation.
    window.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    window.setMinimumSize(0, 0)
    window.showFullScreen()
    return window
