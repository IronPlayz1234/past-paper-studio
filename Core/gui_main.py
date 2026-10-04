"""
Past Paper Studio GUI - Main Application (PySide6)
A modern, easy-to-use interface for finding Cambridge past papers.
"""

import os
import logging
import importlib.util
import re
import math
import sys
import time
import tempfile
import subprocess
import webbrowser
import difflib
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Core.background_tasks import run_io
from Core.download_service import download_file, download_pdf, safe_filename as sanitize_filename
from Core.cache_tools import BudgetCache

from Core.runtime_tuning import configure_error_only_logging, file_buffer_size_bytes

try:
    import shiboken6
except Exception:  # pragma: no cover - optional runtime dependency fallback
    shiboken6 = None  # type: ignore[assignment]
from PySide6.QtCore import Qt, QAbstractAnimation, QEasingCurve, QEvent, QEventLoop, QLockFile, QParallelAnimationGroup, QRectF, QPropertyAnimation, QStandardPaths, QStringListModel, QTimer, QVariantAnimation, Property, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QPaintEvent, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QCompleter, QDialog, QFileDialog, QInputDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QGraphicsDropShadowEffect, QGraphicsPixmapItem, QGridLayout, QLayout, QRadioButton, QProgressBar, QScrollArea, QGraphicsScene, QGraphicsView, QSizePolicy, QPlainTextEdit, QTextEdit, QTextBrowser, QToolButton, QSplitter, QVBoxLayout, QWidget, QTabWidget
try:
    from PySide6.QtSvgWidgets import QSvgWidget
except Exception:  # pragma: no cover - optional runtime dependency fallback
    QSvgWidget = None  # type: ignore[assignment]
from UI.theme import get_theme_manager, ThemeManager
from UI.floating_settings_window import FloatingSettingsWindow
from UI.font_system import DEFAULT_FONT_OPTION, discover_available_ui_fonts, sanitize_font_choice
from UI.command_palette import CommandPaletteDialog
from UI.startup_splash import BetaBootSplashWindow
from UI.studio_startup import StudioBootSplashWindow
from UI.startup_motion import startup_redesign_enabled
from UI.static_theme_surface import StaticThemeSurface
from shiboken6 import isValid

from Utils.gui_utils import (
    Colors,
    SubjectDatabase,
    ComponentsDatabase,
    ExamAttemptManager,
    HistoryManager,
    ConfigManager,
    parse_range,
    show_error,
    show_info,
    show_download_complete_dialog,
    show_warning,
    show_toast,
    setup_appearance,
    save_groq_settings,
    load_groq_api_key,
    load_groq_text_model,
    load_groq_vision_model,
    is_groq_configured,
    groq_missing_warning_message,
    should_show_groq_startup_warning,
    LoadingDialog,
    SearchThread,
)
from Utils.sources_manager import PaperGroup, PaperResource, PaperSourceManager
from Grading.ai_config import get_ai_config
from Grading.ai_grading import send_prompt_with_ai
from Core.paper_mode_router import resolve_mode
from Data.paper_structures import (
    calculate_marks_from_structure,
    extract_paper_code,
    generate_question_ids_from_structure,
    get_paper_structure,
)
from Data.exam_data import get_exam_duration
from Data.subjects_structure import infer_exam_year
from Data.app_metadata import APP_NAME
from Data.user_documentation import build_user_documentation_markdown, groq_setup_instructions_plain
from Core.runtime_paths import path_exists, resource_path

try:
    from Core import pdf_service as fitz  # PyMuPDF
    _PDF_PREVIEW_AVAILABLE = True
except Exception:
    fitz = None  # type: ignore[assignment]
    _PDF_PREVIEW_AVAILABLE = False

try:
    _HAS_EXAM_MODE_SPEC = importlib.util.find_spec("Core.exam_mode") is not None
except Exception:
    _HAS_EXAM_MODE_SPEC = False
EXAM_MODE_AVAILABLE = bool(path_exists("Core", "exam_mode.py") or _HAS_EXAM_MODE_SPEC)
_LAUNCH_EXAM_MODE: Optional[Callable[..., Any]] = None
_EXAM_MODE_IMPORT_ERROR: Optional[str] = None

_AUDIO_STREAM_BASE_URL = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
_FILE_BUFFER_BYTES = file_buffer_size_bytes()
_PYTHON_REEXEC_ENV = "PAST_PAPER_FINDER_SKIP_PYTHON_REEXEC"
_APP_LOCK_DIR_NAME = "past-paper-finder"
_APP_LOCK_FILE_NAME = "past-paper-finder.lock"
_APP_INSTANCE_LOCK: Optional[QLockFile] = None


def get_audio_url(paper_id: str) -> str:
    """Build a direct audio stream URL for a normalized paper id stem."""
    stem = str(paper_id or "").strip()
    stem = os.path.splitext(stem)[0]
    stem = os.path.basename(stem).strip().lower()
    stem = re.sub(r"_(?:qp|ms|gt|in|tn)_(\d{1,2})$", r"_sf_\1", stem, flags=re.IGNORECASE)
    if not stem:
        return ""
    return f"{_AUDIO_STREAM_BASE_URL}/{stem}.mp3"


def _resolve_exam_mode_launcher() -> Optional[Callable[..., Any]]:
    """Lazy-load exam_mode to keep startup memory/time low."""
    global _LAUNCH_EXAM_MODE, _EXAM_MODE_IMPORT_ERROR
    if _LAUNCH_EXAM_MODE is not None:
        return _LAUNCH_EXAM_MODE
    if not EXAM_MODE_AVAILABLE:
        return None
    try:
        from Core.exam_mode import launch_exam_mode as _launch_exam_mode

        _LAUNCH_EXAM_MODE = _launch_exam_mode
        return _LAUNCH_EXAM_MODE
    except Exception as exc:
        _EXAM_MODE_IMPORT_ERROR = str(exc)
        return None


@dataclass(slots=True)
class ExamModeLaunchCandidate:
    """Single launchable paper candidate for standalone exam mode."""

    item: Dict[str, Any]
    paper_resources: Dict[str, Dict[str, str]]
    label: str
    year: str
    series: str
    paper_num: str
    variant: str


class SelectionDialog(QDialog):
    """Disambiguation picker shown when multiple exam papers match filters."""

    def __init__(self, candidates: List[ExamModeLaunchCandidate], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Select Paper")
        self.setModal(True)
        self.resize(700, 520)

        self._candidates = list(candidates or [])
        self._selected_index: Optional[int] = None
        self._option_buttons: List[QPushButton] = []
        self._option_labels: List[str] = []
        self.start_exam_button = QPushButton("Start Exam")
        self.start_exam_button.setEnabled(False)
        self.start_exam_button.clicked.connect(self._on_start_exam_clicked)

        self.setStyleSheet(
            "QPushButton[selectionOption='true'] {"
            "text-align: left;"
            "padding: 10px 12px;"
            "border-radius: 8px;"
            "border: 1px solid palette(mid);"
            "background-color: palette(button);"
            "color: palette(button-text);"
            "}"
            "QPushButton[selectionOption='true']:hover:!checked {"
            "border: 1px solid palette(highlight);"
            "}"
            "QPushButton[selectionOption='true']:checked {"
            "background-color: palette(button);"
            "color: palette(button-text);"
            "border: 1px solid palette(highlight);"
            "font-weight: 600;"
            "}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        heading = QLabel("Select a paper before starting Exam Mode.")
        heading.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        root.addWidget(heading)

        years = {c.year for c in self._candidates if c.year}
        series = {c.series for c in self._candidates if c.series}
        variants = {c.variant for c in self._candidates if c.variant}
        summary_bits: List[str] = []
        if len(years) > 1:
            summary_bits.append(f"{len(years)} years")
        if len(series) > 1:
            summary_bits.append(f"{len(series)} series")
        if len(variants) > 1:
            summary_bits.append(f"{len(variants)} variants")
        if summary_bits:
            summary = QLabel(
                "Multiple options were found across " + ", ".join(summary_bits) + ". Choose one paper to continue."
            )
        else:
            summary = QLabel("Multiple papers were found. Choose one paper to continue.")
        summary.setWordWrap(True)
        root.addWidget(summary)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        options_host = QWidget(scroll)
        options_layout = QVBoxLayout(options_host)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(8)

        if not self._candidates:
            empty = QLabel("No question papers are available for the current filters.")
            empty.setWordWrap(True)
            options_layout.addWidget(empty)
        else:
            for index, candidate in enumerate(self._candidates):
                button = QPushButton(candidate.label)
                button.setProperty("selectionOption", True)
                button.setCheckable(True)
                button.setAutoExclusive(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip(candidate.label)
                button.setMinimumHeight(44)
                button.toggled.connect(lambda checked, idx=index: self._on_option_toggled(idx, checked))
                self._option_buttons.append(button)
                self._option_labels.append(candidate.label)
                options_layout.addWidget(button)
            options_layout.addStretch(1)
            self._refresh_option_labels()

        scroll.setWidget(options_host)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)
        actions.addWidget(self.start_exam_button)
        root.addLayout(actions)

    def _on_option_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self._selected_index = index
        elif self._selected_index == index:
            self._selected_index = None
        self.start_exam_button.setEnabled(self._selected_index is not None)
        self._refresh_option_labels()

    def _refresh_option_labels(self) -> None:
        for index, button in enumerate(self._option_buttons):
            marker = "☑" if button.isChecked() else "☐"
            button.setText(f"{marker} {self._option_labels[index]}")

    def _on_start_exam_clicked(self) -> None:
        if self.selected_candidate() is None:
            return
        self.accept()

    def _focus_selection_index(self, index: int) -> bool:
        if not self._option_buttons:
            return False
        clamped = max(0, min(len(self._option_buttons) - 1, int(index)))
        button = self._option_buttons[clamped]
        if not isinstance(button, QPushButton) or not button.isEnabled():
            return False
        button.setChecked(True)
        button.setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if not self._option_buttons:
            super().keyPressEvent(event)
            return
        if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key in {Qt.Key.Key_Up, Qt.Key.Key_Left, Qt.Key.Key_Down, Qt.Key.Key_Right}:
            if self._selected_index is None:
                moved = self._focus_selection_index(0)
            else:
                step = -1 if key in {Qt.Key.Key_Up, Qt.Key.Key_Left} else 1
                moved = self._focus_selection_index(self._selected_index + step)
            if moved:
                event.accept()
                return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if self._selected_index is not None:
                self._on_start_exam_clicked()
                event.accept()
                return
        super().keyPressEvent(event)

    def selected_candidate(self) -> Optional[ExamModeLaunchCandidate]:
        if self._selected_index is None:
            return None
        if self._selected_index < 0 or self._selected_index >= len(self._candidates):
            return None
        return self._candidates[self._selected_index]


class DashboardCard(QFrame):
    """Card widget with fast hover lift used across dashboard surfaces."""

    activated = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        theme_role: str = "resultCard",
        clickable: bool = False,
    ):
        super().__init__(parent)
        normalized_role = str(theme_role or "resultCard").strip()
        self.setProperty("themeRole", normalized_role)
        self._is_history_card = normalized_role == "historyCard"
        self._disable_layout_lift = self._is_history_card
        self._clickable = bool(clickable)
        self._hover_progress = 0.0
        self._base_margins: Optional[Tuple[int, int, int, int]] = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self._clickable else Qt.FocusPolicy.NoFocus)
        if self._clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._shadow_effect: Optional[QGraphicsDropShadowEffect] = None
        if not self._is_history_card:
            try:
                shadow = QGraphicsDropShadowEffect(self)
                shadow.setOffset(0, 1)
                shadow.setBlurRadius(6.0)
                shadow.setColor(QColor(0, 0, 0, 35))
                self.setGraphicsEffect(shadow)
                self._shadow_effect = shadow
            except Exception:
                self._shadow_effect = None

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(100)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.setStartValue(0.0)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.valueChanged.connect(self._on_hover_progress)

    def _refresh_hover_property(self) -> None:
        self.setProperty("hovered", bool(self._hover_progress > 0.01))
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)
        self.update()

    def _on_hover_progress(self, value: object) -> None:
        try:
            t = max(0.0, min(1.0, float(value)))
        except Exception:
            t = 0.0
        self._hover_progress = t
        layout = self.layout()
        if layout is not None and not self._disable_layout_lift:
            if self._base_margins is None:
                margins = layout.contentsMargins()
                self._base_margins = (margins.left(), margins.top(), margins.right(), margins.bottom())
            left, top, right, bottom = self._base_margins
            inset = int(round(2.0 * t))
            layout.setContentsMargins(max(0, left - inset), max(0, top - inset), max(0, right - inset), max(0, bottom - inset))
        if self._shadow_effect is not None:
            try:
                blur = (4.0 + (6.0 * t)) if self._disable_layout_lift else (6.0 + (10.0 * t))
                offset = (0.0 + (1.0 * t)) if self._disable_layout_lift else (1.0 + (2.0 * t))
                self._shadow_effect.setBlurRadius(blur)
                self._shadow_effect.setOffset(0, offset)
                alpha = int(35 + (70 * t))
                self._shadow_effect.setColor(QColor(0, 0, 0, max(0, min(120, alpha))))
            except Exception:
                pass
        self._refresh_hover_property()

    def _animate_hover(self, hovering: bool) -> None:
        target = 1.0 if hovering else 0.0
        start = float(self._hover_progress)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(start)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):  # type: ignore[override]
        self._animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # type: ignore[override]
        self._animate_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # type: ignore[override]
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent):  # type: ignore[override]
        if self._clickable and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class QuickLookPreviewFrame(QFrame):
    """Preview surface that accepts wheel/trackpad input for page navigation."""

    scrollRequested = Signal(int)
    zoomRequested = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self._wheel_accumulator = 0.0
        self._wheel_threshold = 240.0
        self._pinch_last_total_scale = 1.0

    @staticmethod
    def _has_zoom_modifier(modifiers: Qt.KeyboardModifiers) -> bool:
        mask = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        return bool(modifiers & mask)

    @staticmethod
    def _extract_wheel_delta(event) -> Tuple[float, float]:
        angle_y = 0.0
        pixel_y = 0.0
        try:
            angle_y = float(event.angleDelta().y())
        except Exception:
            angle_y = 0.0
        try:
            pixel = event.pixelDelta()
            pixel_y = float(pixel.y()) if pixel is not None else 0.0
        except Exception:
            pixel_y = 0.0
        return angle_y, pixel_y

    def _attached_scroll_area(self) -> Optional[QScrollArea]:
        candidate = self.property("quickLookScrollArea")
        if isinstance(candidate, QScrollArea):
            return candidate
        return None

    def _apply_smooth_scroll(self, delta_y: float) -> Tuple[bool, float]:
        area = self._attached_scroll_area()
        if not isinstance(area, QScrollArea):
            return False, 0.0
        bar = area.verticalScrollBar()
        if bar is None:
            return False, 0.0
        minimum = int(bar.minimum())
        maximum = int(bar.maximum())
        if maximum <= minimum:
            return False, 0.0
        before = int(bar.value())
        step = int(round(float(delta_y)))
        if step == 0:
            if delta_y > 0.0:
                step = 1
            elif delta_y < 0.0:
                step = -1
        target = max(minimum, min(maximum, before - step))
        bar.setValue(target)
        after = int(bar.value())
        overflow = 0.0
        if after == before:
            if before <= minimum and delta_y > 0.0:
                overflow = float(delta_y)
            elif before >= maximum and delta_y < 0.0:
                overflow = float(delta_y)
        return True, overflow

    def _handle_native_zoom_gesture(self, event: object) -> bool:
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
        self.zoomRequested.emit(math.exp(amount * 0.45))
        if hasattr(event, "accept"):
            event.accept()  # type: ignore[attr-defined]
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
        self.zoomRequested.emit(delta)
        if hasattr(event, "accept"):
            event.accept()  # type: ignore[attr-defined]
        return True

    def wheelEvent(self, event):  # type: ignore[override]
        angle_y, pixel_y = self._extract_wheel_delta(event)
        if abs(angle_y) < 1e-6 and abs(pixel_y) < 1e-6:
            super().wheelEvent(event)
            return

        if self._has_zoom_modifier(event.modifiers()):
            units = (angle_y / 120.0) if abs(angle_y) >= 1e-6 else (pixel_y / 120.0)
            scale = math.exp(units * 0.09)
            if abs(scale - 1.0) >= 1e-6:
                self.zoomRequested.emit(scale)
                event.accept()
                return

        delta_y = angle_y if abs(angle_y) >= 1e-6 else (pixel_y * 8.0)
        smooth_used, edge_delta = self._apply_smooth_scroll(delta_y)
        if smooth_used:
            if abs(edge_delta) >= 1e-6:
                if self._wheel_accumulator and ((self._wheel_accumulator > 0.0) != (edge_delta > 0.0)):
                    self._wheel_accumulator = 0.0
                self._wheel_accumulator += float(edge_delta)
                while abs(self._wheel_accumulator) >= self._wheel_threshold:
                    self.scrollRequested.emit(1 if self._wheel_accumulator < 0 else -1)
                    self._wheel_accumulator -= math.copysign(self._wheel_threshold, self._wheel_accumulator)
            else:
                self._wheel_accumulator = 0.0
            event.accept()
            return

        if self._wheel_accumulator and ((self._wheel_accumulator > 0.0) != (delta_y > 0.0)):
            self._wheel_accumulator = 0.0
        self._wheel_accumulator += float(delta_y)

        emitted = False
        while abs(self._wheel_accumulator) >= self._wheel_threshold:
            self.scrollRequested.emit(1 if self._wheel_accumulator < 0 else -1)
            self._wheel_accumulator -= math.copysign(self._wheel_threshold, self._wheel_accumulator)
            emitted = True
        if emitted or abs(delta_y) >= 1e-6:
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event):  # type: ignore[override]
        etype = event.type()
        if etype == QEvent.Type.NativeGesture:
            if self._handle_native_zoom_gesture(event):
                return True
        elif etype in {QEvent.Type.GestureOverride, QEvent.Type.Gesture}:
            if self._handle_pinch_gesture(event):
                return True
        return super().event(event)


class QuickLookGraphicsView(QGraphicsView):
    """Graphics view used by detached quick-look window."""

    zoomRequested = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self._pinch_last_total_scale = 1.0

    def _handle_native_zoom_gesture(self, event: object) -> bool:
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
        self.zoomRequested.emit(math.exp(amount * 0.45))
        if hasattr(event, "accept"):
            event.accept()  # type: ignore[attr-defined]
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
        self.zoomRequested.emit(delta)
        if hasattr(event, "accept"):
            event.accept()  # type: ignore[attr-defined]
        return True

    def wheelEvent(self, event):  # type: ignore[override]
        modifiers = event.modifiers()
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            delta = 0.0
            try:
                delta = float(event.angleDelta().y())
            except Exception:
                delta = 0.0
            if abs(delta) < 1e-6:
                try:
                    pixel = event.pixelDelta()
                    delta = float(pixel.y()) if pixel is not None else 0.0
                except Exception:
                    delta = 0.0
            if abs(delta) >= 1e-6:
                units = delta / 120.0
                self.zoomRequested.emit(math.exp(units * 0.09))
                event.accept()
                return
        super().wheelEvent(event)

    def event(self, event):  # type: ignore[override]
        etype = event.type()
        if etype == QEvent.Type.NativeGesture:
            if self._handle_native_zoom_gesture(event):
                return True
        elif etype in {QEvent.Type.GestureOverride, QEvent.Type.Gesture}:
            if self._handle_pinch_gesture(event):
                return True
        return super().event(event)


class SearchOptionCheckBox(QCheckBox):
    """Make the entire filter control clickable, including its styled padding."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        # Keyboard focus is drawn by our QSS; suppress the native macOS halo.
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)

    def hitButton(self, pos):
        return self.rect().contains(pos)


class PastPaperFinderGUI(QMainWindow):
    """Main GUI Application for Past Paper Studio"""
    AI_PREFLIGHT_PROMPT = "Reply with exactly: hello"
    AI_PREFLIGHT_TIMEOUT_SEC = 20.0

    def __init__(self):
        super().__init__()
        from UI.localization import get_locale_manager
        get_locale_manager()

        self.setWindowTitle(f"{APP_NAME} - Cambridge Exams")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        self.current_level = "IGCSE"
        self.subject_code = ""
        self.subject_name = ""
        self.search_results = []
        self.groq_api_key = load_groq_api_key()
        self.groq_text_model = load_groq_text_model()
        self.groq_vision_model = load_groq_vision_model()
        self._last_ai_preflight_error = ""
        self._central_widget: Optional[QWidget] = None
        self.launch_exam_btn: Optional[QPushButton] = None
        self.settings_btn: Optional[QPushButton] = None
        self.search_button: Optional[QPushButton] = None
        self.open_all_button: Optional[QPushButton] = None
        self.download_all_button: Optional[QPushButton] = None
        self._settings_window: Optional[FloatingSettingsWindow] = None
        self.loading: Optional[LoadingDialog] = None
        self.search_thread: Optional[SearchThread] = None
        self._orphan_search_threads: List[SearchThread] = []
        self._active_search_generation: int = 0
        self._history_search_request_generation: int = 0
        self._available_ui_fonts: List[str] = discover_available_ui_fonts()
        self._user_docs_dialog: Optional[QDialog] = None
        self._user_docs_browser: Optional[QTextBrowser] = None
        self._restore_settings_after_user_docs = False
        self._text_context_registered_widget_ids: set[int] = set()
        self._subject_live_search_connected = False
        self._sidebar_expanded_width: int = 360
        self._sidebar_collapsed_width: int = 56
        self._sidebar_is_collapsed: bool = False
        self._sidebar_is_animating: bool = False
        self._sidebar_animation_target_width: int = self._sidebar_expanded_width
        self._sidebar_current_width: int = self._sidebar_expanded_width
        self._sidebar_animation: Optional[QPropertyAnimation] = None
        self.main_content_splitter: Optional[QSplitter] = None
        self.control_center_sections_splitter: Optional[QWidget] = None
        self._results_view_mode: str = "list"
        self._results_view_rerender_generation: int = 0
        self._results_skeleton_timer = QTimer(self)
        self._results_skeleton_timer.setInterval(90)
        self._results_skeleton_timer.timeout.connect(self._tick_results_skeleton_shimmer)
        self._results_theme_refresh_timer = QTimer(self)
        self._results_theme_refresh_timer.setSingleShot(True)
        self._results_theme_refresh_timer.setInterval(90)
        self._results_theme_refresh_timer.timeout.connect(self._flush_results_theme_refresh)
        self._search_state_watchdog = QTimer(self)
        self._search_state_watchdog.setInterval(150)
        self._search_state_watchdog.timeout.connect(self._recover_search_button_state)
        self._results_skeleton_bars: List[QFrame] = []
        self._results_skeleton_phase: float = 0.0
        self._results_skeleton_active: bool = False
        self._quick_look_pixmap_cache = BudgetCache()
        self._quick_look_pdf_cache: Dict[str, str] = {}
        self._active_quick_look_frame: Optional[QFrame] = None
        self._quick_look_window: Optional[QDialog] = None
        self._quick_look_window_view: Optional[QuickLookGraphicsView] = None
        self._quick_look_window_scene: Optional[QGraphicsScene] = None
        self._quick_look_window_pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._quick_look_window_prev_btn: Optional[QPushButton] = None
        self._quick_look_window_next_btn: Optional[QPushButton] = None
        self._quick_look_window_page_label: Optional[QLabel] = None
        self._quick_look_window_zoom_label: Optional[QLabel] = None
        self._quick_look_window_state: Dict[str, Any] = {}
        self._empty_state_svg_path = resource_path("UI", "assets", "empty_state_no_results.svg")
        self._results_theme_refresh_scheduled: bool = False
        self._global_status_context: Dict[str, str] = {}
        self._command_palette: Optional[CommandPaletteDialog] = None
        self._runtime_theme_apply_in_progress = False
        self._runtime_theme_reapply_requested = False
        self._runtime_theme_signature: Optional[Tuple[str, bool]] = None
        self._deferred_theme_refresh_needed = False
        self._floating_warning_dialogs: List[QMessageBox] = []
        self._graceful_exit_in_progress = False
        self._graceful_exit_finalizing = False
        self._graceful_exit_timer = QTimer(self)
        self._graceful_exit_timer.setInterval(10)
        self._graceful_exit_timer.timeout.connect(self._advance_graceful_exit)
        self._graceful_exit_step = 0.05

        from UI.studio_main_shell import create_main_shell, main_canvas_enabled
        central = StaticThemeSurface(application_canvas=True) if main_canvas_enabled() else QWidget()
        self._central_widget = central
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(10, 10, 10, 6)
        self.main_layout.setSpacing(10)

        self.create_header()
        self.create_main_content()
        # Isolated, reversible presentation experiment; original creation methods remain intact.
        self._experimental_shell = create_main_shell(self)
        from UI.profile_controls import install_profile_header
        install_profile_header(self)
        from UI.study_dashboard import DashboardController
        self._dashboard = DashboardController(self)
        self._refresh_text_interaction_support()
        get_theme_manager().theme_changed.connect(self._on_theme_changed)

        self.load_config()
        from UI.app_icon import install_theme_app_icon
        install_theme_app_icon()
        self.apply_runtime_theme(force=True)
        QTimer.singleShot(0, self._show_groq_startup_warning_if_needed)
        QTimer.singleShot(0, self._maybe_show_onboarding_dialog)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._ensure_sidebar_responsive_width()
        self._resize_history_item_widths()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        if self._deferred_theme_refresh_needed and not (self._graceful_exit_in_progress or self._graceful_exit_finalizing):
            self._deferred_theme_refresh_needed = False
            self.apply_runtime_theme(force=True)

    def eventFilter(self, watched, event):  # type: ignore[override]
        if not self.isEnabled() and event.type() in {QEvent.Type.KeyPress, QEvent.Type.ContextMenu}:
            return False
        if event.type() == QEvent.Type.ContextMenu and isinstance(watched, QWidget):
            if self._is_text_context_widget(watched):
                try:
                    global_pos = event.globalPos()  # type: ignore[attr-defined]
                except Exception:
                    global_pos = None
                if global_pos is None:
                    try:
                        global_pos = watched.mapToGlobal(event.pos())  # type: ignore[attr-defined]
                    except Exception:
                        global_pos = watched.mapToGlobal(watched.rect().center())
                if self._show_text_context_menu(watched, global_pos):
                    return True
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_search_panel_keypress(watched, event):
                return True
        if watched in set(self._search_panel_checkbox_widgets()):
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                watched.setProperty("keyboardFocus", False)
                self._apply_series_checkbox_focus_styles()
            elif etype == QEvent.Type.FocusIn:
                watched.setProperty("keyboardFocus", event.reason() in {
                    Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                    Qt.FocusReason.ShortcutFocusReason, Qt.FocusReason.OtherFocusReason,
                })
            if etype in {QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.EnabledChange}:
                self._apply_series_checkbox_focus_styles()
        if watched is self._user_docs_dialog:
            etype = event.type()
            if etype in {QEvent.Type.Hide, QEvent.Type.Close}:
                self._restore_settings_after_docs_if_needed()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent):  # type: ignore[override]
        if not self.isEnabled():
            event.ignore()
            return
        key = event.key()
        if key == Qt.Key.Key_K and bool(
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        ):
            self._open_command_palette()
            event.accept()
            return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            focus_widget = self.focusWidget()
            if focus_widget is getattr(self, "search_button", None):
                button = getattr(self, "search_button", None)
                if isinstance(button, QPushButton) and button.isEnabled():
                    button.click()
                    event.accept()
                    return
            if focus_widget is getattr(self, "year_entry", None):
                button = getattr(self, "search_button", None)
                if isinstance(button, QPushButton) and button.isEnabled():
                    button.setFocus(Qt.FocusReason.TabFocusReason)
                    button.click()
                    event.accept()
                    return
        super().keyPressEvent(event)

    def closeEvent(self, event):  # type: ignore[override]
        from Core.background_tasks import gui_work_pending
        if gui_work_pending():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        if self._graceful_exit_finalizing:
            if not self._finalize_graceful_exit_cleanup():
                event.ignore()
                QTimer.singleShot(75, self.close)
                return
            super().closeEvent(event)
            return

        event.ignore()
        self.graceful_exit()

    def graceful_exit(self) -> None:
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return

        self._graceful_exit_in_progress = True
        self._prepare_for_graceful_exit()

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

    def _prepare_for_graceful_exit(self) -> None:

        try:
            settings_window = self.__dict__.get("_settings_window")
            if settings_window:
                settings_window.hide()
        except Exception:
            pass

        try:
            if self._user_docs_dialog and self._is_qt_object_alive(self._user_docs_dialog):
                self._user_docs_dialog.hide()
        except Exception:
            pass


        try:
            self._close_loading_dialog()
        except Exception:
            pass

        try:
            search_thread = getattr(self, "search_thread", None)
            if search_thread and search_thread.isRunning():
                search_thread.request_cancel()
        except Exception:
            pass

    def _complete_graceful_exit(self) -> None:
        if self._graceful_exit_finalizing:
            return
        self._graceful_exit_in_progress = False
        self._graceful_exit_finalizing = True
        self.close()

    def _finalize_graceful_exit_cleanup(self) -> bool:
        self._graceful_exit_timer.stop()
        # Child windows own QThreads; let their close handlers finish first.
        if EXAM_MODE_AVAILABLE:
            from PySide6.QtWidgets import QApplication
            exam_window_class = getattr(sys.modules.get("Core.exam_mode"), "ExamModeWindow", None)
            for window in list(QApplication.topLevelWidgets()):
                if exam_window_class is not None and isinstance(window, exam_window_class) and not window.close():
                    return False
        threads = list(self._orphan_search_threads)
        current = getattr(self, "search_thread", None)
        if current is not None:
            threads.append(current)
        pending = False
        for thread in threads:
            if thread.isRunning():
                thread.request_cancel()
                pending = True
        if pending:
            self.update_status("Finishing active searches before exit...")
            return False
        self._close_loading_dialog()
        self._set_search_busy_state(False)
        self._release_search_thread()
        self._clear_quick_look_cache()
        dashboard = getattr(self, '_dashboard', None)
        if dashboard:
            dashboard.shutdown()
        return True

    # ------------------------------------------------------------------
    # UI Sections
    # ------------------------------------------------------------------

    def create_header(self):
        self.header_card = QFrame()
        self.header_card.setObjectName("card")
        header_layout = QHBoxLayout(self.header_card)
        header_layout.setContentsMargins(15, 10, 15, 10)

        title = QLabel(APP_NAME)
        title.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        header_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setFixedHeight(44)
        self.settings_btn.setMinimumWidth(112)
        self.settings_btn.setFont(QFont("Arial", 14, QFont.Weight.DemiBold))
        self.settings_btn.clicked.connect(self._show_settings_window)
        header_layout.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        if EXAM_MODE_AVAILABLE:
            self.launch_exam_btn = QPushButton("Launch Exam Mode")
            self.launch_exam_btn.setStyleSheet(self._action_button_style_for_theme(Colors.ACCENT_PURPLE))
            self.launch_exam_btn.setFixedHeight(40)
            self.launch_exam_btn.clicked.connect(self.launch_standalone_exam_mode)
            self.launch_exam_btn.hide()

        header_layout.addStretch(1)

        self.level_selector_card = QFrame(self.header_card)
        self.level_selector_card.setObjectName("examLevelSelectorCard")
        level_row = QHBoxLayout(self.level_selector_card)
        level_row.setContentsMargins(12, 6, 12, 6)
        level_row.setSpacing(10)

        self.level_label = QLabel("Exam Level:")
        self.level_label.setStyleSheet(f"color: {ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.18), min_ratio=4.5)};")
        self.level_label.setFont(QFont("Arial", 12, QFont.Weight.DemiBold))
        level_row.addWidget(self.level_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.level_group = QButtonGroup(self)
        self.igcse_level_btn = QRadioButton("IGCSE")
        self.igcse_level_btn.setChecked(True)
        self.alevel_level_btn = QRadioButton("AS/A Level")

        self.level_group.addButton(self.igcse_level_btn)
        self.level_group.addButton(self.alevel_level_btn)
        self.igcse_level_btn.toggled.connect(self.on_level_change)
        self.alevel_level_btn.toggled.connect(self.on_level_change)

        for level_btn in (self.igcse_level_btn, self.alevel_level_btn):
            level_btn.setMinimumHeight(30)
            level_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            level_row.addWidget(level_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        header_layout.addWidget(self.level_selector_card, 0, Qt.AlignmentFlag.AlignVCenter)

        self.main_layout.addWidget(self.header_card)

    def create_main_content(self):
        content_frame = QFrame()
        self.content_frame = content_frame
        content_layout = QHBoxLayout(content_frame)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout = content_layout

        # Control Center (Sidebar)
        self.search_panel = QFrame()
        self.search_panel.setObjectName("card")
        self.search_panel.setProperty("themeRole", "controlCenter")
        self.search_panel.setMinimumWidth(self._sidebar_expanded_width)
        self.search_panel.setMaximumWidth(self._sidebar_expanded_width)
        self.search_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        search_layout = QVBoxLayout(self.search_panel)
        search_layout.setContentsMargins(16, 24, 16, 24)
        search_layout.setSpacing(12)
        self.search_layout = search_layout

        self.control_center_header = QWidget(self.search_panel)
        top_row = QHBoxLayout(self.control_center_header)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        self.control_center_header_layout = top_row
        self.control_center_title = QLabel("Control Center")
        self.control_center_title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.control_center_title.setStyleSheet("letter-spacing: -0.4px;")
        top_row.addWidget(self.control_center_title, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.control_center_header_spacer = QWidget(self.control_center_header)
        self.control_center_header_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_row.addWidget(self.control_center_header_spacer, 1)
        self.sidebar_toggle_btn = QToolButton(self.control_center_header)
        self.sidebar_toggle_btn.setObjectName("controlCenterToggleButton")
        self.sidebar_toggle_btn.setText("◀")
        self.sidebar_toggle_btn.setToolTip("Collapse Control Center")
        self.sidebar_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_toggle_btn.setAutoRaise(False)
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar_collapsed)
        top_row.addWidget(self.sidebar_toggle_btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        search_layout.addWidget(self.control_center_header, 0)

        self.control_center_content = QWidget(self.search_panel)
        control_content_layout = QVBoxLayout(self.control_center_content)
        control_content_layout.setContentsMargins(0, 0, 0, 0)
        control_content_layout.setSpacing(14)
        self.control_center_content_layout = control_content_layout

        self._control_anchor_widgets: Dict[str, QWidget] = {}
        self._build_control_center_sections(control_content_layout)
        search_layout.addWidget(self.control_center_content, 1)

        # Results Panel
        self.results_panel = QFrame()
        self.results_panel.setObjectName("card")
        self.results_panel.setProperty("themeRole", "mainResults")
        results_layout = QVBoxLayout(self.results_panel)
        results_layout.setContentsMargins(15, 15, 15, 15)
        results_layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_label = QLabel("Search Results")
        header_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header_row.addWidget(header_label)

        self.results_count = QLabel("(0 found)")
        self.results_count.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
        header_row.addWidget(self.results_count)
        header_row.addStretch(1)

        self.results_view_list_btn = QToolButton(self.results_panel)
        self.results_view_list_btn.setObjectName("resultsViewModeButton")
        self.results_view_list_btn.setText("List")
        self.results_view_list_btn.setCheckable(True)
        self.results_view_list_btn.setAutoExclusive(True)
        self.results_view_list_btn.setChecked(True)
        self.results_view_list_btn.setToolTip("List View")
        self.results_view_list_btn.clicked.connect(lambda: self._set_results_view_mode("list"))
        header_row.addWidget(self.results_view_list_btn)

        self.results_view_grid_btn = QToolButton(self.results_panel)
        self.results_view_grid_btn.setObjectName("resultsViewModeButton")
        self.results_view_grid_btn.setText("Grid")
        self.results_view_grid_btn.setCheckable(True)
        self.results_view_grid_btn.setAutoExclusive(True)
        self.results_view_grid_btn.setToolTip("Grid View")
        self.results_view_grid_btn.clicked.connect(lambda: self._set_results_view_mode("grid"))
        header_row.addWidget(self.results_view_grid_btn)

        self.open_all_button = QPushButton("Open All")
        self.open_all_button.setEnabled(False)
        self.open_all_button.setMinimumWidth(110)
        self.open_all_button.clicked.connect(self.open_all_results)
        header_row.addWidget(self.open_all_button)

        self.download_all_button = QPushButton("Download All")
        self.download_all_button.setEnabled(False)
        self.download_all_button.setMinimumWidth(126)
        self.download_all_button.clicked.connect(self.download_all_results)
        header_row.addWidget(self.download_all_button)

        self._apply_header_action_button_styles()

        results_layout.addLayout(header_row)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_container = StaticThemeSurface(search_canvas=True)
        self.results_container_layout = QVBoxLayout(self.results_container)
        from PySide6.QtWidgets import QLayout
        # New result cards must grow the scroll content after a home-state swap.
        self.results_container_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.results_container_layout.setContentsMargins(2, 2, 10, 2)
        self.results_container_layout.setSpacing(8)
        self.results_scroll.setWidget(self.results_container)

        results_layout.addWidget(self.results_scroll)

        self.exam_launch_footer = QFrame(self.results_panel)
        footer_layout = QHBoxLayout(self.exam_launch_footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_label = QLabel("Practise with these papers", self.exam_launch_footer)
        footer_label.setWordWrap(True)
        footer_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer_layout.addWidget(footer_label, 1)
        if self.launch_exam_btn is not None:
            footer_layout.addWidget(self.launch_exam_btn)
            self.launch_exam_btn.show()
        results_layout.addWidget(self.exam_launch_footer)
        self.exam_launch_footer.hide()

        self.main_content_splitter = None
        content_layout.addWidget(self.search_panel, 0)
        self.sidebar_divider = QFrame(content_frame)
        self.sidebar_divider.setObjectName("controlCenterDivider")
        self.sidebar_divider.setFixedWidth(1)
        content_layout.addWidget(self.sidebar_divider, 0)
        content_layout.addWidget(self.results_panel, 1)
        self._style_control_center_divider()

        self.main_layout.addWidget(content_frame)

        self._set_results_view_mode(ConfigManager.get_dashboard_results_view(), persist=False, rerender=False)
        self._set_sidebar_panel_width(int(self._sidebar_expanded_width))
        self._apply_sidebar_collapsed_visuals(False)
        self._show_results_empty_state("Search for papers to get started")

    def _control_filter_text_color(self) -> str:
        shell = getattr(self, "_experimental_shell", None)
        panel_bg = shell.sidebar_background() if shell is not None else self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.2)
        return ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, panel_bg, min_ratio=4.5)

    def _apply_control_center_tab_style(self) -> None:
        tab_bg = self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.4)
        selected_bg = self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.3)
        tab_text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, tab_bg, min_ratio=4.5)
        selected_text = ThemeManager._ensure_text_contrast(Colors.TEXT_WHITE, selected_bg, min_ratio=4.5)
        hover_bg = self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.5)
        hover_text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, hover_bg, min_ratio=4.5)
        self.control_center_tabs.setStyleSheet(
            "QTabWidget#controlCenterTabs {"
            f"background-color: {self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.3)};"
            "border: none;"
            "border-radius: 12px;"
            "}"
            "QTabWidget::pane {"
            f"background-color: {self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.2)};"
            "border: none;"
            "border-radius: 8px;"
            "}"
            "QTabBar::tab {"
            f"background-color: {self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.4)};"
            f"color: {tab_text};"
            "border: none;"
            "border-radius: 8px;"
            "padding: 8px 16px;"
            "margin-right: 4px;"
            "min-width: 80px;"
            "font-size: 11px;"
            "font-weight: 600;"
            "}"
            "QTabBar::tab:selected {"
            f"background-color: {self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.3)};"
            f"color: {selected_text};"
            f"border: 1px solid {self._mix_colors(Colors.ACCENT_CYAN, Colors.TEXT_WHITE, 0.2)};"
            "}"
            "QTabBar::tab:hover:!selected {"
            f"background-color: {hover_bg};"
            f"color: {hover_text};"
            "}"
        )

    def _build_control_center_sections(self, parent_layout: QVBoxLayout) -> None:
        self.control_center_sections_splitter = None

        # Create tab widget for dual-tabbed layout
        self.control_center_tabs = QTabWidget()
        self.control_center_tabs.setObjectName("controlCenterTabs")
        self._apply_control_center_tab_style()
        parent_layout.addWidget(self.control_center_tabs, 1)

        # Tab 1: Search
        search_tab_widget = QWidget()
        search_tab_widget.setObjectName("searchTabWidget")
        search_layout = QVBoxLayout(search_tab_widget)
        search_layout.setContentsMargins(16, 16, 16, 16)
        search_layout.setSpacing(14)

        # Call existing create methods directly on search_layout
        # They will add their widgets (including container widgets) directly to search_layout
        self.create_subject_section(search_layout)
        self.create_series_section(search_layout)
        self.create_year_section(search_layout)
        self.create_component_section(search_layout)
        self.create_doctype_section(search_layout)

        # Create search button
        self.search_button = QPushButton("Search Papers")
        self.search_button.setFixedHeight(42)
        self.search_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.search_button.setToolTip("Search for past papers with current filters (Press Enter)")
        self.search_button.clicked.connect(self.on_search)
        self.search_button.installEventFilter(self)
        self.search_button.setProperty("isPrimarySearchButton", True)
        self.search_button.setShortcut(Qt.Key.Key_Return)
        self.search_button.setStyleSheet(
            "QPushButton {"
            f"background-color: {Colors.SUCCESS};"
            f"color: {self._mix_colors(Colors.BG_DARK, Colors.SUCCESS, 0.85)};"
            f"border: 1px solid {Colors.SUCCESS};"
            "border-radius: 8px;"
            "font-size: 12px;"
            "font-weight: 700;"
            "padding: 8px 12px;"
            "}"
            f"QPushButton:hover:!disabled {{ background-color: {self._mix_colors(Colors.SUCCESS, Colors.TEXT_WHITE, 0.15)}; }}"
            f"QPushButton:disabled {{ background-color: {self._mix_colors(Colors.BG_DARK, Colors.SUCCESS, 0.3)}; color: {Colors.TEXT_GRAY}; border: 1px solid {self._mix_colors(Colors.BG_DARK, Colors.SUCCESS, 0.3)}; }}"
        )
        search_layout.addWidget(self.search_button)

        # Single stretch at the bottom to push all content to the top
        search_layout.addStretch(1)
        self.control_center_tabs.addTab(search_tab_widget, "Search")

        # Tab 2: History
        history_tab_widget = QWidget()
        history_tab_widget.setObjectName("historyTabWidget")
        history_layout = QVBoxLayout(history_tab_widget)
        history_layout.setContentsMargins(16, 16, 16, 16)
        history_layout.setSpacing(14)

        # Create history section
        self.create_history_section(history_layout)

        # Ensure history list expands to fill available space
        if isinstance(self.history_list, QListWidget):
            self.history_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # No stretch at bottom - history should fill entire available space
        self.control_center_tabs.addTab(history_tab_widget, "History")

        # Update control anchor widgets
        self._control_anchor_widgets["subject"] = self.subject_entry
        self._control_anchor_widgets["series"] = self.series_vars.get("MJ", self.subject_entry)
        self._control_anchor_widgets["year"] = self.year_entry
        self._control_anchor_widgets["component"] = self.component_entry
        self._control_anchor_widgets["docs"] = self.paper_var
        self._control_anchor_widgets["search"] = self.search_button
        self._control_anchor_widgets["history"] = self.history_list

        self._apply_control_filter_styles()

    def _focus_control_anchor(self, key: str) -> None:
        anchor = self._control_anchor_widgets.get(str(key))
        if isinstance(anchor, QWidget) and anchor.isEnabled():
            anchor.setFocus(Qt.FocusReason.TabFocusReason)
            if isinstance(anchor, QLineEdit):
                anchor.selectAll()

    def _ensure_sidebar_responsive_width(self) -> None:
        shell = getattr(self, "_experimental_shell", None)
        if shell is not None:
            shell.resize()
            return
        if self._sidebar_is_animating:
            return
        target = self._sidebar_collapsed_width if self._sidebar_is_collapsed else self._sidebar_expanded_width
        self._set_sidebar_panel_width(int(target), allow_collapsed=self._sidebar_is_collapsed)

    def _set_sidebar_panel_width(self, width: int, *, allow_collapsed: bool = False) -> None:
        panel = getattr(self, "search_panel", None)
        if not isinstance(panel, QWidget):
            return
        minimum = self._sidebar_collapsed_width if allow_collapsed else 280
        clamped = max(int(minimum), int(width))
        panel.setMinimumWidth(clamped)
        panel.setMaximumWidth(clamped)
        panel.setVisible(True)
        panel.updateGeometry()
        self._sidebar_current_width = clamped

    def _style_control_center_divider(self) -> None:
        divider_widget = getattr(self, "sidebar_divider", None)
        if not isinstance(divider_widget, QFrame):
            return
        divider_color = self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.50)
        divider_widget.setStyleSheet(f"background-color: {divider_color}; border: none;")

    def _apply_sidebar_collapsed_visuals(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if isinstance(getattr(self, "search_layout", None), QVBoxLayout):
            if collapsed:
                self.search_layout.setContentsMargins(10, 10, 10, 10)
                self.search_layout.setSpacing(8)
            else:
                self.search_layout.setContentsMargins(16, 24, 16, 24)
                self.search_layout.setSpacing(12)

        title = getattr(self, "control_center_title", None)
        spacer = getattr(self, "control_center_header_spacer", None)
        content = getattr(self, "control_center_content", None)
        toggle = getattr(self, "sidebar_toggle_btn", None)
        header_layout = getattr(self, "control_center_header_layout", None)
        if isinstance(title, QWidget):
            title.setVisible(not collapsed)
        if isinstance(spacer, QWidget):
            spacer.setVisible(not collapsed)
        if isinstance(content, QWidget):
            content.setVisible(not collapsed)
        if isinstance(toggle, QToolButton):
            toggle.setText("▶" if collapsed else "◀")
            toggle.setToolTip("Expand Control Center" if collapsed else "Collapse Control Center")
        if isinstance(header_layout, QHBoxLayout) and isinstance(toggle, QWidget):
            if collapsed:
                header_layout.setSpacing(0)
            else:
                header_layout.setSpacing(6)
            alignment = Qt.AlignmentFlag.AlignCenter if collapsed else (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header_layout.setAlignment(toggle, alignment)

        shell = getattr(self, "_experimental_shell", None)
        if shell is not None:
            shell.collapsed(collapsed)

    def _control_filter_line_edit_stylesheet(self) -> str:
        input_bg = self._mix_colors(Colors.BG_DARK, Colors.BG_CARD, 0.35)
        input_border = self._mix_colors(Colors.TEXT_GRAY, Colors.BG_DARK, 0.35)
        input_border_hover = self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.28)
        input_border_focus = self._mix_colors(Colors.PRIMARY, Colors.TEXT_WHITE, 0.12)
        input_text = self._contrast_text_for_bg(Colors.BG_DARK)
        input_placeholder = self._mix_colors(input_text, Colors.TEXT_GRAY, 0.62)
        input_selection_bg = self._mix_colors(Colors.PRIMARY, Colors.ACCENT_CYAN, 0.24)
        input_selection_text = self._contrast_text_for_bg(input_selection_bg)
        disabled_bg = self._mix_colors(Colors.BG_DARK, Colors.BG_CARD, 0.5)
        disabled_text = self._mix_colors(input_text, Colors.TEXT_GRAY, 0.58)
        return (
            "QLineEdit {"
            f"background-color: {input_bg};"
            f"color: {input_text};"
            f"border: 1px solid {input_border};"
            "border-radius: 6px;"
            "padding: 5px 8px;"
            f"selection-background-color: {input_selection_bg};"
            f"selection-color: {input_selection_text};"
            "}"
            "QLineEdit:hover {"
            f"border: 1px solid {input_border_hover};"
            "}"
            "QLineEdit:focus {"
            f"border: 1px solid {input_border_focus};"
            "padding: 5px 8px;"
            f"selection-background-color: {self._mix_colors(Colors.PRIMARY, Colors.ACCENT_CYAN, 0.25)};"
            "}"
            "QLineEdit::placeholder {"
            f"color: {input_placeholder};"
            "}"
            "QLineEdit:disabled {"
            f"background-color: {disabled_bg};"
            f"color: {disabled_text};"
            f"border: 1px solid {self._mix_colors(input_border, Colors.BG_DARK, 0.44)};"
            "}"
        )

    def _subject_completer_popup_stylesheet(self) -> str:
        popup_bg = self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.18)
        popup_text = self._contrast_text_for_bg(popup_bg)
        popup_border = self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.34)
        hover_bg = self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.30)
        selected_bg = self._mix_colors(Colors.PRIMARY, Colors.ACCENT_CYAN, 0.26)
        selected_text = self._contrast_text_for_bg(selected_bg)
        scrollbar_track = self._mix_colors(Colors.BG_DARK, Colors.BG_MEDIUM, 0.44)
        scrollbar_handle = self._mix_colors(Colors.PRIMARY, Colors.ACCENT_CYAN, 0.36)
        scrollbar_hover = self._mix_colors(scrollbar_handle, Colors.TEXT_WHITE, 0.18)
        return (
            "QAbstractItemView {"
            f"background-color: {popup_bg};"
            f"color: {popup_text};"
            f"border: 1px solid {popup_border};"
            "border-radius: 9px;"
            "outline: none;"
            "padding: 2px;"
            "}"
            "QAbstractItemView::item {"
            "min-height: 26px;"
            "padding: 5px 8px;"
            "border-radius: 6px;"
            "}"
            "QAbstractItemView::item:hover {"
            f"background-color: {hover_bg};"
            "}"
            "QAbstractItemView::item:selected {"
            f"background-color: {selected_bg};"
            f"color: {selected_text};"
            "}"
            "QScrollBar:vertical {"
            "background: transparent;"
            "width: 10px;"
            "margin: 2px 2px 2px 0px;"
            "}"
            "QScrollBar::handle:vertical {"
            f"background: {scrollbar_handle};"
            "min-height: 22px;"
            "border-radius: 5px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            f"background: {scrollbar_hover};"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "height: 0px;"
            "background: transparent;"
            "}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            f"background: {scrollbar_track};"
            "border-radius: 5px;"
            "}"
        )

    def _apply_control_filter_styles(self) -> None:
        from UI.localization import source_text
        self._apply_series_checkbox_focus_styles()
        entry_style = self._control_filter_line_edit_stylesheet()
        for entry_name in ("subject_entry", "component_entry", "year_entry"):
            entry = getattr(self, entry_name, None)
            if isinstance(entry, QLineEdit):
                entry.setStyleSheet(entry_style)
                entry.setMinimumHeight(28)

        for label in self.search_panel.findChildren(QLabel):
            if str(source_text(label) or "").strip().upper() in {"SUBJECT", "SERIES", "YEARS", "COMPONENTS"}:
                label.setStyleSheet(
                    f"color: {self._control_filter_text_color()};"
                    "font-size: 10px;"
                    "font-weight: 600;"
                    "letter-spacing: 1px;"
                    "text-transform: uppercase;"
                )

        for label in self.search_panel.findChildren(QLabel):
            if source_text(label) in {"Paper Components", "Document Options"}:
                label.setStyleSheet(f"color: {self._control_filter_text_color()};")
        note = getattr(self, "variant_lock_note", None)
        if isinstance(note, QLabel):
            note.setStyleSheet(f"color: {self._control_filter_text_color()}; font-style: italic;")

        completer = getattr(self, "subject_completer", None)
        if not isinstance(completer, QCompleter):
            return
        popup = completer.popup()
        if isinstance(popup, QAbstractItemView):
            popup.setStyleSheet(self._subject_completer_popup_stylesheet())
            popup.setFrameShape(QFrame.Shape.NoFrame)
            popup.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            popup.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def _get_sidebar_animated_width(self) -> int:
        panel = getattr(self, "search_panel", None)
        if isinstance(panel, QWidget):
            try:
                return int(panel.width())
            except Exception:
                pass
        return int(self._sidebar_current_width)

    def _set_sidebar_animated_width(self, width: int) -> None:
        self._set_sidebar_panel_width(int(width), allow_collapsed=True)

    sidebarAnimatedWidth = Property(int, _get_sidebar_animated_width, _set_sidebar_animated_width)

    def _on_sidebar_animation_finished(self) -> None:
        self._sidebar_is_animating = False
        self._set_sidebar_panel_width(int(self._sidebar_animation_target_width), allow_collapsed=self._sidebar_is_collapsed)
        toggle = getattr(self, "sidebar_toggle_btn", None)
        if isinstance(toggle, QToolButton):
            toggle.setEnabled(True)

    def _set_sidebar_collapsed(self, collapsed: bool, *, persist: bool = True, animate: bool = True) -> None:
        collapsed = bool(collapsed)
        if persist and hasattr(ConfigManager, "set_dashboard_sidebar_collapsed"):
            ConfigManager.set_dashboard_sidebar_collapsed(collapsed)

        target_width = self._sidebar_collapsed_width if collapsed else self._sidebar_expanded_width
        self._sidebar_is_collapsed = collapsed
        self._sidebar_animation_target_width = int(target_width)
        self._apply_sidebar_collapsed_visuals(collapsed)

        toggle = getattr(self, "sidebar_toggle_btn", None)
        if isinstance(toggle, QToolButton):
            toggle.setEnabled(not animate)

        if not animate:
            self._sidebar_is_animating = False
            self._set_sidebar_panel_width(int(target_width), allow_collapsed=collapsed)
            if isinstance(toggle, QToolButton):
                toggle.setEnabled(True)
            return

        if self._sidebar_animation is None:
            self._sidebar_animation = QPropertyAnimation(self, b"sidebarAnimatedWidth")
            self._sidebar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._sidebar_animation.setDuration(220)
            self._sidebar_animation.finished.connect(self._on_sidebar_animation_finished)

        self._sidebar_is_animating = True
        self._sidebar_animation.stop()
        self._sidebar_animation.setStartValue(self._get_sidebar_animated_width())
        self._sidebar_animation.setEndValue(int(target_width))
        self._sidebar_animation.start()

    def _toggle_sidebar_collapsed(self) -> None:
        if self._sidebar_is_animating:
            return
        self._set_sidebar_collapsed(not self._sidebar_is_collapsed, persist=True, animate=True)


    # ------------------------------------------------------------------
    # Input Sections
    # ------------------------------------------------------------------

    def _series_checkbox_focus_stylesheet(self) -> str:
        ring_color = self._mix_colors(Colors.PRIMARY, "#FFFFFF", 0.18)
        ring_bg = self._mix_colors(Colors.BG_CARD, Colors.PRIMARY, 0.07)
        checked_bg = self._mix_colors(Colors.PRIMARY, Colors.BG_DARK, 0.25)
        checked_text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, checked_bg, min_ratio=4.5)
        disabled_bg = self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.5)
        disabled_text = ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, disabled_bg, min_ratio=3.0)
        return (
            "QCheckBox[controlChip='true'] {"
            f"color: {Colors.TEXT_LIGHT};"
            f"background-color: {self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.3)};"
            f"border: 1px solid {self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.44)};"
            "border-radius: 8px;"
            "padding: 4px 10px;"
            "font-size: 11px;"
            "font-weight: 600;"
            "}"
            "QCheckBox[controlChip='true']::indicator { width: 0px; height: 0px; }"
            "QCheckBox[controlChip='true']:checked {"
            f"color: {checked_text};"
            f"background-color: {checked_bg};"
            f"border: 1px solid {ring_color};"
            "}"
            "QCheckBox[controlChip='true'][keyboardFocus='true']:focus {"
            f"border: 2px solid {ring_color};"
            "padding: 3px 9px;"
            "}"
            "QCheckBox[controlChip='false'] {"
            f"color: {self._control_filter_text_color()};"
            "padding: 2px 6px;"
            "border: 1px solid transparent;"
            "border-radius: 6px;"
            "}"
            "QCheckBox[controlChip='false'][keyboardFocus='true']:focus {"
            f"border: 2px solid {ring_color};"
            f"background-color: {ring_bg};"
            f"color: {ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, ring_bg, min_ratio=4.5)};"
            "padding: 1px 5px;"
            "}"
            "QCheckBox:disabled {"
            f"background-color: {disabled_bg};"
            f"color: {disabled_text};"
            f"border: 1px solid {Colors.BG_LIGHT};"
            "padding: 2px 6px;"
            "}"
        )

    def _apply_series_checkbox_focus_styles(self) -> None:
        checkboxes = self._search_panel_checkbox_widgets()
        if not checkboxes:
            return
        style = self._series_checkbox_focus_stylesheet()
        for cb in checkboxes:
            # Qt QSS does not support CSS :not(); give ordinary options an explicit role.
            if cb.property("controlChip") is None:
                cb.setProperty("controlChip", False)
            cb.setStyleSheet(style)

    def _search_panel_checkbox_widgets(self) -> List[QCheckBox]:
        widgets: List[QCheckBox] = []
        series_vars = getattr(self, "series_vars", {})
        if isinstance(series_vars, dict):
            for cb in series_vars.values():
                if isinstance(cb, QCheckBox):
                    widgets.append(cb)
        for attr in ("paper_var", "ms_var", "gt_var"):
            cb = getattr(self, attr, None)
            if isinstance(cb, QCheckBox):
                widgets.append(cb)
        return widgets

    @staticmethod
    def _is_text_context_widget(widget: object) -> bool:
        return isinstance(widget, (QLabel, QLineEdit, QTextBrowser, QTextEdit, QPlainTextEdit))

    def _prepare_text_context_widget(self, widget: QWidget) -> None:
        if not self._is_text_context_widget(widget):
            return
        widget_id = id(widget)
        if widget_id in self._text_context_registered_widget_ids:
            return
        self._text_context_registered_widget_ids.add(widget_id)
        try:
            widget.installEventFilter(self)
        except Exception:
            pass
        if isinstance(widget, QLabel):
            try:
                if str(widget.text() or "").strip():
                    flags = widget.textInteractionFlags()
                    flags |= Qt.TextInteractionFlag.TextSelectableByMouse
                    flags |= Qt.TextInteractionFlag.TextSelectableByKeyboard
                    widget.setTextInteractionFlags(flags)
            except Exception:
                pass

    def _refresh_text_interaction_support(self) -> None:
        for widget in self.findChildren(QWidget):
            if self._is_text_context_widget(widget):
                self._prepare_text_context_widget(widget)

    @staticmethod
    def _text_selection(widget: QWidget) -> str:
        try:
            if isinstance(widget, QLineEdit):
                return str(widget.selectedText() or "")
            if isinstance(widget, (QTextEdit, QPlainTextEdit, QTextBrowser)):
                return str(widget.textCursor().selectedText() or "")
            if isinstance(widget, QLabel):
                if widget.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse:
                    return str(widget.selectedText() or "")
        except Exception:
            return ""
        return ""

    @staticmethod
    def _text_content(widget: QWidget) -> str:
        try:
            if isinstance(widget, QLineEdit):
                return str(widget.text() or "")
            if isinstance(widget, QTextBrowser):
                return str(widget.toPlainText() or "")
            if isinstance(widget, QTextEdit):
                return str(widget.toPlainText() or "")
            if isinstance(widget, QPlainTextEdit):
                return str(widget.toPlainText() or "")
            if isinstance(widget, QLabel):
                return str(widget.text() or "")
        except Exception:
            return ""
        return ""

    @staticmethod
    def _widget_is_editable(widget: QWidget) -> bool:
        if isinstance(widget, QLineEdit):
            return not widget.isReadOnly()
        if isinstance(widget, QTextEdit):
            return not widget.isReadOnly()
        if isinstance(widget, QPlainTextEdit):
            return not widget.isReadOnly()
        return False

    def _show_text_context_menu(self, widget: QWidget, global_pos) -> bool:
        if not self._is_text_context_widget(widget):
            return False

        selected_text = self._text_selection(widget)
        all_text = self._text_content(widget)
        editable = self._widget_is_editable(widget)
        clipboard_text = str(QApplication.clipboard().text() or "")

        menu = QMenu(self)
        cut_action = menu.addAction("Cut")
        copy_action = menu.addAction("Copy")
        paste_action = menu.addAction("Paste")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        select_all_action = menu.addAction("Select All")
        clear_action = menu.addAction("Clear")

        has_selection = bool(selected_text)
        has_text = bool(all_text)
        has_clipboard = bool(clipboard_text)

        cut_action.setEnabled(editable and has_selection)
        copy_action.setEnabled(has_selection or has_text)
        paste_action.setEnabled(editable and has_clipboard)
        delete_action.setEnabled(editable and has_selection)
        select_all_action.setEnabled(has_text)
        clear_action.setEnabled(editable and has_text)

        chosen = menu.exec(global_pos)
        if chosen is None:
            return True

        if chosen is copy_action:
            QApplication.clipboard().setText(selected_text or all_text)
            return True
        if chosen is cut_action and editable:
            if isinstance(widget, QLineEdit):
                widget.cut()
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                widget.cut()
            return True
        if chosen is paste_action and editable:
            if isinstance(widget, QLineEdit):
                widget.paste()
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                widget.paste()
            return True
        if chosen is delete_action and editable and has_selection:
            if isinstance(widget, QLineEdit):
                widget.insert("")
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                cursor = widget.textCursor()
                cursor.removeSelectedText()
                widget.setTextCursor(cursor)
            return True
        if chosen is select_all_action:
            if isinstance(widget, QLineEdit):
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
                widget.selectAll()
            elif isinstance(widget, (QTextEdit, QPlainTextEdit, QTextBrowser)):
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
                widget.selectAll()
            elif isinstance(widget, QLabel):
                widget.setTextInteractionFlags(
                    widget.textInteractionFlags()
                    | Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
            return True
        if chosen is clear_action and editable:
            if isinstance(widget, QLineEdit):
                widget.clear()
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                widget.clear()
            return True
        return True

    def _search_panel_ordered_widgets(self) -> List[List[QWidget]]:
        shell = getattr(self, "_experimental_shell", None)
        if shell is not None and hasattr(shell, "keyboard_rows"):
            return shell.keyboard_rows()
        ordered: List[List[QWidget]] = []
        subject = getattr(self, "subject_entry", None)
        if isinstance(subject, QLineEdit):
            ordered.append([subject])

        series_vars = getattr(self, "series_vars", {})
        series_boxes: List[QWidget] = []
        if isinstance(series_vars, dict):
            ordered_keys = [key for key in ("MJ", "ON", "FM") if key in series_vars]
            ordered_keys.extend([key for key in series_vars.keys() if key not in ordered_keys])
            for key in ordered_keys:
                cb = series_vars.get(key)
                if isinstance(cb, QCheckBox):
                    series_boxes.append(cb)
        if series_boxes:
            ordered.append(series_boxes)

        component = getattr(self, "component_entry", None)
        if isinstance(component, QLineEdit):
            ordered.append([component])

        year = getattr(self, "year_entry", None)
        if isinstance(year, QLineEdit):
            ordered.append([year])

        doc_type_widgets: List[QWidget] = []
        for attr_name in ("paper_var", "ms_var", "gt_var"):
            widget = getattr(self, attr_name, None)
            if isinstance(widget, QCheckBox):
                doc_type_widgets.append(widget)
        if doc_type_widgets:
            ordered.append(doc_type_widgets)

        search_button = getattr(self, "search_button", None)
        if isinstance(search_button, QPushButton):
            ordered.append([search_button])

        return ordered

    def _search_panel_widget_position(self, watched: object) -> Optional[Tuple[int, int]]:
        if not isinstance(watched, QWidget):
            return None
        for row_idx, row in enumerate(self._search_panel_ordered_widgets()):
            for col_idx, widget in enumerate(row):
                if watched is widget:
                    return row_idx, col_idx
        return None

    def _focus_search_panel_row(self, row_idx: int, preferred_col: Optional[int] = None) -> bool:
        rows = self._search_panel_ordered_widgets()
        if row_idx < 0 or row_idx >= len(rows):
            return False
        row = rows[row_idx]
        if not row:
            return False
        if preferred_col is None or preferred_col < 0 or preferred_col >= len(row):
            preferred_col = 0
        candidates = row[preferred_col:] + row[:preferred_col]
        for widget in candidates:
            if not isinstance(widget, QWidget):
                continue
            if not widget.isEnabled():
                continue
            widget.setFocus(Qt.FocusReason.TabFocusReason)
            if isinstance(widget, QLineEdit):
                widget.selectAll()
            return True
        return False

    def _focus_search_panel_vertical(self, watched: object, direction: int) -> bool:
        if direction == 0:
            return False
        position = self._search_panel_widget_position(watched)
        if position is None:
            return False
        row_idx, _col_idx = position
        target_row = row_idx + (1 if direction > 0 else -1)
        rows = self._search_panel_ordered_widgets()
        if target_row < 0 or target_row >= len(rows):
            return False
        preferred_col = 0
        target_widgets = rows[target_row]
        if target_widgets and isinstance(target_widgets[0], QCheckBox):
            for idx, widget in enumerate(target_widgets):
                if isinstance(widget, QCheckBox) and widget.isChecked():
                    preferred_col = idx
                    break
        return self._focus_search_panel_row(target_row, preferred_col=preferred_col)

    def _focus_series_checkbox_horizontal(self, watched: object, direction: int) -> bool:
        if direction == 0:
            return False
        rows = self._search_panel_ordered_widgets()
        for row in rows:
            if not row or not isinstance(row[0], QCheckBox):
                continue
            if watched not in row:
                continue
            current_idx = row.index(watched)
            next_idx = max(0, min(len(row) - 1, current_idx + (1 if direction > 0 else -1)))
            target = row[next_idx]
            if isinstance(target, QCheckBox):
                target.setFocus(Qt.FocusReason.TabFocusReason)
                return True
            return False
        return False

    def _handle_search_panel_keypress(self, watched: object, event: QKeyEvent) -> bool:
        shell = getattr(self, "_experimental_shell", None)
        if shell is not None and hasattr(shell, "handle_subject_keypress"):
            if shell.handle_subject_keypress(watched, event):
                return True
        if not isinstance(watched, QWidget):
            return False
        if self._search_panel_widget_position(watched) is None:
            return False
        if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return False

        key = event.key()
        if key == Qt.Key.Key_Up:
            return self._focus_search_panel_vertical(watched, direction=-1)
        if key == Qt.Key.Key_Down:
            return self._focus_search_panel_vertical(watched, direction=1)
        if key == Qt.Key.Key_Left:
            if isinstance(watched, QCheckBox):
                return self._focus_series_checkbox_horizontal(watched, direction=-1)
            return False
        if key == Qt.Key.Key_Right:
            if isinstance(watched, QCheckBox):
                return self._focus_series_checkbox_horizontal(watched, direction=1)
            return False
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if isinstance(watched, QCheckBox):
                watched.toggle()
                return True
            if watched is getattr(self, "year_entry", None):
                button = getattr(self, "search_button", None)
                if isinstance(button, QPushButton) and button.isEnabled():
                    button.setFocus(Qt.FocusReason.TabFocusReason)
                    button.click()
                    return True
            if isinstance(watched, QPushButton):
                watched.click()
                return True
        return False

    def create_subject_section(self, layout: QVBoxLayout):
        label = QLabel("Subject")
        label.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
        layout.addWidget(label)

        self.subject_entry = QLineEdit()
        self.subject_entry.setPlaceholderText("Type subject name or code...")
        self.subject_entry.setMinimumHeight(32)
        self.subject_entry.setToolTip("Enter subject name (e.g., Physics) or code (e.g., 0625)")
        self.subject_entry.editingFinished.connect(self.on_subject_validate)
        self.subject_entry.installEventFilter(self)
        layout.addWidget(self.subject_entry)
        self.subject_suggestion_model = QStringListModel(self)
        self.subject_completer = QCompleter(self.subject_suggestion_model, self.subject_entry)
        self.subject_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.subject_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.subject_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.subject_completer.activated[str].connect(self._on_subject_completion_activated)
        self.subject_entry.setCompleter(self.subject_completer)
        self._sync_live_subject_search_mode()

    def _clear_subject_selection(self) -> None:
        self.subject_code = ""
        self.subject_name = ""
        if isinstance(getattr(self, "subject_entry", None), QLineEdit):
            self.subject_entry.clear()
        if isinstance(getattr(self, "subject_suggestion_model", None), QStringListModel):
            self.subject_suggestion_model.setStringList([])
        self._hide_subject_completer_popup()
        self.update_series_availability("")
        self._sync_subject_browser(clear_filter=True)

    def _sync_subject_browser(self, *, clear_filter: bool = False) -> None:
        shell = getattr(self, "_experimental_shell", None)
        if shell is not None and hasattr(shell, "sync_subject_browser"):
            shell.sync_subject_browser(clear_filter=clear_filter)

    def _apply_subject_selection(self, code: str, name: str, *, clear_entry: bool = True) -> None:
        normalized_code = str(code or "").strip()
        normalized_name = str(name or "").strip()
        if not normalized_code:
            return
        self.subject_code = normalized_code
        self.subject_name = normalized_name
        if isinstance(getattr(self, "subject_entry", None), QLineEdit):
            selected_label = f"{self.subject_code} - {self.subject_name}"
            blocked = self.subject_entry.blockSignals(True)
            self.subject_entry.setText(selected_label)
            self.subject_entry.setCursorPosition(len(selected_label))
            self.subject_entry.blockSignals(blocked)
        if isinstance(getattr(self, "subject_suggestion_model", None), QStringListModel):
            self.subject_suggestion_model.setStringList([])
        self._hide_subject_completer_popup()
        self.update_series_availability(self.subject_code)
        self._sync_subject_browser()

    def create_series_section(self, layout):
        self.series_section_widget = QWidget()
        section_layout = QVBoxLayout(self.series_section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)
        label = QLabel("Series")
        label.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
        section_layout.addWidget(label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.series_vars = {
            "MJ": SearchOptionCheckBox("MJ"),
            "ON": SearchOptionCheckBox("ON"),
            "FM": SearchOptionCheckBox("FM"),
        }
        self.series_vars["MJ"].setToolTip("May/June examination session")
        self.series_vars["ON"].setToolTip("October/November examination session")
        self.series_vars["FM"].setToolTip("February/March examination session")
        self.series_vars["MJ"].setChecked(True)
        for cb in self.series_vars.values():
            cb.setObjectName("seriesToggleChip")
            cb.setProperty("controlChip", True)
            cb.setMinimumHeight(28)
            cb.setMaximumHeight(28)
            cb.setMinimumWidth(60)
            cb.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            row.addWidget(cb)
            cb.toggled.connect(self._on_series_selection_changed)
            cb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            cb.installEventFilter(self)
            cb.setStyleSheet(
                "QCheckBox#seriesToggleChip {"
                f"color: {Colors.TEXT_LIGHT};"
                f"background-color: {self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.3)};"
                f"border: 1px solid {self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.44)};"
                "border-radius: 8px;"
                "padding: 4px 10px;"
                "font-size: 11px;"
                "font-weight: 600;"
                "}"
                "QCheckBox#seriesToggleChip::indicator { width: 0px; height: 0px; }"
                "QCheckBox#seriesToggleChip:checked {"
                f"background-color: {self._mix_colors(Colors.SUCCESS, Colors.BG_DARK, 0.25)};"
                f"border: 1px solid {self._mix_colors(Colors.SUCCESS, Colors.TEXT_WHITE, 0.12)};"
                "}"
            )
        row.addStretch(1)
        self._apply_series_checkbox_focus_styles()
        section_layout.addLayout(row)
        if isinstance(layout, QLayout):
            layout.addWidget(self.series_section_widget, 1)

    def create_component_section(self, layout: QVBoxLayout):
        self.component_section_widget = QWidget()
        section_layout = QVBoxLayout(self.component_section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)

        label = QLabel("Paper Components")
        label.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
        section_layout.addWidget(label)

        self.component_entry = QLineEdit()
        self.component_entry.setPlaceholderText("e.g., 11-13 or 41,42 (paper variants)")
        self.component_entry.setMinimumHeight(32)
        self.component_entry.setToolTip("Enter paper component numbers or variants (e.g., 11-13 for components 11, 12, 13)")
        self.component_entry.installEventFilter(self)
        section_layout.addWidget(self.component_entry)

        self.variant_lock_note = QLabel(
            "Feb/March papers are typically produced in a single variant, so the variant is locked"
        )
        self.variant_lock_note.setStyleSheet(f"color: {Colors.TEXT_GRAY}; font-style: italic;")
        self.variant_lock_note.setWordWrap(True)
        self.variant_lock_note.setVisible(False)
        section_layout.addWidget(self.variant_lock_note)
        layout.addWidget(self.component_section_widget)

    def create_year_section(self, layout):
        self.year_section_widget = QWidget()
        section_layout = QVBoxLayout(self.year_section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)

        label = QLabel("Years")
        label.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
        section_layout.addWidget(label)

        self.year_entry = QLineEdit()
        self.year_entry.setPlaceholderText("e.g., 2024 or 20-24 or 20,22,24")
        self.year_entry.setMinimumHeight(32)
        self.year_entry.setMaximumHeight(32)
        self.year_entry.setToolTip("Enter single year (2024), range (20-24), or multiple years (20,22,24)")
        self.year_entry.installEventFilter(self)
        section_layout.addWidget(self.year_entry)
        if isinstance(layout, QLayout):
            layout.addWidget(self.year_section_widget, 1)

    def create_doctype_section(self, layout: QVBoxLayout):
        self.doctype_section_widget = QWidget()
        section_layout = QVBoxLayout(self.doctype_section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(8)

        label = QLabel("Document Options")
        label.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
        section_layout.addWidget(label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.paper_var = SearchOptionCheckBox("QP")
        self.ms_var = SearchOptionCheckBox("MS")
        self.gt_var = SearchOptionCheckBox("GT")
        self.paper_var.setToolTip("Question Paper")
        self.ms_var.setToolTip("Mark Scheme")
        self.gt_var.setToolTip("Grade Thresholds")
        self.paper_var.setChecked(True)
        self.ms_var.setChecked(True)
        self.gt_var.setChecked(False)

        for cb in (self.paper_var, self.ms_var, self.gt_var):
            cb.setMinimumHeight(28)
            cb.setMinimumWidth(56)
            cb.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            cb.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            cb.installEventFilter(self)
            cb.setStyleSheet(
                "QCheckBox {"
                f"color: {Colors.TEXT_LIGHT};"
                f"border: 1px solid {self._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.45)};"
                "border-radius: 10px;"
                "padding: 2px 10px;"
                "}"
                "QCheckBox:checked {"
                f"background-color: {self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.2)};"
                f"border: 1px solid {self._mix_colors(Colors.ACCENT_CYAN, Colors.TEXT_WHITE, 0.2)};"
                "}"
            )
            row.addWidget(cb)
        row.addStretch(1)
        self._apply_series_checkbox_focus_styles()
        section_layout.addLayout(row)
        layout.addWidget(self.doctype_section_widget)

    def create_history_section(self, layout: QVBoxLayout):
        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.on_history_clicked)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._on_history_context_menu)
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setContentsMargins(0, 0, 0, 0)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_list.setSpacing(12)
        self.history_list.setViewportMargins(6, 6, 10, 8)
        self.history_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.history_list.setUniformItemSizes(False)
        self.history_list.verticalScrollBar().setSingleStep(12)
        self.history_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.history_list.setToolTip("Click to re-run search, right-click for options")
        layout.addWidget(self.history_list)

        self.history_scroll_hint = QLabel("Scroll for more history")
        self.history_scroll_hint.setStyleSheet(f"color: {Colors.TEXT_GRAY}; font-size: 11px;")
        self.history_scroll_hint.setVisible(False)
        layout.addWidget(self.history_scroll_hint)

        self._apply_history_list_scrollbar_style()
        self.refresh_history()

    def _apply_history_list_scrollbar_style(self) -> None:
        if not isinstance(getattr(self, "history_list", None), QListWidget):
            return
        track = self._mix_colors(Colors.BG_DARK, Colors.BG_MEDIUM, 0.34)
        handle = self._mix_colors(Colors.BG_LIGHT, Colors.TEXT_GRAY, 0.38)
        hover = self._mix_colors(handle, Colors.TEXT_WHITE, 0.22)
        self.history_list.setStyleSheet(
            "QListWidget { padding-right: 2px; border: none; outline: none; }"
            "QListWidget::item { border: none; padding: 2px; border-radius: 6px; }"
            "QListWidget::item:selected { background: transparent; }"
            "QListWidget::item:hover { background: transparent; }"
            "QScrollBar:vertical {"
            "width: 8px;"
            "margin: 2px 2px 2px 0px;"
            "background: transparent;"
            "}"
            "QScrollBar::handle:vertical {"
            f"background: {handle};"
            "min-height: 20px;"
            "border-radius: 4px;"
            "}"
            "QScrollBar::handle:vertical:hover {"
            f"background: {hover};"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "height: 0px;"
            "background: transparent;"
            "}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            f"background: {track};"
            "border-radius: 4px;"
            "}"
        )

    def _history_item_target_width(self) -> int:
        shell = getattr(self, "_experimental_shell", None)
        if shell is not None:
            return shell.history_target_width()
        list_widget = getattr(self, "history_list", None)
        if not isinstance(list_widget, QListWidget):
            return 260
        viewport = list_widget.viewport()
        width = viewport.width() if isinstance(viewport, QWidget) else list_widget.width()
        scrollbar = list_widget.verticalScrollBar()
        scrollbar_width = 0
        if scrollbar is not None:
            try:
                scrollbar_width = int(scrollbar.sizeHint().width())
            except Exception:
                scrollbar_width = 10
        # Account for card margins and the scrollbar gutter so cards do not clip.
        return max(228, int(width) - max(20, scrollbar_width + 16))

    def _apply_history_item_size_hint(self, item: QListWidgetItem, card: QWidget, min_height: int) -> None:
        if not isinstance(item, QListWidgetItem) or not isinstance(card, QWidget):
            return
        card_size = card.sizeHint().expandedTo(card.minimumSizeHint())
        card_size.setHeight(max(int(min_height), card_size.height() + 6))
        card_size.setWidth(self._history_item_target_width())
        item.setSizeHint(card_size)

    def _resize_history_item_widths(self) -> None:
        list_widget = getattr(self, "history_list", None)
        if not isinstance(list_widget, QListWidget):
            return
        target_width = self._history_item_target_width()
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            card = list_widget.itemWidget(item)
            if not isinstance(card, QWidget):
                continue
            hint = item.sizeHint()
            if hint.width() == target_width:
                continue
            hint.setWidth(target_width)
            item.setSizeHint(hint)

    # ------------------------------------------------------------------
    # Subject Handling
    # ------------------------------------------------------------------

    def on_subject_type(self, text: str):
        text = text.strip()
        if not text:
            if isinstance(getattr(self, "subject_suggestion_model", None), QStringListModel):
                self.subject_suggestion_model.setStringList([])
            self._hide_subject_completer_popup()
            return

        level = self.current_level
        all_subjects = SubjectDatabase.get_searchable_subjects(level)
        matches = []
        lowered = text.lower()
        for code, name in all_subjects.items():
            if lowered in code.lower() or lowered in name.lower():
                matches.append(f"{code} - {name}")

        if not matches:
            scored: List[Tuple[float, str]] = []
            for code, name in all_subjects.items():
                candidate = f"{code} - {name}"
                ratio = difflib.SequenceMatcher(None, lowered, candidate.lower()).ratio()
                if ratio >= 0.55:
                    scored.append((ratio, candidate))
            scored.sort(key=lambda row: row[0], reverse=True)
            matches = [entry for _, entry in scored[:10]]

        if isinstance(getattr(self, "subject_suggestion_model", None), QStringListModel):
            self.subject_suggestion_model.setStringList(matches[:12])

        if matches and isinstance(getattr(self, "subject_entry", None), QLineEdit) and self.subject_entry.hasFocus():
            completer = getattr(self, "subject_completer", None)
            if isinstance(completer, QCompleter):
                completer.complete()
        else:
            self._hide_subject_completer_popup()

    def _on_subject_completion_activated(self, text: str) -> None:
        self.subjects_set_from_text(str(text or "").strip())

    def _hide_subject_completer_popup(self) -> None:
        completer = getattr(self, "subject_completer", None)
        if not isinstance(completer, QCompleter):
            return
        popup = completer.popup()
        if isinstance(popup, QWidget):
            popup.hide()

    def on_subject_validate(self):
        text = self.subject_entry.text().strip()
        if not text:
            return
        self.subjects_set_from_text(text)

    def subjects_set_from_text(self, text: str):
        clean_text = str(text or "").strip()
        if not clean_text:
            self.subject_code = ""
            self.subject_name = ""
            self.update_series_availability("")
            self._sync_subject_browser()
            return

        parts = text.split("-")
        code = None
        if parts and parts[0].strip().isdigit():
            code = parts[0].strip()
        else:
            code = SubjectDatabase.find_subject_code(text, self.current_level)

        if not code:
            self.subject_code = ""
            self.subject_name = ""
            self.update_series_availability("")
            self._sync_subject_browser()
            if clean_text.isdigit() and len(clean_text) < 4:
                self.update_status("Type full 4-digit code or select from suggestions")
            else:
                self.update_status("Invalid subject")
            return

        if not SubjectDatabase.is_searchable_subject(code):
            self.subject_code = ""
            self.subject_name = ""
            self.update_series_availability("")
            self._sync_subject_browser()
            self.update_status("Selected subject is not available in current catalog")
            return

        self._apply_subject_selection(code, SubjectDatabase.get_subject_name(code), clear_entry=True)

    def on_level_change(self):
        checked = self.level_group.checkedButton()
        if checked is getattr(self, "igcse_level_btn", None):
            self.current_level = "IGCSE"
        else:
            self.current_level = "A Level"

        # Refresh suggestions and history
        self.on_subject_type(self.subject_entry.text())
        self.refresh_history()
        self.update_series_availability(self.subject_code or "")
        self._sync_subject_browser()

    def update_series_availability(self, subject_code: str) -> None:
        series_vars = getattr(self, "series_vars", {})
        if not isinstance(series_vars, dict) or not series_vars:
            return

        availability = SubjectDatabase.get_series_availability(subject_code)
        tooltip = str(availability.get("tooltip", "Data Check")).strip() or "Data Check"
        reason = str(availability.get("reason", "default")).strip() or "default"

        for series_code in ("MJ", "ON", "FM"):
            cb = series_vars.get(series_code)
            if not isinstance(cb, QCheckBox):
                continue
            enabled = bool(availability.get(series_code, True))
            try:
                cb.setEnabled(enabled)
            except Exception:
                pass
            if not enabled and cb.isChecked():
                cb.setChecked(False)
            if enabled and reason == "default":
                cb.setToolTip(f"{tooltip} ({series_code})")
            else:
                cb.setToolTip(tooltip)

        enabled_checked = [
            cb
            for cb in series_vars.values()
            if isinstance(cb, QCheckBox) and cb.isEnabled() and cb.isChecked()
        ]
        if not enabled_checked:
            for series_code in ("MJ", "ON", "FM"):
                cb = series_vars.get(series_code)
                if isinstance(cb, QCheckBox) and cb.isEnabled():
                    cb.setChecked(True)
                    break

        self._apply_series_checkbox_focus_styles()
        selected = [
            s
            for s, cb in series_vars.items()
            if isinstance(cb, QCheckBox) and cb.isEnabled() and cb.isChecked()
        ]
        self.update_variant_lock_ui(selected, None)

    def _on_series_selection_changed(self, _checked: bool) -> None:
        selected = [s for s, cb in self.series_vars.items() if cb.isChecked()]
        self.update_variant_lock_ui(selected, None)

    @staticmethod
    def _extract_paper_numbers_for_variant(components: List[str]) -> List[str]:
        papers: set[str] = set()
        for component in components:
            text = str(component or "").strip()
            if not text:
                continue
            digits = "".join(ch for ch in text if ch.isdigit())
            if not digits:
                continue
            papers.add(digits[0])
        return sorted(papers)

    @staticmethod
    def _apply_variant_to_components(components: List[str], variant: Optional[str]) -> List[str]:
        if variant not in {"1", "2", "3"}:
            return [str(c) for c in components]

        updated: List[str] = []
        seen: set[str] = set()
        for component in components:
            text = str(component or "").strip()
            if len(text) >= 2 and text[0].isdigit() and text[1].isdigit():
                text = f"{text[0]}{variant}{text[2:]}"
            if text not in seen:
                seen.add(text)
                updated.append(text)
        return updated

    @staticmethod
    def _series_display_label(series: str) -> str:
        lookup = {
            "MJ": "MJ",
            "ON": "ON",
            "FM": "FM",
        }
        return lookup.get(str(series or "").upper(), str(series or ""))

    def _flatten_group_items(self, include_resources: bool = True) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for group in self.search_results:
            if not isinstance(group, PaperGroup):
                continue
            for resource in group.all_documents(include_resources=include_resources):
                items.append(group.to_result_item(resource))
        return items

    @staticmethod
    def _build_exam_mode_resource_bundle(group: Optional[PaperGroup]) -> Dict[str, Dict[str, str]]:
        if not isinstance(group, PaperGroup):
            return {}

        def _resource_payload(resource: Optional[PaperResource]) -> Dict[str, str]:
            if not isinstance(resource, PaperResource):
                return {}
            return {
                "kind": str(resource.kind or ""),
                "filename": str(resource.filename or ""),
                "url": str(resource.direct_url or resource.download_url or resource.url or ""),
                "direct_url": str(resource.direct_url or resource.url or ""),
                "open_url": str(resource.direct_url or resource.download_url or resource.open_url or resource.url or ""),
                "download_url": str(resource.download_url or resource.direct_url or resource.url or ""),
                "extension": str(resource.extension or ""),
                "resource_family": str(resource.resource_family or ""),
            }

        def _series_letter(series: str) -> str:
            token = str(series or "").strip().upper()
            return {"MJ": "s", "ON": "w", "FM": "m"}.get(token, "")

        def _normalize_component(component: str) -> str:
            digits = "".join(ch for ch in str(component or "") if ch.isdigit())
            if not digits:
                return "00"
            if len(digits) == 1:
                return f"0{digits}"
            return digits[:2]

        def _derive_audio_paper_id(question_resource: Optional[PaperResource]) -> str:
            stem = ""
            if isinstance(question_resource, PaperResource):
                candidate_name = str(question_resource.filename or "").strip()
                if not candidate_name:
                    candidate_name = os.path.basename(urlparse(str(question_resource.url or "")).path)
                stem = os.path.splitext(candidate_name)[0].strip().lower()

            if stem:
                stem = re.sub(r"_(?:qp|ms|gt|in|tn)_(\d{1,2})$", r"_sf_\1", stem, flags=re.IGNORECASE)
                if re.fullmatch(r"\d{4}_[a-z]\d{2}_sf_\d{1,2}", stem, flags=re.IGNORECASE):
                    return stem.lower()

            subject_code = str(group.subject_code or "").strip()
            year_text = str(group.year or "").strip()
            year_suffix = year_text[-2:] if len(year_text) >= 2 else year_text
            letter = _series_letter(group.session)
            component = _normalize_component(group.component)
            if subject_code and year_suffix and letter and component:
                return f"{subject_code}_{letter}{year_suffix}_sf_{component}"
            return ""

        bundle: Dict[str, Dict[str, str]] = {}
        qp = group.primary_docs.get("QP") or group.primary_docs.get("SP_QP")
        ms = group.primary_docs.get("MS") or group.primary_docs.get("SP_MS")
        gt = group.primary_docs.get("GT") or group.resources.get("GT")
        insert = group.resources.get("IN") or group.resources.get("MAP")
        audio = group.resources.get("AU")
        derived_audio_paper_id = _derive_audio_paper_id(qp)
        if qp:
            bundle["question"] = _resource_payload(qp)
        if ms:
            bundle["mark_scheme"] = _resource_payload(ms)
        if gt:
            bundle["grade_threshold"] = _resource_payload(gt)
        if insert:
            bundle["insert"] = _resource_payload(insert)
        if audio:
            audio_payload = _resource_payload(audio)
            if derived_audio_paper_id:
                dynamic_audio_url = get_audio_url(derived_audio_paper_id)
                if dynamic_audio_url:
                    audio_payload["dynamic_url"] = dynamic_audio_url
                    audio_payload["paper_id"] = derived_audio_paper_id
            bundle["audio"] = audio_payload
        elif derived_audio_paper_id:
            dynamic_audio_url = get_audio_url(derived_audio_paper_id)
            if dynamic_audio_url:
                bundle["audio"] = {
                    "kind": "AU",
                    "filename": f"{derived_audio_paper_id}.mp3",
                    "url": dynamic_audio_url,
                    "open_url": dynamic_audio_url,
                    "download_url": dynamic_audio_url,
                    "extension": "mp3",
                    "resource_family": "AUDIO",
                    "paper_id": derived_audio_paper_id,
                    "dynamic_url": dynamic_audio_url,
                }

        for kind, key in {
            "SF": "source_file",
            "TN": "transcript",
            "MAP": "map",
            "IN": "insert",
        }.items():
            resource = group.resources.get(kind)
            if not resource:
                continue
            bundle[key] = _resource_payload(resource)
        return bundle

    def update_variant_lock_ui(self, selected_sessions: List[str], locked_variant: Optional[str]) -> None:
        fm_selected = "FM" in {str(s).upper() for s in selected_sessions}
        if fm_selected:
            if locked_variant in {"1", "2", "3"}:
                self.variant_lock_note.setText(
                    f"Feb/March papers are typically produced in a single variant, so the variant is locked to {locked_variant}."
                )
            else:
                self.variant_lock_note.setText(
                    "Feb/March papers are typically produced in a single variant, so the variant is locked."
                )
            self.variant_lock_note.setVisible(True)
            return

        self.variant_lock_note.setText(
            "Feb/March papers are typically produced in a single variant, so the variant is locked"
        )
        self.variant_lock_note.setVisible(False)

    # ------------------------------------------------------------------
    # Search + Results
    # ------------------------------------------------------------------

    def update_status(self, message: str):
        self.publish_status_event("app", message)

    def publish_status_event(self, source: str, message: str) -> None:
        key = str(source or "app").strip() or "app"
        text = str(message or "").strip()
        if text:
            self._global_status_context[key] = text
        else:
            self._global_status_context.pop(key, None)
        snapshot = " | ".join(f"{k}: {v}" for k, v in self._global_status_context.items())
        if isinstance(getattr(self, "status_surface_label", None), QLabel):
            self.status_surface_label.setText(f"Status: {snapshot or 'Ready'}")

    def _set_search_busy_state(self, busy: bool) -> None:
        watchdog = getattr(self, "_search_state_watchdog", None)
        if isinstance(watchdog, QTimer):
            if busy:
                if not watchdog.isActive():
                    watchdog.start()
            elif watchdog.isActive():
                watchdog.stop()
        if self.search_button:
            self.search_button.setEnabled(not busy)
            self.search_button.setText("Searching..." if busy else "Search Papers")
            self.search_button.setProperty("searchBusy", bool(busy))
            self._apply_search_button_theme_style()
        self.publish_status_event("search", "Searching..." if busy else "")

    def _recover_search_button_state(self) -> None:
        button = getattr(self, "search_button", None)
        if not isinstance(button, QPushButton):
            watchdog = getattr(self, "_search_state_watchdog", None)
            if isinstance(watchdog, QTimer) and watchdog.isActive():
                watchdog.stop()
            return

        thread = getattr(self, "search_thread", None)
        thread_running = False
        if thread is not None:
            try:
                thread_running = bool(thread.isRunning())
            except Exception:
                thread_running = False
        if thread_running:
            return

        button_busy = (
            not button.isEnabled()
            or bool(button.property("searchBusy"))
            or str(button.text() or "").strip() == "Searching..."
        )
        if button_busy:
            self._set_search_busy_state(False)
            return

        watchdog = getattr(self, "_search_state_watchdog", None)
        if isinstance(watchdog, QTimer) and watchdog.isActive():
            watchdog.stop()

    def _clear_results_container_widgets(self) -> None:
        self._close_active_quick_look()
        self.exam_launch_footer.hide()
        while self.results_container_layout.count():
            item = self.results_container_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()

    def _show_results_skeleton(self, card_count: int = 6) -> None:
        if getattr(self, '_dashboard', None):
            self._dashboard.enter_results()
        self._results_skeleton_active = True
        self._results_skeleton_phase = 0.0
        self._results_skeleton_bars = []
        self._clear_results_container_widgets()
        count = max(2, int(card_count))
        for _ in range(count):
            card = QFrame()
            card.setProperty("themeRole", "skeletonCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(8)
            for width in (0.72, 0.56, 0.84):
                bar = QFrame(card)
                bar.setObjectName("skeletonBar")
                bar.setMinimumHeight(11)
                bar.setMaximumHeight(11)
                bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                bar.setProperty("skeletonWidthFactor", float(width))
                card_layout.addWidget(bar)
                self._results_skeleton_bars.append(bar)
            self.results_container_layout.addWidget(card)
        self.results_container_layout.addStretch(1)
        self._tick_results_skeleton_shimmer()
        self._results_skeleton_timer.start()

    def _hide_results_skeleton(self) -> None:
        self._results_skeleton_active = False
        self._results_skeleton_timer.stop()
        self._results_skeleton_bars = []
        self._clear_results_container_widgets()

    def _tick_results_skeleton_shimmer(self) -> None:
        if not self._results_skeleton_active:
            return
        self._results_skeleton_phase += 0.18
        shimmer_t = (math.sin(self._results_skeleton_phase) + 1.0) * 0.5
        base = self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.35)
        shimmer = self._mix_colors(base, Colors.TEXT_WHITE, 0.16)
        active = self._mix_colors(base, shimmer, shimmer_t)
        for bar in list(self._results_skeleton_bars):
            if bar is None or not self._is_qt_object_alive(bar):
                continue
            width_factor = float(bar.property("skeletonWidthFactor") or 0.7)
            parent = bar.parentWidget()
            if parent is not None:
                available = max(80, parent.width() - 28)
                bar.setFixedWidth(max(70, int(available * max(0.35, min(0.95, width_factor)))))
            bar.setStyleSheet(
                "QFrame#skeletonBar {"
                f"background-color: {active};"
                "border-radius: 5px;"
                "}"
            )

    def _show_results_empty_state(self, message: str = "Try adjusting your filters", *, title: str = "No Results") -> None:
        if getattr(self, '_dashboard', None):
            self._dashboard.enter_results()
        self._empty_state_message = message
        self._hide_results_skeleton()
        self._clear_results_container_widgets()
        wrapper = QWidget(self.results_container)
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        wrapper.setMaximumWidth(560)
        row = QVBoxLayout(wrapper)
        row.setContentsMargins(24, 24, 24, 24)
        row.setSpacing(12)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        asset = str(self._empty_state_svg_path or "").strip()
        if asset and QSvgWidget is not None and os.path.exists(asset):
            try:
                art = QSvgWidget(wrapper)
                from UI.theme_assets import themed_empty_state_svg
                art.load(themed_empty_state_svg(asset, transparent_background=True))
                ratio = 1.6
                try:
                    renderer = art.renderer()
                    if renderer is not None:
                        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
                        default_size = renderer.defaultSize()
                        width = int(default_size.width()) if default_size is not None else 0
                        height = int(default_size.height()) if default_size is not None else 0
                        if width > 0 and height > 0:
                            ratio = float(width) / float(height)
                except Exception:
                    pass
                viewport_width = max(720, int(self.results_scroll.viewport().width())) if self.results_scroll else 1200
                target_width = max(220, min(320, int(viewport_width * 0.24)))
                target_height = max(120, min(220, int(round(float(target_width) / max(0.6, ratio)))))
                art.setFixedSize(target_width, target_height)
                row.addWidget(art, 0, Qt.AlignmentFlag.AlignCenter)
            except Exception:
                pass

        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title_label, 0, Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(str(message or "Try adjusting your filters"))
        subtitle.setProperty("themeRole", "metadata")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setMaximumWidth(420)
        subtitle.setMinimumWidth(min(420, subtitle.fontMetrics().horizontalAdvance(subtitle.text()) + 4))
        subtitle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        subtitle.setMinimumHeight(subtitle.heightForWidth(subtitle.minimumWidth()))
        subtitle.setObjectName("resultsEmptySubtitle")
        row.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignCenter)
        self.results_container_layout.addStretch(1)
        self.results_container_layout.addWidget(wrapper, 0, Qt.AlignmentFlag.AlignCenter)
        self.results_container_layout.addStretch(2)

    def _close_loading_dialog(self) -> None:
        loading = getattr(self, "loading", None)
        self.loading = None
        if not isinstance(loading, QDialog):
            return
        if isinstance(loading, LoadingDialog):
            try:
                loading.suppress_cancel_signal()
            except Exception:
                pass
            try:
                loading.cancelled.disconnect(self._cancel_active_search)
            except Exception:
                pass
        try:
            loading.hide()
        except Exception:
            pass
        try:
            loading.close()
        except Exception:
            pass

    def _release_search_thread(self) -> None:
        thread = getattr(self, "search_thread", None)
        self.search_thread = None
        if thread is None:
            return
        for signal, slot in ((thread.results_ready, self.on_search_complete), (thread.error, self.on_search_error),
                             (thread.progress_update, self.on_search_progress_update),
                             (thread.partial_results, self.on_search_partial_results), (thread.cancelled, self.on_search_cancelled)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        if thread.isRunning():
            if thread not in self._orphan_search_threads:
                self._orphan_search_threads.append(thread)
        else:
            thread.deleteLater()

    def _on_search_thread_finished(self) -> None:
        thread = self.sender()
        if thread in self._orphan_search_threads:
            self._orphan_search_threads.remove(thread)
        if thread is not self.search_thread and thread is not None:
            thread.deleteLater()

    def _finalize_search_ui(self) -> None:
        self._close_loading_dialog()
        self._set_search_busy_state(False)
        self._release_search_thread()

    def _resolve_signal_generation(self, generation: Optional[int] = None) -> Optional[int]:
        if generation is not None:
            try:
                return int(generation)
            except Exception:
                return None
        sender = self.sender()
        if sender is None:
            return None
        try:
            value = getattr(sender, "_search_generation", None)
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _is_stale_search_signal(self, generation: Optional[int] = None) -> bool:
        signal_generation = self._resolve_signal_generation(generation)
        if signal_generation is None:
            return False
        return int(signal_generation) != int(self._active_search_generation)

    def _cancel_resets_results_enabled(self) -> bool:
        try:
            cfg = ConfigManager.get_search_config()
            return bool(cfg.get("cancel_resets_results", True))
        except Exception:
            return True

    def _reset_search_results_section(self, status_message: str = "Search cancelled") -> None:
        self.search_results = []
        self._hide_results_skeleton()
        try:
            self.results_count.setText("(0 found)")
        except Exception:
            pass
        try:
            self._clear_results_container_widgets()
        except Exception:
            pass
        try:
            self.open_all_button.setEnabled(False)
        except Exception:
            pass
        try:
            self.download_all_button.setEnabled(False)
        except Exception:
            pass
        try:
            if isinstance(getattr(self, "build_offline_pack_button", None), QPushButton):
                self.build_offline_pack_button.setEnabled(False)
        except Exception:
            pass
        self._show_results_empty_state(
            "Try adjusting your filters",
            title="No Papers Found" if status_message == "No Papers Found" else "No Results",
        )
        if status_message != 'No Papers Found' and getattr(self, '_dashboard', None):
            self._dashboard.show_home()
        self.update_status(status_message)

    def _cancel_active_search(
        self,
        force_reset_results: bool = False,
        status_message: str = "Search cancelled",
    ) -> None:
        thread = getattr(self, "search_thread", None)
        has_active = False
        if thread is not None:
            try:
                has_active = bool(thread.isRunning())
            except Exception:
                has_active = True
            try:
                thread.request_cancel()
            except Exception:
                pass
        self._active_search_generation += 1
        self._finalize_search_ui()
        self._hide_results_skeleton()
        should_reset_results = bool(force_reset_results) or self._cancel_resets_results_enabled()
        if has_active and should_reset_results:
            self._reset_search_results_section(status_message)
        elif has_active:
            self.update_status(status_message)

    def _run_deferred_history_search(self, generation: int) -> None:
        if int(generation) != int(self._history_search_request_generation):
            return
        self.on_search()

    def _launch_history_search_preemptively(self) -> None:
        self._history_search_request_generation += 1
        generation = int(self._history_search_request_generation)
        thread = getattr(self, "search_thread", None)
        is_active = False
        if thread is not None:
            try:
                is_active = bool(thread.isRunning())
            except Exception:
                is_active = True
        if is_active:
            self._cancel_active_search(
                force_reset_results=True,
                status_message="Switching to selected recent search...",
            )
        QTimer.singleShot(0, lambda g=generation: self._run_deferred_history_search(g))

    def on_search(self):
        subject = self.subject_code
        if not subject:
            show_error(self, "Missing Subject", "Please select a subject first.")
            return
        if not SubjectDatabase.is_searchable_subject(subject):
            show_error(
                self,
                "Unsupported Subject",
                "This subject is not available in the active catalog.",
            )
            return

        series = [s for s, cb in self.series_vars.items() if cb.isChecked()]
        if not series:
            show_error(self, "Missing Series", "Please select at least one series.")
            return

        comp_text = self.component_entry.text().strip()
        if not comp_text:
            show_error(self, "Missing Components", "Please enter component(s).")
            return

        components = parse_range(comp_text, minimum=1, maximum=99, max_items=40)
        if not components:
            show_error(self, "Invalid Components", "Please enter valid component(s).")
            return

        year_text = self.year_entry.text().strip()
        years: List[str] = []
        current_year = datetime.now().year
        if year_text:
            years = parse_range(year_text, minimum=0, maximum=9999, max_items=50)
            if any(not (0 <= int(year) <= 99 or 1900 <= int(year) <= 9999) for year in years):
                years = []
            if not years:
                show_error(self, "Invalid Years", "Please enter valid year(s).")
                return
        else:
            show_error(self, "Missing Years", "Please enter year(s).")
            return

        doc_types = []
        if self.paper_var.isChecked():
            doc_types.append("QP")
        if self.ms_var.isChecked():
            doc_types.append("MS")
        if self.gt_var.isChecked():
            doc_types.append("GT")

        if not doc_types:
            show_error(self, "Missing Types", "Please select at least one document type.")
            return

        base_components = [str(c).strip() for c in components if str(c).strip()]
        series_component_map: Dict[str, List[str]] = {s: list(base_components) for s in series}

        warnings: List[str] = []
        validated_series_component_map: Dict[str, List[str]] = {}
        for series_code in series:
            target_components = series_component_map.get(series_code, [])
            valid, invalid = ComponentsDatabase.validate_components(subject, target_components)
            if invalid:
                warnings.append(f"{series_code}: {', '.join(map(str, invalid))}")
            if valid:
                validated_series_component_map[series_code] = valid

        if warnings:
            show_warning(
                self,
                "Invalid Components",
                f"Some components are not valid for {subject}:\n" + "\n".join(warnings),
            )

        has_valid_series_components = any(validated_series_component_map.get(code) for code in series)
        if not has_valid_series_components:
            show_error(self, "Invalid Components", "No valid components were provided for the selected series.")
            return

        merged_components: List[str] = []
        seen_components: set[str] = set()
        for series_code in series:
            for comp in validated_series_component_map.get(series_code, []):
                if comp not in seen_components:
                    seen_components.add(comp)
                    merged_components.append(comp)

        self.search_params = {
            "subject_code": subject,
            "subject_name": self.subject_name or SubjectDatabase.get_subject_name(subject),
            "series": series,
            "components": merged_components,
            "series_component_map": validated_series_component_map,
            "years": years,
            "doc_types": doc_types,
        }

        # Sources interpret two-digit years as 20xx. Never fetch future papers.
        years = [year for year in years
                 if (2000 + int(year) if int(year) <= 99 else int(year)) <= current_year]
        self.search_params["years"] = years
        if not years:
            self._cancel_active_search(force_reset_results=True)
            self._reset_search_results_section("No Papers Found")
            return

        self.update_variant_lock_ui(series, None)
        self.perform_search()

    def perform_search(self):
        params = self.search_params

        existing_thread = getattr(self, "search_thread", None)
        try:
            if existing_thread and existing_thread.isRunning():
                try:
                    existing_thread.request_cancel()
                except Exception:
                    pass
                # Mark current worker signals stale before launching a replacement search.
                self._active_search_generation += 1
                self._release_search_thread()
                self.update_status("Updating search...")
        except Exception:
            pass
        self._release_search_thread()

        self._set_search_busy_state(True)
        self._show_results_skeleton(card_count=6)
        self._active_search_generation += 1
        search_generation = int(self._active_search_generation)

        thread_ref: Dict[str, Optional[SearchThread]] = {"thread": None}

        def cancel_requested() -> bool:
            thread = thread_ref.get("thread")
            if thread is None:
                return False
            try:
                return bool(thread.isInterruptionRequested())
            except Exception:
                return False

        def do_search(
            *,
            progress_callback: Optional[Callable[[str, Dict[str, object]], None]] = None,
            partial_callback: Optional[Callable[[List[PaperGroup], bool], None]] = None,
            cancel_check: Optional[Callable[[], bool]] = None,
        ):
            return PaperSourceManager.search_papers_multi_source(
                params["subject_code"],
                params["series"],
                params["components"],
                params["years"],
                params["doc_types"],
                series_component_map=params.get("series_component_map"),
                cancel_check=cancel_check or cancel_requested,
                progress_callback=progress_callback,
                partial_callback=partial_callback,
            )

        self.search_thread = SearchThread(do_search, parent=self)
        self.search_thread.finished.connect(self._on_search_thread_finished)
        setattr(self.search_thread, "_search_generation", search_generation)
        thread_ref["thread"] = self.search_thread
        self.search_thread.results_ready.connect(self.on_search_complete)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.progress_update.connect(self.on_search_progress_update)
        self.search_thread.partial_results.connect(self.on_search_partial_results)
        self.search_thread.cancelled.connect(self.on_search_cancelled)
        self.search_thread.start()

    def on_search_complete(self, results, generation: Optional[int] = None):
        if self._is_stale_search_signal(generation):
            return
        self._finalize_search_ui()
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        if self.subject_code:
            self.subjects_set_from_text(f"{self.subject_code} - {self.subject_name}")
        self._hide_results_skeleton()
        self.display_results(results)

    def on_search_progress_update(self, message: str, metrics: object, generation: Optional[int] = None) -> None:
        if self._is_stale_search_signal(generation):
            return
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        text = str(message or "").strip()
        if not text:
            return
        self.update_status(text)
        self.publish_status_event("search", text)

    def on_search_partial_results(self, results: object, is_final: bool, generation: Optional[int] = None) -> None:
        if self._is_stale_search_signal(generation):
            return
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        if bool(is_final):
            return
        if not isinstance(results, list) or not results:
            return
        self._hide_results_skeleton()
        self.display_results(results, record_history=False, partial=True)
        # Keep the app responsive for follow-up searches once there are visible matches.
        if self.search_button and bool(self.search_button.property("searchBusy")):
            self._set_search_busy_state(False)

    def on_search_error(self, error_msg: str, generation: Optional[int] = None):
        if self._is_stale_search_signal(generation):
            return
        self._finalize_search_ui()
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        self._hide_results_skeleton()
        show_error(self, "Search Error", error_msg)

    def on_search_cancelled(self, generation: Optional[int] = None) -> None:
        if self._is_stale_search_signal(generation):
            return
        self._finalize_search_ui()
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        self._hide_results_skeleton()
        if self._cancel_resets_results_enabled():
            self._reset_search_results_section("Search cancelled")
        else:
            self.update_status("Search cancelled")

    def display_results(
        self,
        results: List[PaperGroup],
        *,
        record_history: bool = True,
        partial: bool = False,
    ):
        from Core.background_tasks import gui_work_pending
        if getattr(self, '_dashboard', None):
            self._dashboard.enter_results()
        if gui_work_pending():
            # Keep preview widgets alive until their pending PDF request returns.
            QTimer.singleShot(50, lambda: self.display_results(results, record_history=record_history, partial=partial))
            return
        normalized_results: List[PaperGroup] = []
        for group in list(results or []):
            try:
                code = str(getattr(group, "subject_code", "") or "").strip()
                if code:
                    group.subject_name = SubjectDatabase.get_subject_name(code)
            except Exception:
                pass
            normalized_results.append(group)

        self.search_results = normalized_results
        group_count = len(self.search_results)
        document_count = len(self._flatten_group_items(include_resources=True))
        if group_count <= 0 and document_count <= 0:
            self.results_count.setText("(0 found)")
        else:
            group_label = "group" if group_count == 1 else "groups"
            doc_label = "document" if document_count == 1 else "documents"
            self.results_count.setText(f"({document_count} {doc_label} in {group_count} {group_label})")
        self._hide_results_skeleton()
        self._clear_results_container_widgets()
        if not self.search_results:
            if partial:
                return
            self.open_all_button.setEnabled(False)
            self.download_all_button.setEnabled(False)
            if isinstance(getattr(self, "build_offline_pack_button", None), QPushButton):
                self.build_offline_pack_button.setEnabled(False)
            self._show_results_empty_state("Try adjusting your filters")
            self.update_status("No results found")
            return

        self.open_all_button.setEnabled(True)
        self.download_all_button.setEnabled(True)
        if isinstance(getattr(self, "build_offline_pack_button", None), QPushButton):
            self.build_offline_pack_button.setEnabled(True)
        if self._results_view_mode == "grid":
            self._render_results_grid_view()
        else:
            self._render_results_list_view()

        shell = getattr(self, "_experimental_shell", None)
        if shell is not None:
            shell.prepare_results()

        self.exam_launch_footer.setVisible(
            EXAM_MODE_AVAILABLE and any(
                group.primary_docs.get("QP") or group.primary_docs.get("SP_QP")
                for group in self.search_results))

        if record_history and self.search_results:
            first = self.search_results[0]
            HistoryManager.add_to_history(
                first.subject_code,
                first.subject_name,
                first.session,
                first.component,
                first.year,
            )
            self.refresh_history()

        self._refresh_text_interaction_support()
        if partial:
            self.update_status(f"Showing {document_count} documents across {group_count} groups (partial)")
        else:
            self.update_status(f"Found {document_count} documents across {group_count} groups")

    def _set_results_view_mode(self, mode: str, *, persist: bool = True, rerender: bool = True) -> None:
        normalized = str(mode or "list").strip().lower()
        if normalized not in {"list", "grid"}:
            normalized = "list"
        self._results_view_mode = normalized
        list_btn = getattr(self, "results_view_list_btn", None)
        grid_btn = getattr(self, "results_view_grid_btn", None)
        if isinstance(list_btn, QToolButton):
            blocked = list_btn.blockSignals(True)
            list_btn.setChecked(normalized == "list")
            list_btn.blockSignals(blocked)
        if isinstance(grid_btn, QToolButton):
            blocked = grid_btn.blockSignals(True)
            grid_btn.setChecked(normalized == "grid")
            grid_btn.blockSignals(blocked)
        if persist:
            ConfigManager.set_dashboard_results_view(normalized)
        if rerender and self.search_results:
            self._results_view_rerender_generation += 1
            generation = int(self._results_view_rerender_generation)
            QTimer.singleShot(
                0,
                lambda g=generation: self._deferred_results_view_rerender(g),
            )

    def _deferred_results_view_rerender(self, generation: int) -> None:
        if int(generation) != int(self._results_view_rerender_generation):
            return
        if not self.search_results:
            return
        self.display_results(list(self.search_results), record_history=False)

    def _render_results_list_view(self) -> None:
        self.results_container_layout.addSpacing(32)
        for group in self.search_results:
            group_card = DashboardCard(theme_role="groupCard")
            group_layout = QHBoxLayout(group_card)
            group_layout.setContentsMargins(14, 12, 14, 12)
            group_layout.setSpacing(10)
            session_label = self._series_display_label(group.session)
            group_items = [group.to_result_item(resource) for resource in group.all_documents(include_resources=True)]
            title_col = QVBoxLayout()
            title_col.setContentsMargins(0, 0, 0, 0)
            title_col.setSpacing(4)
            title = QLabel(str(group.subject_name or "Unknown Subject"))
            title.setFont(QFont("Arial", 14, QFont.Weight.Black))
            title_col.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
            docs_count = len(group_items)
            doc_word = "document" if docs_count == 1 else "documents"
            meta = QLabel(f"{docs_count} {doc_word} | {session_label} {group.year} | Comp {group.component}")
            meta.setProperty("themeRole", "metadata")
            meta.setWordWrap(True)
            title_col.addWidget(meta, 0, Qt.AlignmentFlag.AlignLeft)
            group_layout.addLayout(title_col, 1)
            code = QLabel(f"{group.subject_code}/{group.component}")
            code.setProperty("themeRole", "paperCode")
            group_layout.addWidget(code, 0, Qt.AlignmentFlag.AlignTop)
            open_btn = QPushButton("Open")
            self._style_card_action_button(open_btn, Colors.SECONDARY)
            open_btn.clicked.connect(lambda _, i=group_items: self.open_papers(i))
            download_btn = QPushButton("Download")
            self._style_card_action_button(download_btn, Colors.INFO)
            download_btn.clicked.connect(lambda _, i=group_items: self.download_papers(i))
            group_layout.addWidget(open_btn)
            group_layout.addWidget(download_btn)
            self.results_container_layout.addWidget(group_card)
            for resource in group.all_documents(include_resources=True):
                self.results_container_layout.addWidget(self.create_result_item(group, resource, compact=False))
        self.results_container_layout.addStretch(1)

    def _render_results_grid_view(self) -> None:
        self.results_container_layout.addSpacing(32)
        grid_host = QWidget(self.results_container)
        grid_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(2, 2, 10, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        flat: List[Tuple[PaperGroup, PaperResource]] = []
        for group in self.search_results:
            for resource in group.all_documents(include_resources=True):
                flat.append((group, resource))
        viewport_width = max(380, self.results_scroll.viewport().width()) if self.results_scroll else 1200
        usable_width = max(320, viewport_width - 22)
        min_column_width = 430
        max_columns = 3
        columns = max(1, min(max_columns, int(usable_width // min_column_width)))
        for idx, pair in enumerate(flat):
            row_idx = idx // columns
            col_idx = idx % columns
            card = self.create_result_item(pair[0], pair[1], compact=True)
            card.setMinimumWidth(392)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            grid.addWidget(card, row_idx, col_idx)
        for col_idx in range(columns):
            grid.setColumnStretch(col_idx, 1)
        self.results_container_layout.addWidget(grid_host)
        self.results_container_layout.addStretch(1)

    def _style_card_action_button(self, button: QPushButton, base_color: str) -> None:
        button.setStyleSheet(self._action_button_style_for_theme(base_color))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(32)
        button.setMinimumWidth(92)
        button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        button.installEventFilter(self)

    @staticmethod
    def _result_kind_badge(item: Dict[str, Any]) -> str:
        kind = str(item.get("resource_kind") or item.get("type") or "").strip().upper()
        return {
            "QP": "QP",
            "P": "QP",
            "SP_QP": "SP QP",
            "MS": "MS",
            "SP_MS": "SP MS",
            "GT": "GT",
            "ER": "ER",
            "IN": "IN",
            "SF": "SF",
            "AU": "AU",
            "TN": "TN",
            "MAP": "MAP",
        }.get(kind, kind or "--")

    def _result_signal_badges(self, group: PaperGroup, item: Dict[str, Any]) -> List[str]:
        badges: List[str] = []
        if group.primary_docs.get("MS") or group.primary_docs.get("SP_MS"):
            badges.append("[Has MS]")
        if group.resources.get("IN"):
            badges.append("[Has Insert]")
        if group.resources.get("AU"):
            badges.append("[Has Audio]")
        if bool(item.get("is_specimen")):
            badges.append("[Specimen]")
        if bool(item.get("downloaded")):
            badges.append("[Downloaded]")
        if bool(item.get("attempted")):
            badges.append("[Attempted]")
        return badges

    @staticmethod
    def _item_supports_quick_look(item: Dict[str, Any]) -> bool:
        kind = str(item.get("resource_kind") or item.get("type") or "").strip().upper()
        if kind == "AU":
            return False
        extension = str(item.get("extension", "") or "").strip().lower().lstrip(".")
        if extension == "pdf":
            return True
        url = str(item.get("direct_url") or item.get("download_url") or item.get("url") or "").strip().lower()
        return url.endswith(".pdf")

    @staticmethod
    def _quick_look_cache_key(item: Dict[str, Any]) -> str:
        return str(item.get("direct_url") or item.get("download_url") or item.get("url") or item.get("filename") or "")

    def _quick_look_page_count(self, item: Dict[str, Any]) -> int:
        if not _PDF_PREVIEW_AVAILABLE:
            return 0
        cache_key = self._quick_look_cache_key(item)
        if not cache_key:
            return 0
        cached_count = self._quick_look_pdf_cache.get(f"pages::{cache_key}")
        if cached_count:
            try:
                return max(0, int(cached_count))
            except Exception:
                pass
        pdf_path = self._resolve_quick_look_pdf_path(item)
        if not pdf_path:
            return 0
        try:
            doc = fitz.open(pdf_path)
            count = max(0, int(doc.page_count))
            doc.close()
            self._quick_look_pdf_cache[f"pages::{cache_key}"] = str(count)
            return count
        except Exception:
            return 0

    def _quick_look_preview_pixmap(self, item: Dict[str, Any], page_index: int = 0) -> Optional[QPixmap]:
        if not _PDF_PREVIEW_AVAILABLE:
            return None
        cache_key = self._quick_look_cache_key(item)
        if not cache_key:
            return None
        page = max(0, int(page_index))
        page_cache_key = f"{cache_key}::p{page}"
        cached = self._quick_look_pixmap_cache.get(page_cache_key)
        if isinstance(cached, QPixmap) and not cached.isNull():
            return cached
        pdf_path = self._resolve_quick_look_pdf_path(item)
        if not pdf_path:
            return None
        try:
            doc = fitz.open(pdf_path)
            if page >= int(doc.page_count):
                doc.close()
                return None
            page_obj = doc.load_page(page)
            pix = page_obj.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
            fmt = QImage.Format.Format_RGB888
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
            qpix = QPixmap.fromImage(image)
            doc.close()
            if not qpix.isNull():
                self._quick_look_pixmap_cache[page_cache_key] = qpix
            return qpix
        except Exception:
            return None

    def _quick_look_target_width(self, preview_frame: QFrame, preview_state: Dict[str, Any]) -> int:
        compact = bool(preview_frame.property("quickLookCompact"))
        scroll_area = preview_state.get("scroll_area")
        viewport_width = 0
        if isinstance(scroll_area, QScrollArea):
            try:
                viewport_width = int(scroll_area.viewport().width())
            except Exception:
                viewport_width = 0
        parent_card = preview_frame.parentWidget()
        card_width = int(parent_card.width()) if isinstance(parent_card, QWidget) else 0
        frame_width = int(preview_frame.width())
        available_width = max(viewport_width, frame_width, card_width)
        if available_width <= 0:
            panel_width = self.results_scroll.viewport().width() if self.results_scroll else 1200
            available_width = int(panel_width * (0.34 if compact else 0.68))
        side_padding = 36 if compact else 42
        if compact:
            return max(210, min(460, int(available_width) - side_padding))
        return max(280, min(860, int(available_width) - side_padding))

    def _quick_look_scaled_pixmap(
        self,
        item: Dict[str, Any],
        page: int,
        base_pixmap: QPixmap,
        zoom_factor: float,
        target_width: int,
        compact: bool,
    ) -> Optional[QPixmap]:
        if not isinstance(base_pixmap, QPixmap) or base_pixmap.isNull():
            return None
        render_width = max(190, int(round(float(target_width) * float(zoom_factor))))
        cache_key = self._quick_look_cache_key(item)
        if not cache_key:
            return base_pixmap.scaledToWidth(
                render_width,
                Qt.TransformationMode.SmoothTransformation,
            )
        zoom_bucket = int(round(float(zoom_factor) * 100.0))
        scaled_key = f"scaled::{cache_key}::p{int(page)}::z{zoom_bucket}::w{int(render_width)}::c{int(bool(compact))}"
        cached = self._quick_look_pixmap_cache.get(scaled_key)
        if isinstance(cached, QPixmap) and not cached.isNull():
            return cached
        scaled = base_pixmap.scaledToWidth(
            render_width,
            Qt.TransformationMode.SmoothTransformation,
        )
        if isinstance(scaled, QPixmap) and not scaled.isNull():
            self._quick_look_pixmap_cache[scaled_key] = scaled
            return scaled
        return None

    def _schedule_quick_look_preview_refresh(
        self,
        item: Dict[str, Any],
        preview_frame: QFrame,
        preview_image: QLabel,
        preview_text: QLabel,
        preview_meta: QLabel,
        preview_state: Dict[str, Any],
    ) -> None:
        timer = preview_state.get("zoom_timer")
        if not isinstance(timer, QTimer):
            timer = QTimer(preview_frame)
            timer.setSingleShot(True)
            timer.setInterval(24)
            timer.timeout.connect(
                lambda it=dict(item), pf=preview_frame, pi=preview_image, pt=preview_text, pm=preview_meta, ps=preview_state:
                    self._show_quick_look_preview(
                        it,
                        pf,
                        pi,
                        pt,
                        pm,
                        ps,
                        page_index=int(ps.get("page", 0)),
                    )
            )
            preview_state["zoom_timer"] = timer
        try:
            timer.start()
        except Exception:
            self._show_quick_look_preview(
                item,
                preview_frame,
                preview_image,
                preview_text,
                preview_meta,
                preview_state,
                page_index=int(preview_state.get("page", 0)),
            )

    def _resolve_quick_look_pdf_path(self, item: Dict[str, Any]) -> Optional[str]:
        candidate = str(item.get("direct_url") or item.get("download_url") or item.get("url") or "").strip()
        if os.path.isfile(candidate):
            return candidate
        cached = self._quick_look_pdf_cache.get(candidate)
        if cached and os.path.isfile(cached):
            return cached
        if not candidate.lower().startswith(("http://", "https://")):
            return None
        try:
            path = download_pdf(candidate)
            self._quick_look_pdf_cache[candidate] = path
            if len(self._quick_look_pdf_cache) > 40:
                self._clear_quick_look_cache(keep=candidate)
            return path
        except (OSError, ValueError, requests.RequestException):
            return None

    def _clear_quick_look_cache(self, keep=None):
        from Core.download_service import remove_owned_temporary_file
        for key, value in list(self._quick_look_pdf_cache.items()):
            if key == keep:
                continue
            remove_owned_temporary_file(value)
            self._quick_look_pdf_cache.pop(key, None)
        self._quick_look_pixmap_cache.clear()

    def _close_active_quick_look(self, *, exclude: Optional[QFrame] = None) -> None:
        active = getattr(self, "_active_quick_look_frame", None)
        if not isinstance(active, QFrame):
            self._active_quick_look_frame = None
            return
        if exclude is not None and active is exclude:
            return
        try:
            active.setVisible(False)
        except Exception:
            pass
        self._active_quick_look_frame = None

    def _clear_active_quick_look_if_matches(self, frame: Optional[QFrame]) -> None:
        if isinstance(frame, QFrame) and getattr(self, "_active_quick_look_frame", None) is frame:
            self._active_quick_look_frame = None

    def _toggle_quick_look(
        self,
        item: Dict[str, Any],
        preview_frame: QFrame,
        preview_image: QLabel,
        preview_text: QLabel,
        preview_meta: QLabel,
        preview_state: Dict[str, Any],
    ) -> None:
        if preview_frame.isVisible():
            preview_frame.setVisible(False)
            self._clear_active_quick_look_if_matches(preview_frame)
            return
        self._close_active_quick_look(exclude=preview_frame)
        self._show_quick_look_preview(
            item,
            preview_frame,
            preview_image,
            preview_text,
            preview_meta,
            preview_state,
            page_index=int(preview_state.get("page", 0)),
        )
        if preview_frame.isVisible():
            self._active_quick_look_frame = preview_frame

    def _show_quick_look_preview(
        self,
        item: Dict[str, Any],
        preview_frame: QFrame,
        preview_image: QLabel,
        preview_text: QLabel,
        preview_meta: QLabel,
        preview_state: Dict[str, Any],
        *,
        page_index: int = 0,
    ) -> None:
        if not self._item_supports_quick_look(item):
            preview_text.setText("Preview unavailable for this resource type")
            preview_text.setVisible(True)
            preview_meta.setVisible(False)
            preview_image.setVisible(False)
            preview_frame.setVisible(True)
            return
        page_count = max(0, self._quick_look_page_count(item))
        if page_count <= 0:
            preview_text.setText("Preview could not be loaded")
            preview_text.setVisible(True)
            preview_meta.setVisible(False)
            preview_image.setVisible(False)
            preview_frame.setVisible(True)
            return
        page = max(0, min(page_count - 1, int(page_index)))
        zoom_factor = max(0.55, min(3.5, float(preview_state.get("zoom", 1.0) or 1.0)))
        compact = bool(preview_frame.property("quickLookCompact"))
        previous_page = int(preview_state.get("page", -1))
        pixmap = self._quick_look_preview_pixmap(item, page)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            target_width = self._quick_look_target_width(preview_frame, preview_state)
            scaled = self._quick_look_scaled_pixmap(
                item,
                page,
                pixmap,
                zoom_factor,
                target_width,
                compact,
            )
            if not isinstance(scaled, QPixmap) or scaled.isNull():
                preview_text.setText("Preview could not be loaded")
                preview_text.setVisible(True)
                preview_meta.setVisible(False)
                preview_image.setVisible(False)
                preview_frame.setVisible(True)
                return
            preview_image.setPixmap(scaled)
            preview_image.setMinimumSize(scaled.size())
            preview_image.setMaximumSize(scaled.size())
            preview_image.setVisible(True)
            preview_text.setVisible(False)
            preview_meta.setText(
                f"Page {page + 1}/{page_count}  |  Smooth scroll  |  Edge scroll changes page  |  Zoom {int(round(zoom_factor * 100))}%"
            )
            preview_meta.setVisible(True)
            preview_state["page"] = int(page)
            preview_state["page_count"] = int(page_count)
            preview_state["zoom"] = float(zoom_factor)
            preview_state["target_width"] = int(target_width)
            preview_frame.setVisible(True)
            self._active_quick_look_frame = preview_frame
            scroll_area = preview_state.get("scroll_area")
            if isinstance(scroll_area, QScrollArea):
                try:
                    if previous_page != page:
                        scroll_area.verticalScrollBar().setValue(0)
                except Exception:
                    pass
            return
        preview_text.setText("Preview could not be loaded")
        preview_text.setVisible(True)
        preview_meta.setVisible(False)
        preview_image.setVisible(False)
        preview_frame.setVisible(True)

    def _scroll_quick_look_preview(
        self,
        step: int,
        item: Dict[str, Any],
        preview_frame: QFrame,
        preview_image: QLabel,
        preview_text: QLabel,
        preview_meta: QLabel,
        preview_state: Dict[str, Any],
    ) -> None:
        if not preview_frame.isVisible():
            return
        page_count = int(preview_state.get("page_count", 0))
        if page_count <= 1:
            return
        current_page = int(preview_state.get("page", 0))
        direction = int(step)
        self._show_quick_look_preview(
            item,
            preview_frame,
            preview_image,
            preview_text,
            preview_meta,
            preview_state,
            page_index=current_page + direction,
        )
        scroll_area = preview_state.get("scroll_area")
        if isinstance(scroll_area, QScrollArea):
            try:
                bar = scroll_area.verticalScrollBar()
                if direction < 0:
                    bar.setValue(bar.maximum())
                else:
                    bar.setValue(bar.minimum())
            except Exception:
                pass

    def _zoom_quick_look_preview(
        self,
        zoom_delta: float,
        item: Dict[str, Any],
        preview_frame: QFrame,
        preview_image: QLabel,
        preview_text: QLabel,
        preview_meta: QLabel,
        preview_state: Dict[str, Any],
    ) -> None:
        if not preview_frame.isVisible():
            return
        if not math.isfinite(float(zoom_delta)) or float(zoom_delta) <= 0.0:
            return
        current_zoom = max(0.55, min(3.5, float(preview_state.get("zoom", 1.0) or 1.0)))
        next_zoom = max(0.55, min(3.5, current_zoom * float(zoom_delta)))
        if abs(next_zoom - current_zoom) < 5e-3:
            return
        preview_state["zoom"] = float(round(next_zoom, 4))
        self._schedule_quick_look_preview_refresh(
            item,
            preview_frame,
            preview_image,
            preview_text,
            preview_meta,
            preview_state,
        )

    def _ensure_quick_look_window(self) -> None:
        if isinstance(self._quick_look_window, QDialog):
            return

        window = QDialog(self)
        window.setWindowTitle("Quick Look")
        window.setModal(False)
        window.resize(980, 760)
        window.setMinimumSize(760, 520)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        root = QVBoxLayout(window)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)
        prev_btn = QPushButton("Prev", window)
        prev_btn.setMinimumWidth(84)
        next_btn = QPushButton("Next", window)
        next_btn.setMinimumWidth(84)
        page_label = QLabel("Page 0/0", window)
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_label.setMinimumWidth(130)
        zoom_label = QLabel("100%", window)
        zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        zoom_label.setMinimumWidth(72)
        hint_label = QLabel("Scroll to pan · Ctrl/Pinch to zoom", window)
        hint_label.setProperty("themeRole", "metadata")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        control_row.addWidget(prev_btn)
        control_row.addWidget(next_btn)
        control_row.addWidget(page_label)
        control_row.addStretch(1)
        control_row.addWidget(hint_label, 0)
        control_row.addWidget(zoom_label, 0)
        root.addLayout(control_row)

        view = QuickLookGraphicsView(window)
        scene = QGraphicsScene(view)
        view.setScene(scene)
        pixmap_item = scene.addPixmap(QPixmap())
        pixmap_item.setVisible(False)
        pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        root.addWidget(view, 1)

        prev_btn.clicked.connect(lambda: self._step_quick_look_window_page(-1))
        next_btn.clicked.connect(lambda: self._step_quick_look_window_page(1))
        view.zoomRequested.connect(self._zoom_quick_look_window)

        self._style_card_action_button(prev_btn, Colors.BG_LIGHT)
        self._style_card_action_button(next_btn, Colors.BG_LIGHT)

        self._quick_look_window = window
        self._quick_look_window_view = view
        self._quick_look_window_scene = scene
        self._quick_look_window_pixmap_item = pixmap_item
        self._quick_look_window_prev_btn = prev_btn
        self._quick_look_window_next_btn = next_btn
        self._quick_look_window_page_label = page_label
        self._quick_look_window_zoom_label = zoom_label

    def _apply_quick_look_window_zoom_transform(self) -> None:
        view = self._quick_look_window_view
        state = self._quick_look_window_state
        if not isinstance(view, QuickLookGraphicsView):
            return
        zoom = max(0.5, min(3.5, float(state.get("zoom", 1.0) or 1.0)))
        view.resetTransform()
        view.scale(zoom, zoom)
        if isinstance(self._quick_look_window_zoom_label, QLabel):
            self._quick_look_window_zoom_label.setText(f"{int(round(zoom * 100.0))}%")

    def _refresh_quick_look_window_page(self) -> None:
        window = self._quick_look_window
        view = self._quick_look_window_view
        scene = self._quick_look_window_scene
        pixmap_item = self._quick_look_window_pixmap_item
        state = self._quick_look_window_state
        if (
            not isinstance(window, QDialog)
            or not isinstance(view, QuickLookGraphicsView)
            or not isinstance(scene, QGraphicsScene)
            or not isinstance(pixmap_item, QGraphicsPixmapItem)
        ):
            return
        item = state.get("item")
        if not isinstance(item, dict):
            return
        page_count = max(0, int(state.get("page_count", 0) or 0))
        page = max(0, min(max(0, page_count - 1), int(state.get("page", 0) or 0)))
        state["page"] = page
        pixmap = self._quick_look_preview_pixmap(item, page)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            pixmap_item.setVisible(True)
            pixmap_item.setPixmap(pixmap)
            scene.setSceneRect(0, 0, float(pixmap.width()), float(pixmap.height()))
        else:
            pixmap_item.setVisible(False)
            pixmap_item.setPixmap(QPixmap())
            scene.setSceneRect(QRectF())
        if isinstance(self._quick_look_window_page_label, QLabel):
            self._quick_look_window_page_label.setText(f"Page {page + 1}/{max(1, page_count)}")
        if isinstance(self._quick_look_window_prev_btn, QPushButton):
            self._quick_look_window_prev_btn.setEnabled(page > 0)
        if isinstance(self._quick_look_window_next_btn, QPushButton):
            self._quick_look_window_next_btn.setEnabled(page < (page_count - 1))
        self._apply_quick_look_window_zoom_transform()
        title_name = str(item.get("filename") or item.get("type_name") or "Document")
        window.setWindowTitle(f"Quick Look • {title_name}")

    def _open_quick_look_window(self, item: Dict[str, Any]) -> None:
        if not self._item_supports_quick_look(item):
            self.update_status("Quick look preview unavailable for this resource type")
            return
        page_count = self._quick_look_page_count(item)
        if page_count <= 0:
            self.update_status("Preview could not be loaded")
            return
        self._ensure_quick_look_window()
        window = self._quick_look_window
        if not isinstance(window, QDialog):
            return

        cache_key = self._quick_look_cache_key(item)
        state = self._quick_look_window_state if isinstance(self._quick_look_window_state, dict) else {}
        previous_key = str(state.get("cache_key", "") or "")
        page = int(state.get("page", 0) or 0) if previous_key == cache_key else 0
        zoom = float(state.get("zoom", 1.0) or 1.0) if previous_key == cache_key else 1.0
        self._quick_look_window_state = {
            "cache_key": cache_key,
            "item": dict(item),
            "page": max(0, min(max(0, int(page_count) - 1), int(page))),
            "page_count": int(page_count),
            "zoom": max(0.5, min(3.5, float(zoom))),
        }
        self._refresh_quick_look_window_page()
        window.show()
        window.raise_()
        window.activateWindow()

    def _step_quick_look_window_page(self, step: int) -> None:
        state = self._quick_look_window_state
        if not isinstance(state, dict):
            return
        page_count = max(0, int(state.get("page_count", 0) or 0))
        if page_count <= 1:
            return
        current_page = int(state.get("page", 0) or 0)
        next_page = max(0, min(page_count - 1, current_page + int(step)))
        if next_page == current_page:
            return
        state["page"] = next_page
        self._refresh_quick_look_window_page()

    def _zoom_quick_look_window(self, zoom_delta: float) -> None:
        if not math.isfinite(float(zoom_delta)) or float(zoom_delta) <= 0.0:
            return
        state = self._quick_look_window_state
        if not isinstance(state, dict):
            return
        current_zoom = max(0.5, min(3.5, float(state.get("zoom", 1.0) or 1.0)))
        next_zoom = max(0.5, min(3.5, current_zoom * float(zoom_delta)))
        if abs(next_zoom - current_zoom) < 2e-3:
            return
        state["zoom"] = float(next_zoom)
        view = self._quick_look_window_view
        if isinstance(view, QuickLookGraphicsView) and current_zoom > 1e-6:
            factor = float(next_zoom / current_zoom)
            view.scale(factor, factor)
            if isinstance(self._quick_look_window_zoom_label, QLabel):
                self._quick_look_window_zoom_label.setText(f"{int(round(next_zoom * 100.0))}%")
            return
        self._apply_quick_look_window_zoom_transform()

    def create_result_item(self, group: PaperGroup, resource: PaperResource, *, compact: bool = False) -> QFrame:
        item = group.to_result_item(resource)
        frame = DashboardCard(theme_role="resultCard")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(14, 12, 14, 12)
        frame_layout.setSpacing(10)
        frame_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        preview_supported = self._item_supports_quick_look(item)

        quick_btn = QPushButton("Quick Look")
        quick_btn.setToolTip("Quick look preview")
        self._style_card_action_button(quick_btn, Colors.BG_LIGHT)
        if compact:
            quick_btn.setToolTip("Open preview in a resizable window")
            quick_btn.setMinimumHeight(32)
            quick_btn.setMinimumWidth(94)
            quick_btn.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        if not preview_supported:
            quick_btn.setEnabled(False)
            quick_btn.setToolTip("Quick look preview is unavailable for this resource")

        exam_btn: Optional[QPushButton] = None
        if EXAM_MODE_AVAILABLE and item["type"] in ("QP", "P"):
            exam_btn = QPushButton("Start Exam")
            self._style_card_action_button(exam_btn, Colors.ACCENT_PURPLE)
            if compact:
                exam_btn.setMinimumHeight(32)
                exam_btn.setMinimumWidth(86)
                exam_btn.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
            resources_bundle = self._build_exam_mode_resource_bundle(group)
            exam_btn.clicked.connect(lambda _, i=item, r=resources_bundle: self.launch_exam_mode_for_item(i, paper_resources=r))

        open_btn = QPushButton("Open")
        self._style_card_action_button(open_btn, Colors.SECONDARY)
        if compact:
            open_btn.setMinimumHeight(32)
            open_btn.setMinimumWidth(86)
            open_btn.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        open_btn.clicked.connect(lambda _, i=item: self.open_papers([i]))

        download_btn = QPushButton("Download")
        self._style_card_action_button(download_btn, Colors.INFO)
        if compact:
            download_btn.setMinimumHeight(32)
            download_btn.setMinimumWidth(100)
            download_btn.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        download_btn.clicked.connect(lambda _, i=item: self.download_papers([i]))

        paper_code = QLabel(f"{item.get('subject_code', '')}/{item.get('component', '')}")
        paper_code.setProperty("themeRole", "paperCode")
        title = QLabel(f"{self._result_kind_badge(item)}  {item.get('type_name', 'Document')}")
        title.setFont(QFont("Arial", 12 if compact else 13, QFont.Weight.Black))
        session_label = self._series_display_label(str(item.get("series", "")))
        source_suffix = str(item.get("source") or "").strip()
        meta_parts = [f"{session_label} {item.get('year', '')}".strip(), f"Comp {item.get('component', '')}"]
        if source_suffix:
            meta_parts.append(source_suffix)
        metadata = QLabel(" | ".join([part for part in meta_parts if part]))
        metadata.setProperty("themeRole", "metadata")
        badges_label = QLabel(" ".join(self._result_signal_badges(group, item)))
        badges_label.setProperty("themeRole", "metadata")

        def _build_resource_tray() -> QHBoxLayout:
            tray = QHBoxLayout()
            tray.setContentsMargins(0, 0, 0, 0)
            tray.setSpacing(6)
            paper_stack_icon = QLabel("🗂")
            paper_stack_icon.setToolTip("Paper resource group")
            paper_stack_icon.setProperty("themeRole", "metadata")
            attachment_icon = QLabel("📎")
            attachment_icon.setToolTip("Additional resources available")
            attachment_icon.setProperty("themeRole", "metadata")
            tray.addWidget(paper_stack_icon, 0, Qt.AlignmentFlag.AlignLeft)
            tray.addWidget(attachment_icon, 0, Qt.AlignmentFlag.AlignLeft)
            tray.addStretch(1)
            return tray

        if compact:
            frame.setMinimumHeight(158)
            frame.setMaximumHeight(560)
            title.setWordWrap(True)
            metadata.setWordWrap(True)
            frame_layout.addWidget(paper_code, 0, Qt.AlignmentFlag.AlignLeft)
            frame_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
            frame_layout.addWidget(metadata, 0, Qt.AlignmentFlag.AlignLeft)
            frame_layout.addWidget(badges_label, 0, Qt.AlignmentFlag.AlignLeft)
            frame_layout.addLayout(_build_resource_tray())
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(8)
            actions.addWidget(quick_btn, 1)
            if isinstance(exam_btn, QPushButton):
                actions.addWidget(exam_btn, 1)
            actions.addWidget(open_btn, 1)
            actions.addWidget(download_btn, 1)
            frame_layout.addLayout(actions)
        else:
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(10)
            left_col = QVBoxLayout()
            left_col.setContentsMargins(0, 0, 0, 0)
            left_col.setSpacing(4)
            left_col.addWidget(paper_code, 0, Qt.AlignmentFlag.AlignLeft)
            left_col.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
            left_col.addWidget(metadata, 0, Qt.AlignmentFlag.AlignLeft)
            left_col.addWidget(badges_label, 0, Qt.AlignmentFlag.AlignLeft)
            left_col.addLayout(_build_resource_tray())
            top.addLayout(left_col, 1)
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(8)
            actions.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            actions.addWidget(quick_btn)
            if isinstance(exam_btn, QPushButton):
                actions.addWidget(exam_btn)
            actions.addWidget(open_btn)
            actions.addWidget(download_btn)
            top.addLayout(actions, 0)
            frame_layout.addLayout(top)

        shell = getattr(self, "_experimental_shell", None)
        if shell is not None:
            shell.prepare_result_card(frame, None if compact else top, actions, compact)
        quick_btn.clicked.connect(lambda _, it=dict(item): self._open_quick_look_window(it))
        return frame

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    @staticmethod
    def _resume_answer_has_content(value: Any) -> bool:
        if isinstance(value, dict):
            answer_type = str(value.get("type", "")).strip().lower()
            if answer_type == "drawing":
                return bool(str(value.get("image_path", "")).strip())
            if answer_type == "table":
                cells = value.get("cells")
                if isinstance(cells, dict):
                    for cell_value in cells.values():
                        if str(cell_value or "").strip():
                            return True
                    return bool(str(value.get("value", "")).strip())
                if isinstance(cells, list):
                    for cell in cells:
                        if isinstance(cell, dict) and str(cell.get("value", "")).strip():
                            return True
                return bool(str(value.get("value", "")).strip())
            if "value" in value:
                return bool(str(value.get("value", "")).strip())
            for nested in value.values():
                if PastPaperFinderGUI._resume_answer_has_content(nested):
                    return True
            return False
        if isinstance(value, (list, tuple, set)):
            return any(PastPaperFinderGUI._resume_answer_has_content(entry) for entry in value)
        return bool(str(value or "").strip())

    @staticmethod
    def _normalize_resume_question_id(raw_qid: Any) -> str:
        text = str(raw_qid or "").strip().lower()
        if not text:
            return ""
        text = re.sub(r"^question\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[^0-9a-z]", "", text)
        return text

    @staticmethod
    def _resume_question_number(raw_qid: str) -> str:
        match = re.match(r"(\d+)", str(raw_qid or ""))
        return str(match.group(1)) if match else ""

    def _answered_resume_question_ids(self, attempt: Dict[str, Any]) -> set[str]:
        answered_qids: set[str] = set()
        answers = attempt.get("answers")
        if isinstance(answers, dict):
            for raw_qid, payload in answers.items():
                if not self._resume_answer_has_content(payload):
                    continue
                normalized = self._normalize_resume_question_id(raw_qid)
                if normalized:
                    answered_qids.add(normalized)
        return answered_qids

    def _extract_attempt_question_marks(self, attempt: Dict[str, Any]) -> Dict[str, float]:
        marks_map: Dict[str, float] = {}
        marks = attempt.get("question_marks")
        if isinstance(marks, dict):
            for raw_qid, raw_marks in marks.items():
                qid = self._normalize_resume_question_id(raw_qid)
                if not qid:
                    continue
                try:
                    mark_value = float(raw_marks)
                except Exception:
                    continue
                if not math.isfinite(mark_value) or mark_value <= 0:
                    continue
                marks_map[qid] = mark_value
        if marks_map:
            return marks_map

        question_ids = attempt.get("question_ids")
        if isinstance(question_ids, list):
            for raw_qid in question_ids:
                qid = self._normalize_resume_question_id(raw_qid)
                if qid and qid not in marks_map:
                    marks_map[qid] = 1.0
        return marks_map

    def _extract_attempt_code_parts(self, attempt: Dict[str, Any]) -> Tuple[str, str, str]:
        candidates = [
            str(attempt.get("pdf_url", "")).strip(),
            str(attempt.get("paper_code", "")).strip(),
            self._format_attempt_question_paper_code(attempt),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            parsed = extract_paper_code(candidate)
            if not parsed:
                continue
            subject = str(parsed.get("subject", "")).strip()
            year_code = str(parsed.get("year_code", "")).strip().lower()
            paper = str(parsed.get("paper", "")).strip()
            if subject and year_code and paper:
                return subject, year_code, paper
        return "", "", ""

    def _extract_structure_marks(self, attempt: Dict[str, Any]) -> Dict[str, float]:
        subject, year_code, paper = self._extract_attempt_code_parts(attempt)
        if not (subject and year_code and paper):
            return {}
        try:
            structure = get_paper_structure(subject, paper, year_code)
        except Exception:
            structure = None
        if not isinstance(structure, dict):
            return {}
        try:
            question_ids = generate_question_ids_from_structure(structure)
            marks = calculate_marks_from_structure(structure, question_ids)
        except Exception:
            return {}

        marks_map: Dict[str, float] = {}
        if isinstance(marks, dict):
            for raw_qid, raw_marks in marks.items():
                qid = self._normalize_resume_question_id(raw_qid)
                if not qid:
                    continue
                try:
                    mark_value = float(raw_marks)
                except Exception:
                    continue
                if not math.isfinite(mark_value) or mark_value <= 0:
                    continue
                marks_map[qid] = mark_value
        return marks_map

    def _compute_resume_progress(self, attempt: Dict[str, Any]) -> Tuple[int, str]:
        answered_qids = self._answered_resume_question_ids(attempt)
        question_marks = self._extract_attempt_question_marks(attempt)
        if not question_marks:
            question_marks = self._extract_structure_marks(attempt)

        if question_marks:
            total_marks = sum(max(0.0, float(value)) for value in question_marks.values())
            if total_marks > 0:
                answered_marks = 0.0
                matched_qids: set[str] = set()
                for qid in answered_qids:
                    if qid in question_marks:
                        answered_marks += float(question_marks[qid])
                        matched_qids.add(qid)

                # Backward-compatibility for older snapshots with question-level IDs.
                if len(matched_qids) < len(answered_qids):
                    per_question_proxy: Dict[str, float] = {}
                    for qid, marks_value in question_marks.items():
                        q_number = self._resume_question_number(qid)
                        if not q_number:
                            continue
                        per_question_proxy[q_number] = max(
                            float(per_question_proxy.get(q_number, 0.0)),
                            float(marks_value),
                        )
                    used_questions: set[str] = set()
                    for qid in answered_qids:
                        if qid in matched_qids:
                            continue
                        q_number = self._resume_question_number(qid)
                        if not q_number or q_number in used_questions:
                            continue
                        proxy_marks = float(per_question_proxy.get(q_number, 0.0))
                        if proxy_marks <= 0:
                            continue
                        answered_marks += proxy_marks
                        used_questions.add(q_number)

                answered_marks = max(0.0, min(total_marks, answered_marks))
                ratio = float(answered_marks) / float(max(1.0, total_marks))
                percent = int(round(max(0.0, min(1.0, ratio)) * 100.0))
                return percent, f"{percent}% complete ({int(round(answered_marks))}/{int(round(total_marks))} marks)"

        inferred_total = 0
        answers = attempt.get("answers")
        if isinstance(answers, dict):
            inferred_total = max(inferred_total, len(answers))
        question_ids = attempt.get("question_ids")
        if isinstance(question_ids, list):
            inferred_total = max(inferred_total, len(question_ids))
        if inferred_total > 0:
            ratio = float(len(answered_qids)) / float(max(1, inferred_total))
            percent = int(round(max(0.0, min(1.0, ratio)) * 100.0))
            return percent, f"{percent}% complete (question estimate)"

        remaining = max(0, int(attempt.get("remaining_seconds", 0) or 0))
        duration_minutes = 0
        for key in ("duration_minutes", "duration", "exam_duration"):
            raw = attempt.get(key)
            try:
                parsed = int(raw)
            except Exception:
                parsed = 0
            if parsed > 0:
                duration_minutes = parsed
                break
        if duration_minutes <= 0:
            try:
                duration_minutes = int(
                    get_exam_duration(
                        str(attempt.get("subject_code", "")),
                        str(attempt.get("paper_num", "") or "1"),
                        str(attempt.get("year", "")),
                    )
                )
            except Exception:
                duration_minutes = 60
        total_seconds = max(60, duration_minutes * 60)
        ratio = 1.0 - (float(remaining) / float(total_seconds))
        percent = int(round(max(0.0, min(1.0, ratio)) * 100.0))
        return percent, f"{percent}% complete (timer estimate)"

    @staticmethod
    def _make_history_card_fully_clickable(card: QWidget) -> None:
        if not isinstance(card, QWidget):
            return
        for child in card.findChildren(QWidget):
            if child is card:
                continue
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            child.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @staticmethod
    def _history_subject_accent_color(subject_code: str) -> str:
        code = str(subject_code or "").strip()
        accent_map = {
            "0620": "#EC4899",  # Chemistry
            "9701": "#EC4899",
            "0625": "#3B82F6",  # Physics
            "9702": "#3B82F6",
            "0580": "#10B981",  # Maths
            "9709": "#10B981",
            "0610": "#A78BFA",  # Biology
            "9700": "#A78BFA",
        }
        return accent_map.get(code, "#22D3EE")

    def refresh_history(self):
        self.history_list.clear()
        shown = 0

        attempts = ExamAttemptManager.list_attempts()
        for attempt in attempts:
            subject_code = str(attempt.get("subject_code", "")).strip()
            if SubjectDatabase.get_exam_level(subject_code) != self.current_level:
                continue
            if not SubjectDatabase.is_searchable_subject(subject_code):
                continue
            attempt_key = str(attempt.get("attempt_key", "")).strip()
            if not attempt_key:
                continue

            subject_name = str(attempt.get("subject_name", "")).strip() or SubjectDatabase.get_subject_name(subject_code)
            question_paper_code = self._format_attempt_question_paper_code(attempt)
            started_label = self._format_attempt_saved_at(attempt.get("first_saved_at", "") or attempt.get("saved_at", ""))
            audio_timestamp = str(attempt.get("listening_audio_timestamp", "") or "").strip()
            listening_suffix = ""
            if bool(attempt.get("is_listening")) and audio_timestamp:
                listening_suffix = f" | Audio: {audio_timestamp}"
            row_item = QListWidgetItem()
            row_item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "entry_type": "resume_attempt",
                    "attempt_key": attempt_key,
                },
            )
            row_widget = DashboardCard(theme_role="historyCard", clickable=True)
            row_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row_widget.setMinimumHeight(104)
            row_shell = QHBoxLayout(row_widget)
            row_shell.setContentsMargins(0, 0, 0, 0)
            row_shell.setSpacing(0)
            accent = QFrame(row_widget)
            accent.setFixedWidth(2)
            accent_color = self._history_subject_accent_color(subject_code)
            accent.setStyleSheet(f"background-color: {accent_color}; border: none;")
            row_shell.addWidget(accent, 0)
            content = QWidget(row_widget)
            row_layout = QVBoxLayout(content)
            row_layout.setContentsMargins(10, 9, 10, 9)
            row_layout.setSpacing(6)
            row_shell.addWidget(content, 1)
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(8)
            title = QLabel(str(subject_name or "Saved Attempt"))
            title.setFont(QFont("Arial", 11, QFont.Weight.Black))
            title.setWordWrap(True)
            title_row.addWidget(title, 1)
            code = QLabel(question_paper_code)
            code.setProperty("themeRole", "paperCode")
            title_row.addWidget(code, 0, Qt.AlignmentFlag.AlignRight)
            row_layout.addLayout(title_row)
            details = QLabel(f"{subject_code} • Started {started_label}{listening_suffix}")
            details.setProperty("themeRole", "metadata")
            details.setWordWrap(True)
            row_layout.addWidget(details)
            progress_percent, progress_text = self._compute_resume_progress(attempt)
            progress_label = QLabel(f"{progress_percent}%")
            progress_label.setProperty("themeRole", "metadata")
            row_layout.addWidget(progress_label)
            progress_bar = QProgressBar(row_widget)
            progress_bar.setRange(0, 100)
            progress_bar.setValue(progress_percent)
            progress_bar.setFormat("")
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(8)
            row_layout.addWidget(progress_bar)
            self._make_history_card_fully_clickable(row_widget)
            row_widget.activated.connect(lambda key=attempt_key: self.continue_saved_exam_attempt(key))
            self._apply_history_item_size_hint(row_item, row_widget, 132)

            self.history_list.addItem(row_item)
            self.history_list.setItemWidget(row_item, row_widget)
            shown += 1

        dashboard = getattr(self, '_dashboard', None)
        if dashboard:
            from UI.study_dashboard import paper_title, attempt_subtitle
            for record in [r for r in dashboard.records if not r.get('resume_key')][:10]:
                if SubjectDatabase.get_exam_level(record.get('subject_code')) != self.current_level:
                    continue
                row_item = QListWidgetItem()
                row_item.setData(Qt.ItemDataRole.UserRole, {'entry_type': 'study_attempt', 'attempt': record})
                card = DashboardCard(theme_role='historyCard', clickable=True)
                row = QVBoxLayout(card)
                title = QLabel(paper_title(record)); title.setWordWrap(True); title.setProperty('ppsNoTranslation', True)
                row.addWidget(title)
                details = QLabel(attempt_subtitle(record)); details.setWordWrap(True); row.addWidget(details)
                card.activated.connect(lambda record=record: dashboard.open_attempt(record))
                self._apply_history_item_size_hint(row_item, card, 84)
                self.history_list.addItem(row_item); self.history_list.setItemWidget(row_item, card)
                shown += 1

        history = HistoryManager.get_history()

        for item in history[:5]:
            if SubjectDatabase.get_exam_level(item['subject_code']) == self.current_level:
                subject_code = str(item.get("subject_code", "")).strip()
                if not SubjectDatabase.is_searchable_subject(subject_code):
                    continue
                canonical_subject_name = SubjectDatabase.get_subject_name(subject_code) or str(item.get("subject_name", "")).strip()
                list_item = QListWidgetItem()
                list_item.setData(
                    Qt.ItemDataRole.UserRole,
                    {
                        "entry_type": "search_history",
                        "search_history": dict(item),
                    },
                )
                self.history_list.addItem(list_item)
                card = DashboardCard(theme_role="historyCard", clickable=True)
                card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                card.setMinimumHeight(108)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(14, 12, 14, 12)
                card_layout.setSpacing(8)
                title = QLabel(canonical_subject_name)
                title.setFont(QFont("Arial", 11, QFont.Weight.Black))
                title.setWordWrap(True)
                title_row = QHBoxLayout()
                title_row.setContentsMargins(0, 0, 0, 0)
                title_row.setSpacing(8)
                title_row.addWidget(title, 1)
                code_badge = QLabel(f"{subject_code}/{item['component']}")
                code_badge.setProperty("themeRole", "paperCode")
                title_row.addWidget(code_badge, 0, Qt.AlignmentFlag.AlignRight)
                card_layout.addLayout(title_row)
                meta = QLabel(f"{item['series']} {item['year']} | Component {item['component']}")
                meta.setProperty("themeRole", "metadata")
                meta.setWordWrap(True)
                card_layout.addWidget(meta)
                self._make_history_card_fully_clickable(card)
                card.activated.connect(lambda row=list_item: self.on_history_clicked(row))
                self._apply_history_item_size_hint(list_item, card, 108)
                self.history_list.setItemWidget(list_item, card)
                shown += 1

        if shown == 0:
            self.history_list.addItem(QListWidgetItem("No recent searches"))

        hint_label = getattr(self, "history_scroll_hint", None)
        if isinstance(hint_label, QLabel):
            bar = self.history_list.verticalScrollBar() if isinstance(self.history_list, QListWidget) else None
            max_value = int(bar.maximum()) if bar is not None else 0
            hint_label.setVisible(shown > 0 and max_value > 0)
        self._resize_history_item_widths()
        shell = getattr(self, "_experimental_shell", None)
        if shell is not None:
            shell.restyle_history()
        if dashboard and not dashboard._updating_history:
            dashboard.refresh()

        self._refresh_text_interaction_support()

    def _on_history_context_menu(self, pos) -> None:
        item = self.history_list.itemAt(pos)
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        dashboard = getattr(self, '_dashboard', None)
        entry_type = str(payload.get('entry_type', '')).strip()
        if dashboard and entry_type in ('study_attempt', 'resume_attempt'):
            record = payload.get('attempt') or next((r for r in dashboard.records
                if r.get('resume_key') == payload.get('attempt_key')), None)
            if record:
                from UI.localization import tr
                menu = QMenu(self.history_list)
                action = menu.addAction(tr('View paper history'))
                if menu.exec(self.history_list.viewport().mapToGlobal(pos)) == action:
                    dashboard.open_paper(record)
            return
        if entry_type != "search_history":
            return
        search_history = payload.get("search_history")
        if not isinstance(search_history, dict):
            return
        menu = QMenu(self.history_list)
        delete_action = menu.addAction("Delete from history")
        chosen = menu.exec(self.history_list.viewport().mapToGlobal(pos))
        if chosen is not delete_action:
            return
        if not HistoryManager.delete_history_entry(search_history):
            show_warning(self, "History", "Could not delete this history item.")
            return
        self.refresh_history()

    @staticmethod
    def _format_attempt_question_paper_code(attempt: Dict[str, Any]) -> str:
        if not isinstance(attempt, dict):
            return "question_paper"

        url = str(attempt.get("pdf_url", "")).strip()
        parsed = extract_paper_code(url)
        if parsed:
            subject = str(parsed.get("subject", "")).strip()
            year_code = str(parsed.get("year_code", "")).strip().lower()
            paper = str(parsed.get("paper", "")).strip()
            if subject and year_code and paper:
                return f"{subject}_{year_code}_qp_{paper}"

        paper_code = str(attempt.get("paper_code", "")).strip()
        if paper_code and not re.fullmatch(r"[a-f0-9]{32,64}", paper_code.lower()):
            if re.fullmatch(r"\d{4}_[a-z]\d{2}_qp_\d{2}", paper_code, flags=re.IGNORECASE):
                return paper_code.lower()
            if re.fullmatch(r"\d{4}_qp_\d{1,2}", paper_code, flags=re.IGNORECASE):
                return paper_code.lower()
            match = re.search(r"(\d{4}_[a-z]\d{2}_qp_\d{2})", paper_code, flags=re.IGNORECASE)
            if match:
                return match.group(1).lower()

        subject_code = str(attempt.get("subject_code", "")).strip()
        paper_num = str(attempt.get("paper_num", "")).strip()
        if len(paper_num) == 1 and paper_num.isdigit():
            paper_num = f"{paper_num}0"
        return f"{subject_code}_qp_{paper_num or '00'}"

    @staticmethod
    def _format_remaining_time(seconds_raw: Any) -> str:
        try:
            total = max(0, int(seconds_raw))
        except Exception:
            total = 0
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        if hours > 0:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_attempt_saved_at(saved_at_raw: Any) -> str:
        text = str(saved_at_raw or "").strip()
        if not text:
            return "Unknown date"

        candidates = [text]
        if text.endswith("Z"):
            candidates.append(f"{text[:-1]}+00:00")

        parsed: Optional[datetime] = None
        for candidate in candidates:
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except Exception:
                continue

        if parsed is None:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except Exception:
                    continue

        if parsed is None:
            return text
        return parsed.strftime("%b %d, %Y %I:%M %p")

    def continue_saved_exam_attempt(self, attempt_key: str, *, flagged_question=None) -> None:
        key = str(attempt_key or "").strip()
        if not key:
            return

        attempt = ExamAttemptManager.get_attempt(key)
        if not isinstance(attempt, dict):
            ExamAttemptManager.delete_attempt(key)
            self.refresh_history()
            show_warning(self, "Resume Unavailable", "Saved exam attempt was not found.")
            return

        try:
            remaining_seconds = int(attempt.get("remaining_seconds", 0))
        except Exception:
            remaining_seconds = 0
        workspace = attempt.get('workspace') or {}
        practice = isinstance(workspace, dict) and workspace.get('mode') == 'practice'
        if remaining_seconds <= 0 and not practice:
            ExamAttemptManager.delete_attempt(key)
            self.refresh_history()
            show_warning(self, "Resume Unavailable", "Saved exam timer expired and was removed.")
            return

        subject_code = str(attempt.get("subject_code", "")).strip()
        subject_name = str(attempt.get("subject_name", "")).strip() or SubjectDatabase.get_subject_name(subject_code)
        paper_num = str(attempt.get("paper_num", "")).strip() or "1"
        year = str(attempt.get("year", "")).strip()
        series = str(attempt.get("series", "")).strip().upper()
        pdf_url = str(attempt.get("pdf_url", "")).strip()
        paper_resources = attempt.get("paper_resources")
        if not isinstance(paper_resources, dict):
            paper_resources = None
        if not (subject_code and year and pdf_url):
            ExamAttemptManager.delete_attempt(key)
            self.refresh_history()
            show_warning(self, "Resume Unavailable", "Saved exam attempt was invalid and has been removed.")
            return

        item = {
            "subject_code": subject_code,
            "subject": subject_name,
            "year": year,
            "series": series,
            "url": pdf_url,
            "component": paper_num,
        }
        if flagged_question:
            attempt = dict(attempt)
            attempt['workspace'] = {**(attempt.get('workspace') or {}), 'active_question': str(flagged_question)}
        self.launch_exam_mode_for_item(
            item,
            resume_snapshot=attempt,
            paper_num_override=paper_num,
            paper_resources=paper_resources,
        )

    def on_history_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return

        entry_type = str(data.get("entry_type", "")).strip().lower()
        if entry_type == 'study_attempt' and getattr(self, '_dashboard', None):
            self._dashboard.open_attempt(data['attempt'])
            return
        should_launch_search = False
        if entry_type == "resume_attempt":
            self.continue_saved_exam_attempt(str(data.get("attempt_key", "")).strip())
            return
        if entry_type == "search_history":
            payload = data.get("search_history")
            if not isinstance(payload, dict):
                return
            data = payload
            should_launch_search = True

        self.subject_code = str(data.get("subject_code", "")).strip()
        if not SubjectDatabase.is_searchable_subject(self.subject_code):
            show_warning(self, "Unsupported Subject", "This subject is not available in the active catalog.")
            return
        canonical_subject_name = SubjectDatabase.get_subject_name(self.subject_code) or str(data.get("subject_name", "")).strip()
        self._apply_subject_selection(self.subject_code, canonical_subject_name, clear_entry=True)

        selected_series = str(data.get('series', '')).strip().upper()
        for s, cb in self.series_vars.items():
            cb.setChecked(cb.isEnabled() and s == selected_series)
        if not any(cb.isChecked() for cb in self.series_vars.values() if cb.isEnabled()):
            for series_code in ("MJ", "ON", "FM"):
                cb = self.series_vars.get(series_code)
                if isinstance(cb, QCheckBox) and cb.isEnabled():
                    cb.setChecked(True)
                    break
        self.update_variant_lock_ui([s for s, cb in self.series_vars.items() if cb.isChecked()], None)

        self.component_entry.setText(data['component'])
        self.year_entry.setText(data['year'])
        if should_launch_search:
            self._launch_history_search_preemptively()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def open_papers(self, items):
        for item in items:
            try:
                target = str(
                    item.get("direct_url")
                    or item.get("download_url")
                    or item.get("url")
                    or item.get("open_url")
                    or ""
                ).strip()
                if not target:
                    continue
                webbrowser.open(target)
            except Exception as e:
                show_error(self, "Error", f"Could not open browser: {e}")

    def download_papers(self, items):
        rows = list(items or [])
        if not rows:
            return
        desktop_root = self._desktop_download_dir()
        parent_directory = QFileDialog.getExistingDirectory(
            self,
            "Choose Parent Download Folder",
            str(desktop_root),
        )
        if not parent_directory:
            return
        target_directory = self._create_download_batch_directory(str(parent_directory), rows)
        if not target_directory:
            return

        saved_paths: List[str] = []
        failed_items: List[Tuple[str, str]] = []
        for item in rows:
            ok, saved_path, error_message = self.download_single_paper(
                item,
                target_directory=target_directory,
                show_success_dialog=False,
                show_error_dialog=False,
            )
            if ok and saved_path:
                saved_paths.append(saved_path)
            else:
                label = str(item.get("filename", "") or item.get("type_name", "") or "Unknown File").strip()
                failed_items.append((label, str(error_message or "Unknown error").strip()))

        if not saved_paths:
            show_error(self, "Download Failed", "No files were downloaded.")
            return

        target_abs = os.path.abspath(target_directory)
        if len(saved_paths) == 1:
            show_download_complete_dialog(
                self,
                "Download Complete",
                os.path.abspath(saved_paths[0]),
                message_prefix="Saved to:",
            )
        else:
            show_info(
                self,
                "Downloads Complete",
                f"Downloaded {len(saved_paths)} files to:\n{target_abs}",
            )

        if failed_items:
            preview_rows = failed_items[:5]
            details = "\n".join(f"- {name}: {message}" for name, message in preview_rows)
            extra_count = len(failed_items) - len(preview_rows)
            extra = f"\n- ...and {extra_count} more." if extra_count > 0 else ""
            show_warning(
                self,
                "Some Downloads Failed",
                f"{len(failed_items)} file(s) failed:\n{details}{extra}",
            )

    def _desktop_download_dir(self) -> str:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if desktop and os.path.isdir(desktop):
            return desktop
        home = os.path.expanduser("~")
        fallback = os.path.join(home, "Desktop")
        if os.path.isdir(fallback):
            return fallback
        return home

    def _next_available_path(self, directory: str, filename: str) -> str:
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(filename)
        index = 1
        while True:
            candidate = os.path.join(directory, f"{stem} ({index}){ext}")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _next_available_directory(self, directory: str) -> str:
        if not os.path.exists(directory):
            return directory
        index = 1
        while True:
            candidate = f"{directory} ({index})"
            if not os.path.exists(candidate):
                return candidate
            index += 1

    @staticmethod
    def _sanitize_folder_segment(text: str, fallback: str = "Past Paper") -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = "".join(ch for ch in cleaned if ch not in '<>:"/\\|?*')
        cleaned = cleaned.strip(" .")
        if not cleaned:
            cleaned = str(fallback or "Past Paper")
        return cleaned[:120]

    def _download_subject_name(self, items: List[Dict[str, Any]]) -> str:
        for item in items:
            subject_name = str(item.get("subject") or item.get("subject_name") or "").strip()
            if subject_name:
                return subject_name
            subject_code = str(item.get("subject_code") or "").strip()
            if subject_code:
                resolved = str(SubjectDatabase.get_subject_name(subject_code) or "").strip()
                if resolved:
                    return resolved
                return subject_code
        if str(self.subject_name or "").strip():
            return str(self.subject_name).strip()
        if str(self.subject_code or "").strip():
            return str(self.subject_code).strip()
        return "Past Paper"

    @staticmethod
    def _resource_token_for_folder(item: Dict[str, Any]) -> str:
        raw = str(item.get("resource_kind") or item.get("type") or "").strip().upper()
        normalized = {
            "QP": "qp",
            "SP_QP": "qp",
            "MS": "ms",
            "SP_MS": "ms",
            "GT": "gt",
            "ER": "er",
            "IN": "in",
            "SF": "sf",
            "AU": "au",
            "TN": "tn",
            "MAP": "map",
        }.get(raw, raw.lower())
        return normalized or "qp"

    def _infer_past_paper_code(self, item: Dict[str, Any]) -> str:
        candidates = [
            str(item.get("filename") or "").strip(),
            str(item.get("download_url") or "").strip(),
            str(item.get("direct_url") or "").strip(),
            str(item.get("url") or "").strip(),
        ]

        for candidate in candidates:
            if not candidate:
                continue
            parsed = extract_paper_code(candidate)
            if parsed:
                subject = str(parsed.get("subject") or "").strip()
                year_code = str(parsed.get("year_code") or "").strip().lower()
                paper = str(parsed.get("paper") or "").strip()
                if subject and year_code and paper:
                    return f"{subject}_{year_code}_qp_{paper}"

            stem = os.path.splitext(os.path.basename(urlparse(candidate).path or candidate))[0]
            match = re.search(r"(\d{4}_[a-z]\d{2}_[a-z]+(?:_[a-z]+)?_\d{1,2})", stem, flags=re.IGNORECASE)
            if match:
                return str(match.group(1)).lower()

        subject_code = str(item.get("subject_code") or "").strip()
        year = str(item.get("year") or "").strip()
        component = str(item.get("component") or "").strip()
        series = str(item.get("series") or "").strip().upper()
        yy = year[-2:] if len(year) >= 2 and year[-2:].isdigit() else ""
        series_code = {"MJ": "s", "ON": "w", "FM": "m", "SP": "y"}.get(series, "")
        token = self._resource_token_for_folder(item)
        if subject_code and yy and series_code and component:
            return f"{subject_code}_{series_code}{yy}_{token}_{component}"

        return "past_paper"

    def _download_folder_name(self, items: List[Dict[str, Any]]) -> str:
        subject_name = self._sanitize_folder_segment(self._download_subject_name(items), fallback="Past Paper")
        paper_code = "past_paper"
        for item in items:
            candidate = self._sanitize_folder_segment(self._infer_past_paper_code(item), fallback="past_paper")
            if candidate:
                paper_code = candidate
                break
        date_downloaded = datetime.now().strftime("%Y-%m-%d")
        return self._sanitize_folder_segment(
            f"{subject_name} {paper_code} {date_downloaded}",
            fallback=f"Past Paper {date_downloaded}",
        )

    def _create_download_batch_directory(self, parent_directory: str, items: List[Dict[str, Any]]) -> str:
        base_parent = str(parent_directory or "").strip()
        if not base_parent:
            return ""
        try:
            os.makedirs(base_parent, exist_ok=True)
            target = os.path.join(base_parent, self._download_folder_name(items))
            target = self._next_available_directory(target)
            os.makedirs(target, exist_ok=False)
            return target
        except Exception as exc:
            show_error(self, "Download Error", f"Could not create download folder: {exc}")
            return ""

    def download_single_paper(
        self,
        item,
        target_directory: Optional[str] = None,
        *,
        show_success_dialog: bool = True,
        show_error_dialog: bool = True,
    ) -> Tuple[bool, str, str]:
        filename = str(item.get('filename', '')).strip()
        safe_filename = sanitize_filename(filename)
        if "." not in os.path.basename(safe_filename):
            ext = str(item.get("extension") or "").strip().lower().lstrip(".")
            if not ext:
                download_candidate = str(item.get("download_url") or item.get("url") or "").strip()
                ext = os.path.splitext(urlparse(download_candidate).path)[1].lower().lstrip(".")
            if not ext:
                ext = "pdf"
            safe_filename = f"{safe_filename}.{ext}"
        active_target_directory = str(target_directory or "").strip()
        if not active_target_directory:
            desktop_root = self._desktop_download_dir()
            parent_directory = QFileDialog.getExistingDirectory(
                self,
                "Choose Parent Download Folder",
                str(desktop_root),
            )
            if not parent_directory:
                return False, "", "Download cancelled"
            active_target_directory = self._create_download_batch_directory(str(parent_directory), [item])
            if not active_target_directory:
                return False, "", "Could not prepare destination folder"
        try:
            os.makedirs(active_target_directory, exist_ok=True)
        except Exception as exc:
            if show_error_dialog:
                show_error(self, "Download Error", f"Could not access destination folder: {exc}")
            return False, "", f"Could not access destination folder: {exc}"

        chosen_path = str(self._next_available_path(active_target_directory, safe_filename))
        if not chosen_path:
            return False, "", "No destination path selected"

        url = str(item.get("download_url") or item.get("direct_url") or item.get("url") or "").strip()
        if not url:
            message = "No downloadable URL was found for this item."
            if show_error_dialog:
                show_error(self, "Download Error", message)
            return False, "", message

        try:
            download_file(url, chosen_path, expected_extension=os.path.splitext(chosen_path)[1])
            item['downloaded'] = True
            if show_success_dialog:
                show_download_complete_dialog(self, "Download Complete", os.path.abspath(chosen_path), message_prefix="Saved to:")
            return True, chosen_path, ""
        except (OSError, ValueError, requests.RequestException) as exc:
            if show_error_dialog:
                show_error(self, "Download Error", str(exc))
            return False, "", str(exc)

    def open_user_documentation(self) -> None:
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

    def _settings_theme_names(self) -> List[str]:
        return list(get_theme_manager().theme_names())

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

    def _current_ai_values(self, *, reload_from_env: bool = False) -> tuple[str, str, str]:
        if reload_from_env:
            self.groq_api_key = load_groq_api_key()
            self.groq_text_model = load_groq_text_model()
            self.groq_vision_model = load_groq_vision_model()
        return (
            str(self.groq_api_key or ""),
            str(self.groq_text_model or ""),
            str(self.groq_vision_model or ""),
        )

    def _refresh_ai_values_from_env(self) -> tuple[str, str, str]:
        return self._current_ai_values(reload_from_env=True)

    def _save_ai_settings(
        self,
        api_key: str,
        text_model: str,
        vision_model: str,
        *,
        show_feedback: bool = True,
    ) -> bool:
        saved = save_groq_settings(
            api_key=api_key.strip() if str(api_key or "").strip() else None,
            text_model=text_model.strip() if str(text_model or "").strip() else None,
            vision_model=vision_model.strip() if str(vision_model or "").strip() else None,
        )
        if saved:
            self.groq_api_key = load_groq_api_key()
            self.groq_text_model = load_groq_text_model()
            self.groq_vision_model = load_groq_vision_model()
            self._reset_ai_config_cache()
            self._sync_settings_window_state()
            if show_feedback:
                show_info(self, "Saved", "Groq settings saved and applied for this session.")
            return True
        if show_feedback:
            show_error(self, "Error", "Could not save Groq settings.")
        return False

    def _ensure_settings_window(self) -> None:
        existing = self.__dict__.get("_settings_window")
        if existing is not None:
            return
        window = FloatingSettingsWindow(
            self,
            on_theme_selected=self.on_theme_changed_by_user,
            on_font_selected=self.on_font_changed_by_user,
            on_sound_toggled=self.on_sound_toggled,
            on_system_accent_toggled=self.on_system_accent_toggled,
            on_answer_panel_position_changed=self.on_answer_panel_position_changed,
            on_random_theme_toggled=self.on_random_theme_toggled,
            on_preference_toggled=self.on_preference_toggled,
            on_open_docs=self.open_user_documentation,
            on_save_ai=self._save_ai_settings,
            on_refresh_ai=self._refresh_ai_values_from_env,
            on_delete_theme=self._delete_custom_theme_by_user,
        )
        window.setWindowTitle("Settings")
        self._settings_window = window
        self._sync_settings_window_state()

    def _show_settings_window(self) -> None:
        self._ensure_settings_window()
        self._available_ui_fonts = discover_available_ui_fonts()
        window = self.__dict__.get("_settings_window")
        if not window:
            return
        was_visible = bool(window.isVisible())
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
            "Enable UI sounds and easter egg audio.",
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
        window.set_random_theme_enabled(ConfigManager.get_random_theme_enabled())
        window.set_theme_names(self._settings_theme_names())
        window.set_selected_theme(self._current_theme_name())
        window.set_ai_values(*self._current_ai_values())
        if window.isVisible():
            window.apply_runtime_theme()


    def _schedule_results_theme_refresh(self) -> None:
        self._results_theme_refresh_scheduled = True
        timer = getattr(self, "_results_theme_refresh_timer", None)
        if isinstance(timer, QTimer):
            timer.start()
            return
        QTimer.singleShot(0, self._flush_results_theme_refresh)

    def _flush_results_theme_refresh(self) -> None:
        self._results_theme_refresh_scheduled = False
        dashboard = getattr(self, '_dashboard', None)
        if dashboard and dashboard.stack.currentWidget() is dashboard.home:
            return
        if self._results_skeleton_active:
            self._tick_results_skeleton_shimmer()
            return
        if self.search_results:
            self.display_results(list(self.search_results), record_history=False)
            return
        self._show_results_empty_state(getattr(self, "_empty_state_message", "Try adjusting your filters"))

    def open_all_results(self):
        items = self._flatten_group_items(include_resources=True)
        if items:
            self.open_papers(items)

    def download_all_results(self):
        items = self._flatten_group_items(include_resources=True)
        if items:
            self.download_papers(items)

    @staticmethod
    def _extract_paper_num_from_item(item: Dict[str, Any]) -> str:
        component = str(item.get("component", "")).strip()
        if len(component) >= 2 and component[0].isdigit():
            return component[0]
        if component:
            return component
        return "1"

    @staticmethod
    def _extract_variant_from_component(component: Any, locked_variant: Optional[str] = None) -> str:
        locked = str(locked_variant or "").strip()
        if locked in {"1", "2", "3"}:
            return locked
        digits = "".join(ch for ch in str(component or "") if ch.isdigit())
        if len(digits) >= 2:
            return digits[1]
        return ""

    def _format_standalone_exam_candidate_label(
        self,
        item: Dict[str, Any],
        paper_num: str,
        variant: str,
    ) -> str:
        subject_name = str(item.get("subject", "")).strip() or self.subject_name or "Selected Subject"
        session_code = str(item.get("series", "")).strip().upper()
        session_label = self._series_display_label(session_code)
        year = str(item.get("year", "")).strip()
        component = str(item.get("component", "")).strip()
        parts = [
            part
            for part in [
                f"{session_label} {year}".strip(),
                f"Paper {paper_num}" if paper_num else "",
                f"Variant {variant}" if variant else "",
                f"Comp {component}" if component else "",
            ]
            if part
        ]
        if not parts:
            return subject_name
        return f"{subject_name} | " + " | ".join(parts)

    def _collect_standalone_exam_candidates(self) -> List[ExamModeLaunchCandidate]:
        candidates: List[ExamModeLaunchCandidate] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for group in self.search_results:
            if not isinstance(group, PaperGroup):
                continue
            qp_resource = group.primary_docs.get("QP") or group.primary_docs.get("SP_QP")
            if qp_resource is None:
                continue
            item = group.to_result_item(qp_resource)
            year = str(item.get("year", "")).strip()
            series = str(item.get("series", "")).strip().upper()
            component = str(item.get("component", "")).strip()
            dedupe_key = (year, series, component)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            paper_num = self._extract_paper_num_from_item(item)
            variant = self._extract_variant_from_component(component, str(item.get("locked_variant", "")).strip())
            label = self._format_standalone_exam_candidate_label(item, paper_num, variant)
            candidates.append(
                ExamModeLaunchCandidate(
                    item=item,
                    paper_resources=self._build_exam_mode_resource_bundle(group),
                    label=label,
                    year=year,
                    series=series,
                    paper_num=paper_num,
                    variant=variant,
                )
            )
        return candidates

    @staticmethod
    def _requires_standalone_exam_disambiguation(candidates: List[ExamModeLaunchCandidate]) -> bool:
        if len(candidates) <= 1:
            return False

        years = {candidate.year for candidate in candidates if candidate.year}
        series = {candidate.series for candidate in candidates if candidate.series}
        papers = {candidate.paper_num for candidate in candidates if candidate.paper_num}
        variants = {candidate.variant for candidate in candidates if candidate.variant}
        has_multiple_dimensions = (
            len(years) > 1
            or len(series) > 1
            or len(papers) > 1
            or len(variants) > 1
        )
        if has_multiple_dimensions:
            return True
        # Multiple candidates can still exist even if one dimension token is missing.
        return len(candidates) > 1

    def _prompt_standalone_exam_selection(
        self,
        candidates: List[ExamModeLaunchCandidate],
    ) -> Optional[ExamModeLaunchCandidate]:
        dialog = SelectionDialog(candidates, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_candidate()

    def _should_gate_exam_mode_preflight(self, subject_code: str, paper_num: str, year: Any) -> bool:
        exam_year = infer_exam_year(str(year), fallback_year=2026)
        decision = resolve_mode(str(subject_code), str(paper_num), exam_year=exam_year)
        return decision.mode in {"WRITTEN_ONLY", "MIXED"}

    def _show_ai_probe_reply(self, title_text: str, reply: str):
        dialog = QDialog(self)
        dialog.setWindowTitle("AI Linked")
        dialog.setModal(True)
        dialog.setFixedSize(520, 180)

        layout = QVBoxLayout(dialog)
        title = QLabel(title_text)
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        body = QLabel(reply)
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body, 1)

        QTimer.singleShot(2000, dialog.accept)
        dialog.exec()

    @staticmethod
    def _is_quota_or_rate_error(message: str) -> bool:
        text = str(message or "").lower()
        if not text:
            return False
        hints = (
            "429",
            "resource_exhausted",
            "quota",
            "rate limit",
            "insufficient_quota",
            "retrydelay",
        )
        return any(h in text for h in hints)

    @staticmethod
    def _compact_probe_error(error_text: str) -> str:
        raw = str(error_text or "").strip()
        if not raw:
            return "Groq preflight failed."

        if PastPaperFinderGUI._is_quota_or_rate_error(raw):
            return "Groq returned rate-limit/quota style errors."

        lowered = raw.lower()
        if "timeout" in lowered or "timed out" in lowered:
            return "Groq probe timed out."
        if "connection" in lowered or "network" in lowered:
            return "Groq network/connectivity error during probe."

        # Keep payloads readable and avoid dumping large JSON blobs in modal dialogs.
        compact = re.sub(r"\s+", " ", raw)
        return f"Groq probe failed: {compact[:180]}{'...' if len(compact) > 180 else ''}"

    @staticmethod
    def _format_probe_attempt_summary(
        attempt_counts: Dict[str, int],
        model_errors: Dict[str, str],
    ) -> str:
        if not attempt_counts:
            return "AI has not linked successfully."

        lines: List[str] = []
        for model_name, count_raw in attempt_counts.items():
            count = int(count_raw or 0)
            if count <= 0:
                continue
            reason = model_errors.get(model_name, "probe failed")
            lines.append(f"{model_name} (attempts: {count}) -> {reason}")

        summary = " | ".join(lines).strip()
        if not summary:
            summary = "AI has not linked successfully."
        if len(summary) > 800:
            return summary[:800] + "..."
        return summary

    @staticmethod
    def _with_groq_setup(message: str) -> str:
        base = str(message or "").strip()
        return f"{base}\n\n{groq_setup_instructions_plain()}".strip()

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

    def _run_exam_mode_ai_preflight(self, item: Dict[str, Any], paper_num: str) -> bool:
        _ = item
        _ = paper_num
        self._last_ai_preflight_error = ""

        if not is_groq_configured():
            self._last_ai_preflight_error = groq_missing_warning_message(detailed=True)
            return False

        deadline = time.monotonic() + float(self.AI_PREFLIGHT_TIMEOUT_SEC)
        loading = LoadingDialog(self, "Linking AI...", "Connecting to Groq...")
        loading.show()

        try:
            cfg = get_ai_config()
            valid, validation_error = cfg.validate()
            if not valid:
                self._last_ai_preflight_error = validation_error or "Invalid Groq configuration."
                return False

            self.groq_api_key = cfg.api_key
            self.groq_text_model = cfg.text_model
            self.groq_vision_model = cfg.vision_model
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._last_ai_preflight_error = "Groq preflight timed out."
                return False

            loading.update_message("Checking Groq API...")
            probe = run_io(send_prompt_with_ai, title="Checking AI connection…",
                prompt=self.AI_PREFLIGHT_PROMPT,
                system_prompt="Reply with exactly one word: hello",
                max_tokens=8,
                temperature=0.0,
                request_timeout=min(8.0, max(1.0, remaining)),
            )
            if not probe.ok:
                compact_error = self._compact_probe_error(probe.error or "Unknown Groq probe failure.")
                self._last_ai_preflight_error = self._with_groq_setup(compact_error)
                return False

            title = "Groq connected"
            message = f"Ready with text model: {cfg.text_model}"
            loading.close()
            self._show_ai_probe_reply(title, message)
            return True
        finally:
            try:
                loading.close()
            except Exception:
                pass

    def _launch_exam_mode_for_item_impl(
        self,
        item,
        resume_snapshot: Optional[Dict[str, Any]] = None,
        paper_num_override: Optional[str] = None,
        paper_resources: Optional[Dict[str, Dict[str, str]]] = None,
        session_mode_override: Optional[str] = None,
    ):
        launcher = _resolve_exam_mode_launcher()
        if launcher is None:
            detail = (
                f"\n\nImport error: {_EXAM_MODE_IMPORT_ERROR}"
                if _EXAM_MODE_IMPORT_ERROR
                else ""
            )
            show_error(
                self,
                "Exam Mode Unavailable",
                "Exam mode module is unavailable. Make sure exam_mode.py is present and dependencies are installed."
                + detail,
            )
            return

        launched_window = None
        try:
            paper_num = str(paper_num_override).strip() if paper_num_override else self._extract_paper_num_from_item(item)
            manual_grading_only = False
            manual_grading_only_reason = ""
            if self._should_gate_exam_mode_preflight(item['subject_code'], paper_num, item.get('year')):
                linked = self._run_exam_mode_ai_preflight(item, paper_num)
                if not linked:
                    manual_grading_only = True
                    manual_grading_only_reason = self._last_ai_preflight_error or "AI has not linked successfully."
                    show_warning(
                        self,
                        "AI Unavailable",
                        (
                            f"{manual_grading_only_reason}\n\n"
                            "Exam mode will open with Manual Grading only."
                        ),
                    )

            launched_window = launcher(
                parent=self,
                subject_code=item['subject_code'],
                subject_name=item['subject'],
                paper_num=paper_num,
                year=item['year'],
                series=item.get('series'),
                pdf_url=item.get('direct_url') or item.get('url'),
                resume_snapshot=resume_snapshot,
                paper_resources=paper_resources,
                manual_grading_only=manual_grading_only,
                manual_grading_only_reason=manual_grading_only_reason,
                **({'session_mode': session_mode_override} if session_mode_override else {}),
            )
        except Exception as e:
            try:
                if launched_window:
                    launched_window.close()
            except Exception:
                pass
            show_error(self, "Launch Error", f"Could not launch exam mode: {str(e)}")

    def launch_exam_mode_for_item(self, item, resume_snapshot: Optional[Dict[str, Any]] = None,
                                  paper_num_override: Optional[str] = None,
                                  paper_resources: Optional[Dict[str, Dict[str, str]]] = None,
                                  session_mode_override: Optional[str] = None):
        self._launch_exam_mode_for_item_impl(item, resume_snapshot=resume_snapshot,
                                            paper_num_override=paper_num_override,
                                            paper_resources=paper_resources,
                                            session_mode_override=session_mode_override)

    def launch_standalone_exam_mode(self):
        if _resolve_exam_mode_launcher() is None:
            detail = (
                f"\n\nImport error: {_EXAM_MODE_IMPORT_ERROR}"
                if _EXAM_MODE_IMPORT_ERROR
                else ""
            )
            show_error(
                self,
                "Exam Mode Unavailable",
                "Exam mode module is unavailable. Make sure exam_mode.py is present and dependencies are installed."
                + detail,
            )
            return

        candidates = self._collect_standalone_exam_candidates()
        if not candidates:
            show_error(self, "No Paper Selected",
                       "Please search for a paper first.\n\n"
                       "Enter a subject + component, click Search, then\n"
                       "press this button again.")
            return

        selected_candidate: Optional[ExamModeLaunchCandidate] = None
        if len(candidates) == 1:
            selected_candidate = candidates[0]
        elif self._requires_standalone_exam_disambiguation(candidates):
            selected_candidate = self._prompt_standalone_exam_selection(candidates)
        else:
            selected_candidate = candidates[0]
        if selected_candidate is None:
            return

        self.launch_exam_mode_for_item(
            selected_candidate.item,
            paper_resources=selected_candidate.paper_resources,
        )

    def load_config(self):
        config = ConfigManager.load_config()
        level_value = SubjectDatabase._normalize_level(config.get('default_level', 'IGCSE')) or "IGCSE"
        if level_value not in {"IGCSE", "A Level"}:
            level_value = "IGCSE"
        self.current_level = level_value
        if self.current_level == "IGCSE":
            self.igcse_level_btn.setChecked(True)
        else:
            self.alevel_level_btn.setChecked(True)

        series = str(config.get('default_series', 'MJ')).strip().upper()
        for s, cb in self.series_vars.items():
            cb.setChecked(s == series)
        if not any(cb.isChecked() for cb in self.series_vars.values()):
            self.series_vars['MJ'].setChecked(True)
        self.update_series_availability(self.subject_code or "")
        self.update_variant_lock_ui([s for s, cb in self.series_vars.items() if cb.isChecked()], None)

        self.gt_var.setChecked(config.get('default_include_gt', False))
        self._set_results_view_mode(ConfigManager.get_dashboard_results_view(), persist=False, rerender=False)
        collapsed = False
        if hasattr(ConfigManager, "get_dashboard_sidebar_collapsed"):
            collapsed = bool(ConfigManager.get_dashboard_sidebar_collapsed())
        self._set_sidebar_collapsed(collapsed, persist=False, animate=False)
        if ConfigManager.get_dashboard_match_system_accent():
            app = QApplication.instance()
            if app is not None:
                get_theme_manager().apply_theme(app, self._current_theme_name())
        self._sync_live_subject_search_mode()
        self._sync_settings_window_state()

    def _maybe_show_onboarding_dialog(self) -> None:
        if str(os.environ.get("QT_QPA_PLATFORM", "")).strip().lower() in {"offscreen", "minimal"}:
            return
        if str(os.environ.get("PYTEST_CURRENT_TEST", "")).strip():
            return
        if ConfigManager.get_dashboard_onboarding_completed():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Welcome - Guided Setup")
        dialog.setModal(True)
        dialog.resize(520, 320)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "First-run checklist:\n"
            "1) Choose exam level\n"
            "2) Select subject\n"
            "3) Enter year range\n"
            "4) Pick source-aware document filters\n"
            "5) Verify AI setup status in Settings > AI Configuration"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        ok = QPushButton("Start Using App")
        ok.clicked.connect(dialog.accept)
        layout.addWidget(ok)
        dialog.exec()
        ConfigManager.set_dashboard_onboarding_completed(True)
        show_toast(self, "Onboarding complete. You can reopen guidance from User Documentation.")

    def _open_command_palette(self) -> None:
        commands: List[Tuple[str, str]] = [
            ("focus_subject", "Focus Subject Search"),
            ("run_search", "Run Search"),
            ("open_settings", "Open Settings"),
            ("launch_exam", "Launch Standalone Exam Mode"),
            ("toggle_theme", "Toggle Solid Dark/White Theme"),
            ("open_docs", "Open User Documentation"),
        ]
        dialog = CommandPaletteDialog(commands, self)

        def _run(command_id: str) -> None:
            ConfigManager.push_command_palette_recent(command_id)
            if command_id == "focus_subject":
                self._focus_control_anchor("subject")
            elif command_id == "run_search":
                self.on_search()
            elif command_id == "open_settings":
                self._show_settings_window()
            elif command_id == "launch_exam":
                self.launch_standalone_exam_mode()
            elif command_id == "toggle_theme":
                app = QApplication.instance()
                if app is not None:
                    current = self._current_theme_name()
                    target = "Solid White" if current == "Solid Dark" else "Solid Dark"
                    get_theme_manager().apply_theme(app, target)
            elif command_id == "open_docs":
                self.open_user_documentation()

        dialog.command_selected.connect(_run)
        self._command_palette = dialog
        dialog.exec()

    def _build_offline_revision_pack(self) -> None:
        if not self.search_results:
            show_warning(self, "Offline Pack", "Search for papers first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose Folder for Offline Revision Pack", self._desktop_download_dir())
        if not folder:
            return
        from Core.offline_pack import build_offline_pack
        import threading
        cancel_event = threading.Event()
        items = self._flatten_group_items(include_resources=True)
        try:
            directory, count, failures = run_io(build_offline_pack, folder, items, cancel_event=cancel_event, cancel=cancel_event.set, title="Building offline revision pack…", wait_timeout=3600)
        except Exception as exc:
            show_error(self, "Offline Pack", str(exc))
            return
        if failures:
            show_warning(self, "Offline Pack", f"Saved {count} files; {len(failures)} failed. See manifest.md for details.")
        show_download_complete_dialog(self, "Offline Pack Ready", directory, message_prefix="Pack folder:")

    def _collect_current_filters(self) -> Dict[str, Any]:
        return {
            "level": self.current_level,
            "subject": str(getattr(self, "subject_entry", QLineEdit()).text() if isinstance(getattr(self, "subject_entry", None), QLineEdit) else ""),
            "series": [s for s, cb in getattr(self, "series_vars", {}).items() if isinstance(cb, QCheckBox) and cb.isChecked()],
            "components": str(getattr(self, "component_entry", QLineEdit()).text() if isinstance(getattr(self, "component_entry", None), QLineEdit) else ""),
            "years": str(getattr(self, "year_entry", QLineEdit()).text() if isinstance(getattr(self, "year_entry", None), QLineEdit) else ""),
            "doc_types": {
                "QP": bool(getattr(self, "paper_var", None).isChecked()) if isinstance(getattr(self, "paper_var", None), QCheckBox) else True,
                "MS": bool(getattr(self, "ms_var", None).isChecked()) if isinstance(getattr(self, "ms_var", None), QCheckBox) else True,
                "GT": bool(getattr(self, "gt_var", None).isChecked()) if isinstance(getattr(self, "gt_var", None), QCheckBox) else False,
            },
        }

    def _save_current_filter_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok:
            return
        preset_name = str(name or "").strip()
        if not preset_name:
            show_warning(self, "Preset", "Preset name is required.")
            return
        presets = ConfigManager.get_dashboard_saved_presets()
        presets = [p for p in presets if str(p.get("name", "")).strip().casefold() != preset_name.casefold()]
        presets.insert(0, {"name": preset_name, "filters": self._collect_current_filters()})
        ConfigManager.set_dashboard_saved_presets(presets)
        show_toast(self, f"Saved preset '{preset_name}'")

    def _load_filter_preset(self) -> None:
        presets = ConfigManager.get_dashboard_saved_presets()
        if not presets:
            show_warning(self, "Preset", "No saved presets yet.")
            return
        names = [str(p.get("name", "")) for p in presets]
        name, ok = QInputDialog.getItem(self, "Load Preset", "Select preset:", names, 0, False)
        if not ok:
            return
        selected = next((p for p in presets if str(p.get("name", "")) == str(name)), None)
        if not selected:
            return
        filters = dict(selected.get("filters", {}) or {})
        subject = str(filters.get("subject", "")).strip()
        if isinstance(getattr(self, "subject_entry", None), QLineEdit):
            self.subject_entry.setText(subject)
            self.subjects_set_from_text(subject)
        if isinstance(getattr(self, "component_entry", None), QLineEdit):
            self.component_entry.setText(str(filters.get("components", "")).strip())
        if isinstance(getattr(self, "year_entry", None), QLineEdit):
            self.year_entry.setText(str(filters.get("years", "")).strip())
        doc_types = dict(filters.get("doc_types", {}) or {})
        for key, attr in (("QP", "paper_var"), ("MS", "ms_var"), ("GT", "gt_var")):
            cb = getattr(self, attr, None)
            if isinstance(cb, QCheckBox):
                cb.setChecked(bool(doc_types.get(key, cb.isChecked())))
        series = {str(x).upper() for x in filters.get("series", [])}
        for code, cb in getattr(self, "series_vars", {}).items():
            if isinstance(cb, QCheckBox):
                cb.setChecked(code in series if series else cb.isChecked())
        show_toast(self, f"Loaded preset '{name}'")

    def _pin_current_search_favorite(self) -> None:
        label = str(getattr(self, "subject_entry", QLineEdit()).text() if isinstance(getattr(self, "subject_entry", None), QLineEdit) else "").strip() or "Favorite Search"
        favorites = ConfigManager.get_dashboard_favorites()
        favorites.insert(0, {"label": label, "payload": self._collect_current_filters()})
        ConfigManager.set_dashboard_favorites(favorites)
        show_toast(self, f"Pinned favorite '{label}'")

    def _resolve_theme_name_input(self, theme_name: str) -> Optional[str]:
        candidate = str(theme_name or "").strip()
        if not candidate:
            return None

        manager = get_theme_manager()
        if not hasattr(manager, "has_theme"):
            return candidate

        if manager.has_theme(candidate):
            return candidate

        lowered = candidate.casefold()
        for known in manager.theme_names(include_hidden=True):
            if str(known).casefold() == lowered:
                return str(known)

        aliases = getattr(manager, "THEME_ALIASES", {})
        if isinstance(aliases, dict):
            for alias in aliases.keys():
                if str(alias).casefold() == lowered:
                    return str(alias)
        return None

    def _current_theme_name(self) -> str:
        return str(get_theme_manager().current_theme() or "Archive Blue")

    def _sync_live_subject_search_mode(self) -> None:
        entry = getattr(self, "subject_entry", None)
        if not isinstance(entry, QLineEdit):
            return
        if not self._subject_live_search_connected:
            entry.textChanged.connect(self.on_subject_type)
            self._subject_live_search_connected = True




    def _search_button_focus_rule(self) -> str:
        focus_border = self._mix_colors(Colors.PRIMARY, "#FFFFFF", 0.32)
        return (
            "QPushButton:focus {"
            f"border: 2px solid {focus_border};"
            "padding: 7px 15px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
        )

    def _with_search_button_focus_rule(self, stylesheet: str) -> str:
        style = str(stylesheet or "")
        rule = self._search_button_focus_rule()
        if rule in style:
            return style
        return f"{style}{rule}"


    def _apply_search_button_theme_style(self) -> None:
        button = getattr(self, "search_button", None)
        if isinstance(button, QPushButton):
            button.setStyleSheet(self._build_action_button_stylesheet(Colors.PRIMARY))

    def _is_liquid_glass_enabled(self) -> bool:
        def _as_bool(value: Any) -> Optional[bool]:
            if isinstance(value, bool):
                return value
            if value is None:
                return None
            text = str(value).strip().casefold()
            if text in {"1", "true", "yes", "on", "enabled"}:
                return True
            if text in {"0", "false", "no", "off", "disabled"}:
                return False
            return None

        for key in ("ui.liquid_glass_enabled", "ui.liquid_glass", "ui.liquid_glass_on"):
            interpreted = _as_bool(ConfigManager.get_value(key, None))
            if interpreted is not None:
                return interpreted

        for source in (self, self._central_widget):
            if source is None:
                continue
            for prop_name in ("liquidGlassEnabled", "liquid_glass_enabled"):
                interpreted = _as_bool(source.property(prop_name))
                if interpreted is not None:
                    return interpreted
        return False


    def on_theme_changed_by_user(self, theme_name: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        resolved = self._resolve_theme_name_input(theme_name)
        if not resolved:
            return
        applied = get_theme_manager().apply_theme(app, resolved)
        ConfigManager.set_value("ui.theme", applied)

    def _delete_custom_theme_by_user(self, theme_name: str) -> bool:
        candidate = str(theme_name or "").strip()
        if not candidate:
            return False
        manager = get_theme_manager()
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
            if app is not None:
                applied = manager.apply_theme(app, ThemeManager.DEFAULT_THEME)
                ConfigManager.set_value("ui.theme", applied)
        self._sync_settings_window_state()
        return True

    def _current_global_font_family(self) -> str:
        manager = get_theme_manager()
        if hasattr(manager, "global_font_family"):
            try:
                value = str(manager.global_font_family() or "").strip()  # type: ignore[attr-defined]
                if value:
                    return value
            except Exception:
                pass
        return ConfigManager.get_ui_font_family()

    def on_font_changed_by_user(self, font_name: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        available_fonts = self.__dict__.get("_available_ui_fonts")
        if not isinstance(available_fonts, list):
            available_fonts = discover_available_ui_fonts()
            self._available_ui_fonts = available_fonts
        selected = sanitize_font_choice(font_name, available_fonts)
        ConfigManager.set_ui_font_family(selected)

        manager = get_theme_manager()
        if hasattr(manager, "apply_font_override"):
            try:
                manager.apply_font_override(app, selected)  # type: ignore[attr-defined]
            except Exception:
                pass
        elif hasattr(manager, "set_global_font_family") and hasattr(manager, "apply_theme"):
            try:
                manager.set_global_font_family(selected)  # type: ignore[attr-defined]
                manager.apply_theme(app, self._current_theme_name())
            except Exception:
                pass
        self._sync_settings_window_state()


    def on_sound_toggled(self, enabled: bool) -> None:
        ConfigManager.set_sound_enabled(bool(enabled))
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                viewer = getattr(widget, "pdf_viewer", None)
                header = getattr(viewer, "audio_header", None) if viewer is not None else None
                if header is None or not hasattr(header, "refresh_sound_state"):
                    continue
                try:
                    header.refresh_sound_state()
                except Exception:
                    pass
        self._sync_settings_window_state()

    def on_system_accent_toggled(self, enabled: bool) -> None:
        ConfigManager.set_dashboard_match_system_accent(bool(enabled))
        app = QApplication.instance()
        if app is not None:
            get_theme_manager().apply_theme(app, self._current_theme_name())
        self.apply_runtime_theme(force=True)

    def on_answer_panel_position_changed(self, position: str) -> None:
        ConfigManager.set_exam_answer_panel_position(position)
        self._sync_settings_window_state()

    def on_random_theme_toggled(self, enabled: bool) -> None:
        ConfigManager.set_random_theme_enabled(bool(enabled))
        self._sync_settings_window_state()

    def on_preference_toggled(self, key: str, enabled: bool) -> None:
        if key not in {"show_startup_animation", "full_screen_on_startup", "custom_theme_creator_enabled"}:
            return
        ConfigManager.set_value(f"ui.{key}", bool(enabled))
        self._sync_settings_window_state()

    def _runtime_theme_signature_key(self) -> str:
        return self._current_theme_name()

    def _on_theme_changed(self, theme_name: str) -> None:
        if self._graceful_exit_in_progress or self._graceful_exit_finalizing:
            return
        if not self.isVisible():
            self._deferred_theme_refresh_needed = True
            return
        self.apply_runtime_theme(force=True)


    def _action_button_style_for_theme(self, base_color: str) -> str:
        return self._build_action_button_stylesheet(base_color)

    def _apply_header_action_button_styles(self) -> None:
        open_bg = Colors.SECONDARY
        download_bg = Colors.INFO
        settings_bg = Colors.WARNING
        if self.open_all_button:
            self.open_all_button.setStyleSheet(self._action_button_style_for_theme(open_bg))
        if self.download_all_button:
            self.download_all_button.setStyleSheet(self._action_button_style_for_theme(download_bg))
        if self.settings_btn:
            self.settings_btn.setStyleSheet(self._action_button_style_for_theme(settings_bg))
        if self.launch_exam_btn:
            self.launch_exam_btn.setStyleSheet(self._action_button_style_for_theme(Colors.ACCENT_PURPLE))


    def _build_action_button_stylesheet(self, base_color: str) -> str:
        hover_color = self._mix_colors(base_color, Colors.PRIMARY_HOVER, 0.45)
        pressed_color = self._mix_colors(hover_color, Colors.BG_DARK, 0.18)
        border_color = self._mix_colors(base_color, Colors.BG_DARK, 0.38)
        hover_border = self._mix_colors(border_color, "#FFFFFF", 0.18)
        focus_border = self._mix_colors(hover_border, "#FFFFFF", 0.22)
        text_color = ThemeManager._ensure_text_contrast(self._contrast_text_for_bg(base_color), base_color, min_ratio=4.5)
        hover_text_color = ThemeManager._ensure_text_contrast(self._contrast_text_for_bg(hover_color), hover_color, min_ratio=4.5)
        pressed_text_color = ThemeManager._ensure_text_contrast(self._contrast_text_for_bg(pressed_color), pressed_color, min_ratio=4.5)
        disabled_bg = self._mix_colors(base_color, Colors.BG_CARD, 0.58)
        disabled_border = self._mix_colors(border_color, Colors.BG_DARK, 0.18)
        disabled_text = ThemeManager._ensure_text_contrast(
            self._mix_colors(text_color, Colors.TEXT_GRAY, 0.36), disabled_bg, min_ratio=3.0)
        return (
            "QPushButton {"
            f"background-color: {base_color};"
            f"color: {text_color};"
            f"border: 1px solid {border_color};"
            "border-radius: 8px;"
            "padding: 8px 16px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "font-size: 13px;"
            "font-weight: bold;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {hover_color};"
            f"color: {hover_text_color};"
            f"border: 1px solid {hover_border};"
            "}"
            "QPushButton:focus {"
            f"border: 2px solid {focus_border};"
            "padding: 7px 15px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
            "QPushButton:pressed {"
            f"background-color: {pressed_color};"
            f"color: {pressed_text_color};"
            f"border: 1px solid {hover_border};"
            "padding: 8px 16px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
            "QPushButton:disabled {"
            f"background-color: {disabled_bg};"
            f"color: {disabled_text};"
            f"border: 1px solid {disabled_border};"
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
    def _contrast_text_for_bg(bg_hex: str) -> str:
        return Colors.contrast_text_for_bg(bg_hex)

    @staticmethod
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

    @classmethod
    def _contrast_ratio(cls, fg_hex: str, bg_hex: str) -> float:
        l_fg = cls._relative_luminance(fg_hex)
        l_bg = cls._relative_luminance(bg_hex)
        lighter = max(l_fg, l_bg)
        darker = min(l_fg, l_bg)
        return (lighter + 0.05) / (darker + 0.05)


    @staticmethod
    def _is_qt_object_alive(obj: Any) -> bool:
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
            if getattr(self, "level_label", None):
                self.level_label.setStyleSheet(f"color: {ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.18), min_ratio=4.5)};")
            if self.launch_exam_btn:
                self.launch_exam_btn.setStyleSheet(
                    self._action_button_style_for_theme(Colors.ACCENT_PURPLE)
                )
            if self.results_count:
                self.results_count.setStyleSheet(f"color: {Colors.TEXT_GRAY};")
            level_panel = getattr(self, "level_selector_card", None)
            if isinstance(level_panel, QFrame):
                panel_bg = self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.18)
                panel_border = self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.48)
                radio_text = self._contrast_text_for_bg(panel_bg)
                muted_radio_text = ThemeManager._ensure_text_contrast(
                    self._mix_colors(radio_text, Colors.TEXT_GRAY, 0.24), panel_bg, min_ratio=4.5)
                level_panel.setStyleSheet(
                    "QFrame#examLevelSelectorCard {"
                    f"background-color: {panel_bg};"
                    f"border: 1px solid {panel_border};"
                    "border-radius: 10px;"
                    "}"
                    "QFrame#examLevelSelectorCard QLabel {"
                    f"color: {Colors.TEXT_GRAY};"
                    "font-size: 12px;"
                    "font-weight: 600;"
                    "}"
                    "QFrame#examLevelSelectorCard QRadioButton {"
                    f"color: {muted_radio_text};"
                    "font-size: 14px;"
                    "font-weight: 600;"
                    "spacing: 8px;"
                    "padding: 4px 6px;"
                    "}"
                    "QFrame#examLevelSelectorCard QRadioButton::indicator {"
                    "width: 18px;"
                    "height: 18px;"
                    "}"
                    "QFrame#examLevelSelectorCard QRadioButton::indicator:unchecked {"
                    f"border: 1px solid {self._mix_colors(Colors.TEXT_GRAY, Colors.BG_DARK, 0.34)};"
                    f"background: {self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.24)};"
                    "border-radius: 9px;"
                    "}"
                    "QFrame#examLevelSelectorCard QRadioButton::indicator:checked {"
                    f"border: 1px solid {self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, 0.38)};"
                    f"background: {self._mix_colors(Colors.ACCENT_CYAN, Colors.BG_CARD, 0.52)};"
                    "border-radius: 9px;"
                    "}"
                    "QFrame#examLevelSelectorCard QRadioButton:checked {"
                    f"color: {radio_text};"
                    "}"
                )
            self._apply_header_action_button_styles()
            self._apply_control_filter_styles()
            self._apply_control_center_tab_style()
            if self._quick_look_window is not None:
                for button in (self._quick_look_window_prev_btn, self._quick_look_window_next_btn):
                    if isinstance(button, QPushButton):
                        self._style_card_action_button(button, Colors.BG_LIGHT)
                self._quick_look_window_view.setBackgroundBrush(QColor(Colors.BG_DARK))

            self._apply_history_list_scrollbar_style()

            # Coalesce heavy result-row refresh to the next UI tick so theme clicks feel instant.
            self._schedule_results_theme_refresh()

            self._apply_search_button_theme_style()
            self._sync_settings_window_state()
            shell = getattr(self, "_experimental_shell", None)
            if shell is not None:
                shell.refresh()
        finally:
            self._runtime_theme_apply_in_progress = False
            if self._runtime_theme_reapply_requested and not (self._graceful_exit_in_progress or self._graceful_exit_finalizing):
                self._runtime_theme_reapply_requested = False
                QTimer.singleShot(0, lambda: self.apply_runtime_theme(force=True))

    # ------------------------------------------------------------------
    # AI Settings Helper
    # ------------------------------------------------------------------

    def _reset_ai_config_cache(self):
        try:
            import Grading.ai_config as ai_config
            ai_config._default_config = None  # type: ignore[attr-defined]
        except Exception:
            pass

    def prompt_ai_settings(self) -> bool:
        from PySide6.QtWidgets import QInputDialog

        api_key, ok = QInputDialog.getText(
            self,
            "Groq Settings",
            "Groq API Key:",
            text=self.groq_api_key or load_groq_api_key(),
        )
        if not ok:
            return False

        text_model, _ = QInputDialog.getText(
            self,
            "Groq Settings",
            "Text Model:",
            text=self.groq_text_model or load_groq_text_model(),
        )
        vision_model, _ = QInputDialog.getText(
            self,
            "Groq Settings",
            "Vision Model:",
            text=self.groq_vision_model or load_groq_vision_model(),
        )
        return self._save_ai_settings(api_key, text_model, vision_model, show_feedback=True)

    def prompt_api_key(self):
        """Backward-compatible alias kept for older button callbacks/tests."""
        return self.prompt_ai_settings()


    def create_footer(self):
        pass


def _startup_build_fingerprint() -> str:
    target = str(getattr(sys, "executable", "") or "").strip() if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    target = os.path.abspath(target or __file__)
    try:
        stat = os.stat(target)
        return f"{target}:{int(stat.st_mtime_ns)}:{int(stat.st_size)}"
    except Exception:
        return target


def _should_run_full_startup_sequence() -> bool:
    key = "ui.startup_splash_seen_build"
    fingerprint = _startup_build_fingerprint()
    seen = str(ConfigManager.get_value(key, "") or "")
    if seen == fingerprint:
        return False
    ConfigManager.set_value(key, fingerprint)
    return True


def _wait_with_events(milliseconds: int) -> None:
    ms = max(0, int(milliseconds))
    if ms <= 0:
        return
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _supports_window_opacity(widget: QWidget) -> bool:
    if widget is None:
        return False
    try:
        current = float(widget.windowOpacity())
        widget.setWindowOpacity(current if current > 0.0 else 1.0)
        return True
    except Exception:
        return False


def _show_main_on_startup(window: QMainWindow) -> None:
    if ConfigManager.get_value("ui.full_screen_on_startup", True):
        window.showFullScreen()
    else:
        window.show()


def _crossfade_splash_to_main(splash: BetaBootSplashWindow, window: QMainWindow) -> None:
    if not _supports_window_opacity(splash) or not _supports_window_opacity(window):
        _show_main_on_startup(window)
        splash.hide()
        splash.close()
        return

    try:
        window.setWindowOpacity(0.0)
    except Exception:
        _show_main_on_startup(window)
        splash.hide()
        splash.close()
        return

    _show_main_on_startup(window)
    splash.raise_()

    group = QParallelAnimationGroup()
    splash_fade = QPropertyAnimation(splash, b"windowOpacity", group)
    splash_fade.setDuration(300)
    splash_fade.setStartValue(1.0)
    splash_fade.setEndValue(0.0)
    splash_fade.setEasingCurve(QEasingCurve.Type.InOutCubic)

    window_fade = QPropertyAnimation(window, b"windowOpacity", group)
    window_fade.setDuration(300)
    window_fade.setStartValue(0.0)
    window_fade.setEndValue(1.0)
    window_fade.setEasingCurve(QEasingCurve.Type.InOutCubic)

    loop = QEventLoop()
    guard = QTimer(loop)
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    group.finished.connect(loop.quit)
    splash.finished.connect(loop.quit)
    try:
        guard.start(1000)
        group.start()
        loop.exec()
    finally:
        guard.stop()
        group.stop()
        group.deleteLater()
        if isValid(splash):
            splash.finished.disconnect(loop.quit)
        loop.deleteLater()

    if isValid(window):
        window.setWindowOpacity(1.0)
    if isValid(splash):
        splash.hide()
        splash.close()


def _maybe_reexec_project_python() -> None:
    if getattr(sys, "frozen", False):
        return
    if str(os.environ.get(_PYTHON_REEXEC_ENV, "")).strip().lower() in {"1", "true", "yes"}:
        return

    entry_root = Path(__file__).resolve().parents[1]
    preferred_venv = (entry_root / ".venv").resolve()
    preferred_python = preferred_venv / "bin" / "python"
    if not preferred_python.is_file():
        return

    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == preferred_venv:
        return

    env = dict(os.environ)
    env[_PYTHON_REEXEC_ENV] = "1"
    script_path = str(Path(__file__).resolve())
    args = [str(preferred_python), script_path, *sys.argv[1:]]
    try:
        os.execve(str(preferred_python), args, env)
    except Exception as exc:
        print(f"[Startup] Python handoff skipped ({exc}); continuing with {sys.executable}", file=sys.stderr)


def _running_under_idle() -> bool:
    if "idlelib" in sys.modules:
        return True
    stdin = getattr(sys, "stdin", None)
    module_name = str(getattr(getattr(stdin, "__class__", None), "__module__", ""))
    return module_name.startswith("idlelib")


def _warmup_ocr_runtime() -> None:
    try:
        from Core.pdf_service import _request
        _request('call', ('Core.ocr_service', 'warmup_ocr_runtime', (), {}), show_progress=False)
    except Exception:
        logging.getLogger(__name__).warning("OCR warmup failed", exc_info=True)


def _launch_outside_idle() -> bool:
    try:
        script_path = str(Path(__file__).resolve())
        project_root_path = Path(__file__).resolve().parents[1]
        project_root = str(project_root_path)
        preferred_python = (project_root_path / ".venv" / "bin" / "python")
        python_cmd = str(preferred_python) if preferred_python.is_file() else str(sys.executable)
        env = dict(os.environ)
        # Prevent recursive relaunch if the child process is still detected as IDLE.
        env["PAST_PAPER_FINDER_EXIT_ON_IDLE"] = "1"
        env[_PYTHON_REEXEC_ENV] = "1"
        subprocess.Popen(
            [python_cmd, script_path, *sys.argv[1:]],
            cwd=project_root,
            env=env,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def _show_already_running_warning() -> None:
    temp_app: Optional[QApplication] = None
    app = QApplication.instance()
    if app is None:
        temp_app = QApplication([sys.argv[0] if sys.argv else "past-paper-finder"])
    try:
        QMessageBox.warning(
            None,
            f"{APP_NAME} Already Running",
            f"{APP_NAME} is already running.\n"
            "Please return to the existing window instead of opening another instance.",
        )
    except Exception:
        print(
            f"{APP_NAME} is already running. Please return to the existing window.",
            file=sys.stderr,
        )
    finally:
        if temp_app is not None:
            temp_app.quit()


def _acquire_single_instance_lock() -> bool:
    global _APP_INSTANCE_LOCK
    if _APP_INSTANCE_LOCK is not None:
        return True

    lock_root = Path(tempfile.gettempdir()) / _APP_LOCK_DIR_NAME
    try:
        lock_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        lock_root = Path(tempfile.gettempdir())
    lock_path = lock_root / _APP_LOCK_FILE_NAME

    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(120000)
    try:
        if lock.tryLock(0):
            _APP_INSTANCE_LOCK = lock
            return True
    except Exception:
        pass

    _show_already_running_warning()
    return False


def _release_single_instance_lock() -> None:
    global _APP_INSTANCE_LOCK
    lock = _APP_INSTANCE_LOCK
    _APP_INSTANCE_LOCK = None
    if lock is None:
        return
    try:
        if lock.isLocked():
            lock.unlock()
    except Exception:
        pass


def main():
    import sys, traceback
    from multiprocessing import freeze_support
    freeze_support()
    configure_error_only_logging()

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        log_path = os.path.join(os.getcwd(), "crash.log")
        try:
            from Core.runtime_paths import cache_path
            log_path = cache_path("logs", "crash.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8", buffering=_FILE_BUFFER_BYTES) as f:
                f.write("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)) + "\n")
        except OSError:
            pass
        print(f"Unhandled exception logged to {log_path}", file=sys.stderr)
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception

    if _running_under_idle():
        print(
            "Running this PyQt app inside IDLE can cause random native crashes on macOS. "
            "Launch from Terminal instead (python gui_main.py).",
            file=sys.stderr,
        )
        if _launch_outside_idle():
            print(f"Launching {APP_NAME} in a separate Python process...", file=sys.stderr)
            return
        exit_on_idle = str(os.environ.get("PAST_PAPER_FINDER_EXIT_ON_IDLE", "")).strip().lower() in {"1", "true", "yes"}
        if exit_on_idle:
            return

    _maybe_reexec_project_python()

    if not _acquire_single_instance_lock():
        return

    qt_platform = str(os.environ.get("QT_QPA_PLATFORM", "")).strip().lower()
    if qt_platform == "offscreen":
        print("[Startup] QT_QPA_PLATFORM=offscreen detected; resetting for desktop GUI.", file=sys.stderr)
        os.environ.pop("QT_QPA_PLATFORM", None)

    app = QApplication(sys.argv)
    app.aboutToQuit.connect(_release_single_instance_lock)
    studio_startup = startup_redesign_enabled()
    show_startup = bool(ConfigManager.get_value("ui.show_startup_animation", True))
    if studio_startup or not show_startup:
        # Resolve saved/custom/random-on-launch themes once, before any visible frame.
        setup_appearance(app)
    full_sequence = _should_run_full_startup_sequence() if show_startup else False
    splash = None
    if show_startup:
        splash_class = StudioBootSplashWindow if studio_startup else BetaBootSplashWindow
        splash = splash_class(full_sequence=full_sequence)
        splash.show_centered()
    startup_begin = time.monotonic()
    if splash is not None:
        splash.set_stage("Loading Studio" if studio_startup else "Preparing your workspace", 0, 5)
        if studio_startup:
            splash.start_intro()
            QApplication.processEvents()
        else:
            splash.play_intro_blocking()
    if splash is not None and splash._closed:
        _release_single_instance_lock()
        return

    if splash is not None:
        splash.set_stage("Loading Studio" if studio_startup else "Getting things ready", 1, 5)
    QApplication.processEvents()

    if splash is not None:
        splash.set_stage("Paper tools" if studio_startup else "Preparing your paper tools", 2, 5)
    # OCR loads lazily when a scanned PDF needs it, keeping startup independent of models.
    QApplication.processEvents()
    if splash is not None and splash._closed:
        _release_single_instance_lock()
        return

    if splash is not None:
        splash.set_stage("Loading interface" if studio_startup else "Adding your personal touch", 3, 5)
    if not studio_startup and show_startup:
        setup_appearance(app)
    QApplication.processEvents()

    if splash is not None:
        splash.set_stage("Opening Studio" if studio_startup else "Opening your workspace", 4, 5)
    window = PastPaperFinderGUI()
    QApplication.processEvents()

    if splash is not None:
        splash.set_stage("Recent papers" if studio_startup else "Restoring your recent papers", 5, 5)
    try:
        window.refresh_history()
    except Exception:
        pass

    minimum_ms = 1200 if full_sequence else 850
    elapsed_ms = int((time.monotonic() - startup_begin) * 1000)
    if show_startup and not studio_startup and elapsed_ms < minimum_ms:
        _wait_with_events(minimum_ms - elapsed_ms)

    if splash is not None:
        splash.finish_loading()
        if splash._closed:
            window.close()
            _release_single_instance_lock()
            return
        _crossfade_splash_to_main(splash, window)
    else:
        _show_main_on_startup(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
