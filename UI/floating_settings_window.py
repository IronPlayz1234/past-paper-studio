from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, Property, QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLayout, QLayoutItem, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QApplication, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from Utils.gui_utils import Colors
from Data.app_metadata import APP_VERSION, SOURCING_NOTICE
from UI.custom_theme_creator import CustomThemeCreatorWidget
from UI.theme import get_theme_manager
from UI.solid_color_themes import SOLID_COLOR_THEME_NAMES
from UI.classic_themes import CLASSIC_THEME_NAMES

ThemeSelectedCallback = Callable[[str], None]
FontSelectedCallback = Callable[[str], None]
SoundToggledCallback = Callable[[bool], None]
ScaleToggledCallback = Callable[[bool], None]
SystemAccentToggledCallback = Callable[[bool], None]
AnswerPanelPositionChangedCallback = Callable[[str], None]
RandomThemeToggledCallback = Callable[[bool], None]
OpenDocsCallback = Callable[[], None]
DocsRequestedCallback = Callable[[], None]
SaveAICallback = Callable[[str, str, str], bool]
RefreshAICallback = Callable[[], Tuple[str, str, str]]
DeleteThemeCallback = Callable[[str], bool]
UserHiddenCallback = Callable[[], None]


class AIConfigDialog(QDialog):
    """Floating AI configuration editor used by the settings window."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        on_save_ai: Optional[SaveAICallback] = None,
        on_refresh_ai: Optional[RefreshAICallback] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("AI Configuration")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(480, 300)

        self._on_save_ai = on_save_ai
        self._on_refresh_ai = on_refresh_ai

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        card = QFrame(self)
        card.setObjectName("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(10)
        root.addWidget(card)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(10)

        self.groq_api_key_input = QLineEdit(card)
        self.groq_api_key_input.setPlaceholderText("gsk_...")
        self.groq_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.groq_text_model_input = QLineEdit(card)
        self.groq_text_model_input.setPlaceholderText("meta-llama/llama-4-scout-17b-16e-instruct")
        self.groq_vision_model_input = QLineEdit(card)
        self.groq_vision_model_input.setPlaceholderText("meta-llama/llama-4-scout-17b-16e-instruct")

        form_layout.addRow("Groq API Key", self.groq_api_key_input)
        form_layout.addRow("Text Model", self.groq_text_model_input)
        form_layout.addRow("Vision Model", self.groq_vision_model_input)
        card_layout.addLayout(form_layout)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self.ai_refresh_btn = QPushButton("Refresh", card)
        self.ai_refresh_btn.clicked.connect(self._refresh_ai_values)
        self.ai_save_btn = QPushButton("Save", card)
        self.ai_save_btn.clicked.connect(self._save_ai_values)
        self.close_btn = QPushButton("Close", card)
        self.close_btn.clicked.connect(self.hide)
        button_row.addStretch(1)
        button_row.addWidget(self.ai_refresh_btn)
        button_row.addWidget(self.ai_save_btn)
        button_row.addWidget(self.close_btn)
        card_layout.addLayout(button_row)

        self.status_label = QLabel("", card)
        self.status_label.setObjectName("settingsStatusLabel")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        self.apply_runtime_theme()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.hide()
        event.ignore()

    def set_ai_values(self, api_key: str, text_model: str, vision_model: str) -> None:
        self.groq_api_key_input.setText(str(api_key or ""))
        self.groq_text_model_input.setText(str(text_model or ""))
        self.groq_vision_model_input.setText(str(vision_model or ""))

    def _save_ai_values(self) -> None:
        self.status_label.setText("")
        if not callable(self._on_save_ai):
            return
        ok = bool(
            self._on_save_ai(
                self.groq_api_key_input.text(),
                self.groq_text_model_input.text(),
                self.groq_vision_model_input.text(),
            )
        )
        if ok:
            self.status_label.setText("Saved AI settings.")
        else:
            self.status_label.setText("Failed to save AI settings.")

    def _refresh_ai_values(self) -> None:
        self.status_label.setText("")
        if not callable(self._on_refresh_ai):
            return
        values = self._on_refresh_ai()
        if isinstance(values, tuple) and len(values) == 3:
            self.set_ai_values(values[0], values[1], values[2])
            self.status_label.setText("Loaded current AI settings.")

    def apply_runtime_theme(self) -> None:
        accent = str(getattr(Colors, "ACCENT_CYAN", "") or Colors.SECONDARY)
        panel_bg = _opaque_settings_panel_bg()
        text_color = Colors.contrast_text_for_bg(panel_bg)
        card_bg = _mix_hex(str(Colors.BG_MEDIUM), panel_bg, 0.18)
        input_bg = _mix_hex(str(Colors.BG_LIGHT), card_bg, 0.24)
        button_bg = _mix_hex(str(Colors.BG_LIGHT), card_bg, 0.18)
        hover_bg = _mix_hex(button_bg, accent, 0.12)
        pressed_bg = _mix_hex(button_bg, accent, 0.2)
        subtle_border = _mix_hex(str(Colors.BG_LIGHT), str(Colors.BG_DARK), 0.36)
        border = _mix_hex(accent, panel_bg, 0.42)
        disabled_bg = _mix_hex(button_bg, panel_bg, 0.55)
        disabled_text = _mix_hex(text_color, panel_bg, 0.52)
        muted_text = _mix_hex(text_color, card_bg, 0.46)
        input_text = Colors.contrast_text_for_bg(input_bg)
        button_text = Colors.contrast_text_for_bg(button_bg)
        hover_text = Colors.contrast_text_for_bg(hover_bg)
        pressed_text = Colors.contrast_text_for_bg(pressed_bg)

        self.setStyleSheet(
            "QDialog {"
            f"background-color: {panel_bg};"
            f"color: {text_color};"
            f"border: 1px solid {subtle_border};"
            "border-radius: 2px;"
            "}"
            "QFrame#settingsCard {"
            f"background-color: {card_bg};"
            f"border: 1px solid {subtle_border};"
            "border-radius: 2px;"
            "}"
            "QLabel#settingsStatusLabel {"
            f"color: {muted_text};"
            "font-size: 12px;"
            "}"
            "QLineEdit {"
            f"background-color: {input_bg};"
            f"color: {input_text};"
            f"border: 1px solid {subtle_border};"
            "border-radius: 2px;"
            "padding: 7px 10px;"
            "min-height: 34px;"
            "}"
            "QLineEdit:focus {"
            f"border: 1px solid {border};"
            "}"
            "QPushButton {"
            f"background-color: {button_bg};"
            f"color: {button_text};"
            f"border: 1px solid {subtle_border};"
            "border-radius: 2px;"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "font-size: 13px;"
            "font-weight: 600;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {hover_bg};"
            f"color: {hover_text};"
            f"border: 1px solid {border};"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
            "QPushButton:pressed {"
            f"background-color: {pressed_bg};"
            f"color: {pressed_text};"
            f"border: 1px solid {border};"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
            "QPushButton:disabled {"
            f"background-color: {disabled_bg};"
            f"color: {disabled_text};"
            f"border: 1px solid {subtle_border};"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "min-width: 0px;"
            "}"
        )


class CustomThemeEditorDialog(QDialog):
    """Dedicated custom-theme editor window that can be opened from the theme list."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        on_theme_saved: Optional[ThemeSelectedCallback] = None,
        on_closed: Optional[OpenDocsCallback] = None,
        target_root_widget: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Custom Theme Creator")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(560, 360)

        self._on_theme_saved = on_theme_saved
        self._on_closed = on_closed

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title = QLabel("Custom Theme Creator", self)
        title.setObjectName("customThemeEditorTitle")
        subtitle = QLabel("Enable edit mode, click widgets, then save your theme.", self)
        subtitle.setObjectName("customThemeEditorSubtitle")
        subtitle.setWordWrap(True)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_row.addLayout(title_col, 1)
        self.close_btn = QPushButton("Back to Settings", self)
        self.close_btn.clicked.connect(self.hide)
        header_row.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header_row)

        self.creator = CustomThemeCreatorWidget(self)
        self.creator.setMaximumHeight(16777215)
        self.creator.theme_saved.connect(self._on_creator_theme_saved)
        root.addWidget(self.creator, 1)

        if isinstance(target_root_widget, QWidget):
            self.creator.set_target_root_widget(target_root_widget)

        self.apply_runtime_theme()

    def set_target_root_widget(self, widget: Optional[QWidget]) -> None:
        if isinstance(widget, QWidget):
            self.creator.set_target_root_widget(widget)

    def _on_creator_theme_saved(self, theme_name: str) -> None:
        if callable(self._on_theme_saved):
            self._on_theme_saved(str(theme_name or ""))

    def _stop_editor_mode(self) -> None:
        creator = self.__dict__.get("creator")
        if isinstance(creator, CustomThemeCreatorWidget):
            creator.force_stop_edit_mode()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_editor_mode()
        self.hide()
        event.ignore()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._stop_editor_mode()
        super().hideEvent(event)
        if callable(self._on_closed):
            self._on_closed()

    def apply_runtime_theme(self) -> None:
        accent = str(getattr(Colors, "ACCENT_CYAN", "") or Colors.SECONDARY)
        panel_bg = _opaque_settings_panel_bg()
        text_color = Colors.contrast_text_for_bg(panel_bg)
        muted_text = _mix_hex(text_color, panel_bg, 0.44)
        border = _mix_hex(accent, panel_bg, 0.45)

        self.setStyleSheet(
            "QDialog {"
            f"background-color: {panel_bg};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 2px;"
            "}"
            "QLabel#customThemeEditorTitle {"
            "font-size: 15px;"
            "font-weight: 700;"
            f"color: {text_color};"
            "}"
            "QLabel#customThemeEditorSubtitle {"
            "font-size: 12px;"
            f"color: {muted_text};"
            "}"
        )
        self.creator.apply_runtime_theme()


class FlowLayout(QLayout):
    """Simple wrapping flow layout for theme cards."""

    def __init__(self, parent: Optional[QWidget] = None, *, margin: int = 0, h_spacing: int = 10, v_spacing: int = 10):
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        available_width = max(1, effective.width())

        rows: List[List[Tuple[QLayoutItem, QSize]]] = []
        row_widths: List[int] = []
        row_heights: List[int] = []
        current_row: List[Tuple[QLayoutItem, QSize]] = []
        current_width = 0
        current_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            hint = item.sizeHint()
            item_width = max(1, hint.width())
            proposed_width = item_width if not current_row else current_width + self._h_spacing + item_width

            if current_row and proposed_width > available_width:
                rows.append(current_row)
                row_widths.append(current_width)
                row_heights.append(current_height)
                current_row = [(item, hint)]
                current_width = item_width
                current_height = max(1, hint.height())
            else:
                current_row.append((item, hint))
                current_width = proposed_width
                current_height = max(current_height, max(1, hint.height()))

        if current_row:
            rows.append(current_row)
            row_widths.append(current_width)
            row_heights.append(current_height)

        if not rows:
            return top + bottom

        y = effective.y()
        for row_index, row in enumerate(rows):
            row_width = row_widths[row_index]
            row_height = row_heights[row_index]
            start_x = effective.x() + max(0, (available_width - row_width) // 2)
            x = start_x
            for index, (item, hint) in enumerate(row):
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width()
                if index < len(row) - 1:
                    x += self._h_spacing
            y += row_height
            if row_index < len(rows) - 1:
                y += self._v_spacing

        return y - rect.y() + bottom


class ToggleSwitch(QCheckBox):
    """Pill-shaped switch toggle used for settings controls."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setText("")
        self.setTristate(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(48, 24)
        self._pressed_inside = False
        self._slide_progress = 0.0
        self._animation = QPropertyAnimation(self, b"slideProgress", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_to_state)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(48, 24)

    def _animate_to_state(self, checked: bool) -> None:
        end_value = 1.0 if checked else 0.0
        self._animation.stop()
        self._animation.setStartValue(float(self._slide_progress))
        self._animation.setEndValue(end_value)
        self._animation.start()

    def _get_slide_progress(self) -> float:
        return float(self._slide_progress)

    def _set_slide_progress(self, value: float) -> None:
        self._slide_progress = max(0.0, min(1.0, float(value)))
        self.update()

    slideProgress = Property(float, _get_slide_progress, _set_slide_progress)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            try:
                point = event.position().toPoint()
            except Exception:
                point = event.pos()
            self._pressed_inside = self.rect().contains(point)
            if self._pressed_inside:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            try:
                point = event.position().toPoint()
            except Exception:
                point = event.pos()
            released_inside = self.rect().contains(point)
            if self._pressed_inside and released_inside:
                self.setChecked(not self.isChecked())
            self._pressed_inside = False
            event.accept()
            return
        self._pressed_inside = False
        super().mouseReleaseEvent(event)

    @staticmethod
    def _mix_colors(start: QColor, end: QColor, t: float) -> QColor:
        ratio = max(0.0, min(1.0, float(t)))
        r = int(round(start.red() + (end.red() - start.red()) * ratio))
        g = int(round(start.green() + (end.green() - start.green()) * ratio))
        b = int(round(start.blue() + (end.blue() - start.blue()) * ratio))
        a = int(round(start.alpha() + (end.alpha() - start.alpha()) * ratio))
        return QColor(r, g, b, a)

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track_rect = self.rect().adjusted(2, 3, -2, -3)
        track_radius = track_rect.height() / 2.0

        off_color = QColor("#4A4A4A")
        on_color = QColor(str(getattr(Colors, "ACCENT_CYAN", "") or Colors.PRIMARY))
        if not self.isEnabled():
            track_color = QColor("#353535")
        else:
            track_color = self._mix_colors(off_color, on_color, self._slide_progress)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, track_radius, track_radius)

        knob_size = track_rect.height() - 4
        knob_y = track_rect.y() + 2
        min_x = track_rect.x() + 2
        max_x = track_rect.right() - knob_size - 2
        knob_x = int(round(min_x + (max_x - min_x) * self._slide_progress))
        knob_rect = QRect(knob_x, knob_y, knob_size, knob_size)

        knob_color = QColor("#FFFFFF") if self.isEnabled() else QColor("#A0A0A0")
        painter.setBrush(knob_color)
        painter.drawEllipse(knob_rect)

        if self.hasFocus():
            pen = painter.pen()
            pen.setColor(QColor(str(getattr(Colors, "ACCENT_CYAN", "") or Colors.PRIMARY)))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track_rect.adjusted(-1, -1, 1, 1), track_radius, track_radius)


class ThemeCardWidget(QFrame):
    """Clickable theme card with primary/secondary color swatches."""

    clicked = Signal(str)
    contextRequested = Signal(str, QPoint)

    def __init__(
        self,
        theme_name: str,
        *,
        primary_color: str,
        secondary_color: str,
        is_creator: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._theme_name = str(theme_name or "")
        self._primary_color = str(primary_color or "#6B7280")
        self._secondary_color = str(secondary_color or "#9CA3AF")
        self._is_creator = bool(is_creator)
        self._selected = False
        self._accent = "#22D3EE"
        self._text = "#F4F6FB"
        self._muted = "#A8B0BE"
        self._card_bg = "#1B1B1B"
        self._card_bg_selected = "#262626"
        self._card_border = "#2E2E2E"

        self.setObjectName("settingsThemeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(164, 90)
        self.setMaximumWidth(192)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        swatch_row = QHBoxLayout()
        swatch_row.setContentsMargins(0, 0, 0, 0)
        swatch_row.setSpacing(6)

        self._primary_swatch = QFrame(self)
        self._primary_swatch.setFixedHeight(14)
        self._primary_swatch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._secondary_swatch = QFrame(self)
        self._secondary_swatch.setFixedHeight(14)
        self._secondary_swatch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        swatch_row.addWidget(self._primary_swatch, 1)
        swatch_row.addWidget(self._secondary_swatch, 1)
        root.addLayout(swatch_row)

        self._title = QLabel(self._theme_name, self)
        self._title.setObjectName("settingsThemeCardTitle")
        self._title.setWordWrap(True)
        root.addWidget(self._title)

        self._subtitle = QLabel("Create custom palette" if self._is_creator else "", self)
        self._subtitle.setObjectName("settingsThemeCardSubtitle")
        self._subtitle.setWordWrap(False)
        self._subtitle.setVisible(self._is_creator)
        root.addWidget(self._subtitle)

        root.addStretch(1)
        self._apply_styles()

    def theme_name(self) -> str:
        return str(self._theme_name)

    def is_creator_card(self) -> bool:
        return self._is_creator

    def set_selected(self, selected: bool) -> None:
        checked = bool(selected)
        if self._selected == checked:
            return
        self._selected = checked
        self._apply_styles()

    def apply_runtime_theme(
        self,
        *,
        accent: str,
        text_color: str,
        muted_color: str,
        card_bg: str,
        card_bg_selected: str,
        card_border: str,
    ) -> None:
        next_accent = str(accent or self._accent)
        next_text = str(text_color or self._text)
        next_muted = str(muted_color or self._muted)
        next_card_bg = str(card_bg or self._card_bg)
        next_card_bg_selected = str(card_bg_selected or self._card_bg_selected)
        next_card_border = str(card_border or self._card_border)
        if (
            next_accent == self._accent
            and next_text == self._text
            and next_muted == self._muted
            and next_card_bg == self._card_bg
            and next_card_bg_selected == self._card_bg_selected
            and next_card_border == self._card_border
        ):
            return
        self._accent = next_accent
        self._text = next_text
        self._muted = next_muted
        self._card_bg = next_card_bg
        self._card_bg_selected = next_card_bg_selected
        self._card_border = next_card_border
        self._apply_styles()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._theme_name)
        elif event.button() == Qt.MouseButton.RightButton:
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                global_pos = self.mapToGlobal(event.pos())
            self.contextRequested.emit(self._theme_name, global_pos)
        super().mousePressEvent(event)

    def _apply_styles(self) -> None:
        border = self._accent if self._selected else self._card_border
        background = self._card_bg_selected if self._selected else self._card_bg
        border_width = 2 if self._selected else 1
        self.setStyleSheet(
            "QFrame#settingsThemeCard {"
            f"background-color: {background};"
            f"border: {border_width}px solid {border};"
            "border-radius: 12px;"
            "}"
            "QLabel#settingsThemeCardTitle {"
            f"color: {self._text};"
            "font-size: 12px;"
            "font-weight: 650;"
            "}"
            "QLabel#settingsThemeCardSubtitle {"
            f"color: {self._muted};"
            "font-size: 10px;"
            "font-weight: 500;"
            "}"
        )
        self._primary_swatch.setStyleSheet(
            "QFrame {"
            f"background-color: {self._primary_color};"
            "border: none;"
            "border-radius: 5px;"
            "}"
        )
        self._secondary_swatch.setStyleSheet(
            "QFrame {"
            f"background-color: {self._secondary_color};"
            "border: none;"
            "border-radius: 5px;"
            "}"
        )


class FloatingSettingsWindow(QDialog):
    """Reusable floating settings window for main app controls."""

    docsRequested = Signal()
    userHidden = Signal()

    CUSTOM_THEME_CREATOR_ENTRY = "Custom Theme Creator"
    EXTRA_THEMES_SECTION = "EXTRA THEMES"
    THEME_SECTION_SPECS = (
        ('Classic', CLASSIC_THEME_NAMES + ('Archive Blue',)),
        ('Solid Colors', SOLID_COLOR_THEME_NAMES),
        ('Signature Themes', ('Coffee Shop', "Synthwave '84", 'Old Library', 'Matcha Latte',
                              'Carbon Fiber', 'Violet Afterburn', 'Cipher Red', 'Cipher Green',
                              'Cipher Purple', 'Aurora Borealis', 'Crimson Meridian')),
        ('Custom', ('Custom Theme Creator',)),
    )

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        on_theme_selected: Optional[ThemeSelectedCallback] = None,
        on_font_selected: Optional[FontSelectedCallback] = None,
        on_sound_toggled: Optional[SoundToggledCallback] = None,
        on_scale_toggled: Optional[ScaleToggledCallback] = None,
        on_system_accent_toggled: Optional[SystemAccentToggledCallback] = None,
        on_answer_panel_position_changed: Optional[AnswerPanelPositionChangedCallback] = None,
        on_random_theme_toggled: Optional[RandomThemeToggledCallback] = None,
        on_preference_toggled: Optional[Callable[[str, bool], None]] = None,
        on_open_docs: Optional[OpenDocsCallback] = None,
        on_docs_requested: Optional[DocsRequestedCallback] = None,
        on_save_ai: Optional[SaveAICallback] = None,
        on_refresh_ai: Optional[RefreshAICallback] = None,
        on_delete_theme: Optional[DeleteThemeCallback] = None,
        on_user_hidden: Optional[UserHiddenCallback] = None,
    ):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(900, 640)
        self.setMinimumSize(760, 520)
        self.setMaximumSize(1200, 860)

        self._on_theme_selected = on_theme_selected
        self._on_font_selected = on_font_selected
        self._on_sound_toggled = on_sound_toggled
        self._on_scale_toggled = on_scale_toggled
        self._on_system_accent_toggled = on_system_accent_toggled
        self._on_answer_panel_position_changed = on_answer_panel_position_changed
        self._on_random_theme_toggled = on_random_theme_toggled
        self._on_preference_toggled = on_preference_toggled
        self._custom_theme_creator_enabled = False
        self._preference_toggles = {}
        self._on_open_docs = on_open_docs
        self._on_docs_requested = on_docs_requested
        self._on_save_ai = on_save_ai
        self._on_refresh_ai = on_refresh_ai
        self._on_delete_theme = on_delete_theme
        self._on_user_hidden = on_user_hidden

        self._theme_names: List[str] = []
        self._font_names: List[str] = []
        self._theme_cards: Dict[str, ThemeCardWidget] = {}
        self._theme_section_titles: List[str] = []
        self._theme_section_widgets: Dict[str, QWidget] = {}
        self._theme_section_layouts: Dict[str, FlowLayout] = {}
        self._theme_card_sections: Dict[str, str] = {}
        self._selected_theme_name: str = ""
        self._last_emitted_theme: str = ""
        self._suppress_theme_signal = False
        self._suppress_font_signal = False
        self._suppress_sound_signal = False
        self._suppress_scale_signal = False
        self._suppress_system_accent_signal = False
        self._suppress_answer_panel_position_signal = False
        self._suppress_random_theme_signal = False
        self._ai_dialog: Optional[AIConfigDialog] = None
        self._cached_ai_values: Tuple[str, str, str] = ("", "", "")
        self._custom_theme_editor_dialog: Optional[CustomThemeEditorDialog] = None
        self._hidden_for_custom_editor = False
        self._suppress_next_user_hidden = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        self.header_widget = QWidget(self)
        self.header_widget.setObjectName("settingsHeader")
        header_layout = QVBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        self.title_label = QLabel("Settings", self.header_widget)
        self.title_label.setObjectName("settingsTitle")
        self.subtitle_label = QLabel("Control behavior, look and AI configuration.", self.header_widget)
        self.subtitle_label.setObjectName("settingsSubtitle")
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label)
        root.addWidget(self.header_widget)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(16)
        root.addLayout(content_row, 1)

        self.nav_list = QListWidget(self)
        self.nav_list.setObjectName("settingsNavList")
        self.nav_list.setFixedWidth(188)
        self.nav_list.setSpacing(2)
        self.nav_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for label in ("General", "Appearance", "AI Config"):
            self.nav_list.addItem(QListWidgetItem(label))
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        content_row.addWidget(self.nav_list, 0)

        self.pages = QStackedWidget(self)
        self.pages.setObjectName("settingsPages")
        content_row.addWidget(self.pages, 1)

        self.general_page = QWidget(self.pages)
        self.appearance_page = QWidget(self.pages)
        self.ai_page = QWidget(self.pages)
        self.general_tab = self.general_page
        self.personalization_tab = self.appearance_page
        self.pages.addWidget(self.general_page)
        self.pages.addWidget(self.appearance_page)
        self.pages.addWidget(self.ai_page)

        self._build_general_page()
        self._build_appearance_page()
        self._build_ai_page()
        self.nav_list.setCurrentRow(0)
        self.apply_runtime_theme()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _on_nav_changed(self, row: int) -> None:
        index = max(0, min(int(row), self.pages.count() - 1))
        self.pages.setCurrentIndex(index)

    def _build_section_header(self, text: str, parent: QWidget) -> QLabel:
        label = QLabel(str(text or ""), parent)
        label.setObjectName("settingsSectionLabel")
        return label

    def _build_general_page(self) -> None:
        page_layout = QVBoxLayout(self.general_page)
        page_layout.setContentsMargins(20, 20, 20, 20)
        page_layout.setSpacing(14)
        self.general_scroll_area = QScrollArea(self.general_page)
        self.general_scroll_area.setObjectName("settingsGeneralScroll")
        self.general_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.general_scroll_area.setWidgetResizable(True)
        self.general_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.general_scroll_area.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("settingsSectionContainer")
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.general_scroll_area.setWidget(body)
        page_layout.addWidget(self.general_scroll_area, 1)

        layout.addWidget(self._build_section_header("Profile", body))
        from UI.profile_controls import ProfileEditor
        self.profile_editor = ProfileEditor(body)
        layout.addWidget(self.profile_editor)

        prefs_container = QWidget(self.general_page)
        prefs_container.setObjectName("settingsSectionContainer")
        prefs_layout = QGridLayout(prefs_container)
        # Keep fixed-size toggles apart when the footer wraps at narrow widths.
        prefs_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        prefs_layout.setContentsMargins(0, 0, 0, 0)
        prefs_layout.setHorizontalSpacing(14)
        prefs_layout.setVerticalSpacing(12)
        prefs_layout.setColumnStretch(0, 1)
        prefs_layout.setColumnStretch(1, 0)


        self.sound_toggle = ToggleSwitch(prefs_container)
        self.sound_toggle.setObjectName("settingsBodyToggle")
        self.sound_toggle.toggled.connect(self._on_sound_toggled_changed)
        self._suppress_sound_signal = True
        self.sound_toggle.setChecked(True)
        self._suppress_sound_signal = False

        self.scale_toggle = ToggleSwitch(prefs_container)
        self.scale_toggle.setObjectName("settingsBodyToggle")
        self.scale_toggle.toggled.connect(self._on_scale_toggled_changed)
        self._suppress_scale_signal = True
        self.scale_toggle.setChecked(True)
        self._suppress_scale_signal = False
        self.scale_toggle.setVisible(False)
        self.scale_toggle.setEnabled(False)
        self.scale_toggle.setToolTip("Show centimeter scale overlay in exam mode.")

        self.system_accent_toggle = ToggleSwitch(prefs_container)
        self.system_accent_toggle.setObjectName("settingsBodyToggle")
        self.system_accent_toggle.toggled.connect(self._on_system_accent_toggled_changed)
        self._suppress_system_accent_signal = True
        self.system_accent_toggle.setChecked(False)
        self._suppress_system_accent_signal = False

        from UI.localization import get_locale_manager
        from Data.ui_translations import LANGUAGES
        locale = get_locale_manager()
        self.language_combo = QComboBox(prefs_container)
        self.language_combo.setObjectName('interfaceLanguageCombo')
        self.language_combo.setProperty('ppsNoTranslation', True)
        self.language_combo.setMinimumWidth(220)
        for code, label in LANGUAGES:
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(locale.language))
        self.language_combo.currentIndexChanged.connect(
            lambda index: locale.set_language(self.language_combo.itemData(index)))
        locale.language_changed.connect(self._sync_language_choice)
        prefs_layout.addWidget(QLabel('Language', prefs_container), 0, 0)
        prefs_layout.addWidget(self.language_combo, 0, 1)
        language_hint = QLabel('Interface language only; papers and your answers stay unchanged.', prefs_container)
        language_hint.setWordWrap(True)
        prefs_layout.addWidget(language_hint, 1, 0, 1, 2)
        prefs_layout.addWidget(self._build_section_header('App behavior', prefs_container), 2, 0, 1, 2)
        # Keep the compatibility setters for the future return of this control.
        self.answer_panel_position_combo = None
        self.answer_panel_position_pref_label = None

        self.sound_pref_label = QLabel("Sound", prefs_container)
        self.scale_pref_label = QLabel("Scale Overlay", prefs_container)
        self.system_accent_pref_label = QLabel("System Accent", prefs_container)

        prefs_layout.addWidget(self.sound_pref_label, 3, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        prefs_layout.addWidget(self.sound_toggle, 3, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prefs_layout.addWidget(self.scale_pref_label, 8, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        prefs_layout.addWidget(self.scale_toggle, 8, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prefs_layout.addWidget(self.system_accent_pref_label, 4, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        prefs_layout.addWidget(self.system_accent_toggle, 4, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.startup_animation_toggle = self._add_preference_toggle(
            prefs_layout, prefs_container, 5, "Show Startup Animation", "show_startup_animation", True)
        self.fullscreen_startup_toggle = self._add_preference_toggle(
            prefs_layout, prefs_container, 6, "Full Screen on Startup", "full_screen_on_startup", True)
        self.startup_animation_toggle.setToolTip("Show the themed loading animation when opening Studio.")
        self.fullscreen_startup_toggle.setToolTip("Open the main window in full-screen mode. Applies on the next launch.")

        self.scale_pref_label.setVisible(False)
        layout.addWidget(prefs_container)

        layout.addWidget(self._build_section_header("Actions", self.general_page))
        self.user_docs_btn = QPushButton("Open Docs", self.general_page)
        self.user_docs_btn.setObjectName("settingsActionButton")
        self.user_docs_btn.clicked.connect(self._open_docs)
        layout.addWidget(
            self._build_action_row(
                parent=self.general_page,
                title_text="User Documentation",
                description_text="Open quick usage docs and shortcuts.",
                action_button=self.user_docs_btn,
            )
        )

        self.ai_config_btn = QPushButton("Open AI Config", self.general_page)
        self.ai_config_btn.setObjectName("settingsActionButton")
        self.ai_config_btn.clicked.connect(self._show_ai_config_page)
        layout.addWidget(
            self._build_action_row(
                parent=self.general_page,
                title_text="AI Configuration",
                description_text="Go to AI Config section.",
                action_button=self.ai_config_btn,
            )
        )

        layout.addStretch(1)
        footer = QWidget(self.general_page)
        footer.setObjectName("settingsSectionContainer")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)
        self.build_version_label = QLabel(f"Build Version: {APP_VERSION}", footer)
        self.build_version_label.setObjectName("settingsVersionLabel")
        footer_layout.addWidget(self.build_version_label)
        self.sourcing_notice_label = QLabel(SOURCING_NOTICE, footer)
        self.sourcing_notice_label.setObjectName("settingsSourcingNotice")
        self.sourcing_notice_label.setTextFormat(Qt.TextFormat.PlainText)
        self.sourcing_notice_label.setWordWrap(True)
        self.sourcing_notice_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        footer_layout.addWidget(self.sourcing_notice_label)
        page_layout.addWidget(footer)

    def _build_appearance_page(self) -> None:
        layout = QVBoxLayout(self.appearance_page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        layout.addWidget(self._build_section_header("Appearance", self.appearance_page))

        font_row = QWidget(self.appearance_page)
        font_row_layout = QGridLayout(font_row)
        font_row_layout.setContentsMargins(0, 0, 0, 0)
        font_row_layout.setHorizontalSpacing(12)
        font_row_layout.setVerticalSpacing(8)
        self.font_label = QLabel("Global Font", self.appearance_page)
        self.font_label.setObjectName("settingsPreferenceLabel")
        self.font_combo = QComboBox(self.appearance_page)
        self.font_combo.setMinimumWidth(220)
        self.font_combo.currentTextChanged.connect(self._on_font_selected_changed)
        font_row_layout.addWidget(self.font_label, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        font_row_layout.addWidget(self.font_combo, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        font_row_layout.setColumnStretch(0, 1)
        font_row_layout.setColumnStretch(1, 0)
        layout.addWidget(font_row)

        random_theme_row = QWidget(self.appearance_page)
        random_theme_row_layout = QGridLayout(random_theme_row)
        random_theme_row_layout.setContentsMargins(0, 0, 0, 0)
        random_theme_row_layout.setHorizontalSpacing(12)
        random_theme_row_layout.setVerticalSpacing(8)
        self.random_theme_label = QLabel("Random Theme on Startup", self.appearance_page)
        self.random_theme_label.setObjectName("settingsPreferenceLabel")
        self.random_theme_toggle = ToggleSwitch(self.appearance_page)
        self.random_theme_toggle.setObjectName("settingsBodyToggle")
        self.random_theme_toggle.toggled.connect(self._on_random_theme_toggled_changed)
        self._suppress_random_theme_signal = True
        self.random_theme_toggle.setChecked(False)
        self._suppress_random_theme_signal = False
        random_theme_row_layout.addWidget(self.random_theme_label, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        random_theme_row_layout.addWidget(self.random_theme_toggle, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        random_theme_row_layout.setColumnStretch(0, 1)
        random_theme_row_layout.setColumnStretch(1, 0)
        layout.addWidget(random_theme_row)

        creator_row = QWidget(self.appearance_page)
        creator_layout = QGridLayout(creator_row)
        creator_layout.setContentsMargins(0, 0, 0, 0)
        creator_layout.setColumnStretch(0, 1)
        self.custom_theme_creator_toggle = self._add_preference_toggle(
            creator_layout, creator_row, 0, "Custom Theme Creator  ·  Beta",
            "custom_theme_creator_enabled", False)
        self.custom_theme_creator_toggle.setToolTip("Enable the experimental custom theme editor in the gallery.")
        layout.addWidget(creator_row)

        layout.addWidget(self._build_section_header("Theme Cards", self.appearance_page))
        self.theme_hint_label = QLabel("Pick a theme from the gallery. Cards show primary and secondary palette colors.", self.appearance_page)
        self.theme_hint_label.setObjectName("settingsHintLabel")
        self.theme_hint_label.setWordWrap(True)
        layout.addWidget(self.theme_hint_label)

        self.theme_search_input = QLineEdit(self.appearance_page)
        self.theme_search_input.setObjectName("settingsThemeSearchInput")
        self.theme_search_input.setPlaceholderText("Search themes...")
        self.theme_search_input.textChanged.connect(self._filter_theme_list)
        layout.addWidget(self.theme_search_input)

        self.theme_scroll_area = QScrollArea(self.appearance_page)
        self.theme_scroll_area.setObjectName("settingsThemeScroll")
        self.theme_scroll_area.setWidgetResizable(True)
        self.theme_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.theme_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.theme_scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.theme_cards_container = QWidget(self.theme_scroll_area)
        self.theme_cards_layout = QVBoxLayout(self.theme_cards_container)
        self.theme_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.theme_cards_layout.setSpacing(10)

        self.theme_empty_state_label = QLabel("No themes found", self.theme_cards_container)
        self.theme_empty_state_label.setObjectName("settingsThemeEmptyState")
        self.theme_empty_state_label.setVisible(False)
        self.theme_cards_layout.addWidget(self.theme_empty_state_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.theme_sections_container = QWidget(self.theme_cards_container)
        self.theme_sections_layout = QVBoxLayout(self.theme_sections_container)
        self.theme_sections_layout.setContentsMargins(0, 0, 0, 0)
        self.theme_sections_layout.setSpacing(20)
        self.theme_cards_layout.addWidget(self.theme_sections_container, 0)
        self.theme_cards_layout.addStretch(1)
        self.theme_scroll_area.setWidget(self.theme_cards_container)
        layout.addWidget(self.theme_scroll_area, 1)

    def _build_ai_page(self) -> None:
        layout = QVBoxLayout(self.ai_page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        layout.addWidget(self._build_section_header("AI Config", self.ai_page))
        desc = QLabel("Configure Groq API credentials and model IDs used by grading.", self.ai_page)
        desc.setObjectName("settingsHintLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 1)

        self.ai_api_key_label = QLabel("Groq API Key", self.ai_page)
        self.ai_api_key_label.setObjectName("settingsPreferenceLabel")
        self.ai_api_key_input = QLineEdit(self.ai_page)
        self.ai_api_key_input.setPlaceholderText("gsk_...")
        self.ai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.ai_text_model_label = QLabel("Text Model", self.ai_page)
        self.ai_text_model_label.setObjectName("settingsPreferenceLabel")
        self.ai_text_model_input = QLineEdit(self.ai_page)
        self.ai_text_model_input.setPlaceholderText("meta-llama/llama-4-scout-17b-16e-instruct")

        self.ai_vision_model_label = QLabel("Vision Model", self.ai_page)
        self.ai_vision_model_label.setObjectName("settingsPreferenceLabel")
        self.ai_vision_model_input = QLineEdit(self.ai_page)
        self.ai_vision_model_input.setPlaceholderText("meta-llama/llama-4-scout-17b-16e-instruct")

        form.addWidget(self.ai_api_key_label, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.addWidget(self.ai_api_key_input, 0, 1)
        form.addWidget(self.ai_text_model_label, 1, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.addWidget(self.ai_text_model_input, 1, 1)
        form.addWidget(self.ai_vision_model_label, 2, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.addWidget(self.ai_vision_model_input, 2, 1)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch(1)
        self.ai_page_refresh_btn = QPushButton("Refresh", self.ai_page)
        self.ai_page_refresh_btn.clicked.connect(self._refresh_ai_page_values)
        self.ai_page_save_btn = QPushButton("Save", self.ai_page)
        self.ai_page_save_btn.setObjectName("settingsActionButton")
        self.ai_page_save_btn.clicked.connect(self._save_ai_page_values)
        button_row.addWidget(self.ai_page_refresh_btn)
        button_row.addWidget(self.ai_page_save_btn)
        layout.addLayout(button_row)

        self.ai_page_status_label = QLabel("", self.ai_page)
        self.ai_page_status_label.setObjectName("settingsHintLabel")
        self.ai_page_status_label.setWordWrap(True)
        layout.addWidget(self.ai_page_status_label)
        layout.addStretch(1)

    def _build_action_row(self, parent: QWidget, title_text: str, description_text: str, action_button: QPushButton) -> QWidget:
        row = QWidget(parent)
        row.setObjectName("settingsActionRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title = QLabel(str(title_text or ""), row)
        title.setObjectName("settingsActionTitle")
        desc = QLabel(str(description_text or ""), row)
        desc.setObjectName("settingsActionDescription")
        desc.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(desc)

        action_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        action_button.setMinimumWidth(126)
        action_button.setMinimumHeight(34)

        row_layout.addLayout(text_col, 1)
        row_layout.addWidget(action_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return row

    def _show_ai_config_page(self) -> None:
        if callable(self._on_refresh_ai):
            values = self._on_refresh_ai()
            if isinstance(values, tuple) and len(values) == 3:
                self.set_ai_values(values[0], values[1], values[2])
        self.nav_list.setCurrentRow(2)

    def _save_ai_page_values(self) -> None:
        self.ai_page_status_label.setText("")
        if not callable(self._on_save_ai):
            self.ai_page_status_label.setText("AI settings handler is unavailable.")
            return
        ok = bool(
            self._on_save_ai(
                self.ai_api_key_input.text(),
                self.ai_text_model_input.text(),
                self.ai_vision_model_input.text(),
            )
        )
        self.ai_page_status_label.setText("Saved AI settings." if ok else "Failed to save AI settings.")

    def _refresh_ai_page_values(self) -> None:
        self.ai_page_status_label.setText("")
        if not callable(self._on_refresh_ai):
            self.ai_page_status_label.setText("AI settings handler is unavailable.")
            return
        values = self._on_refresh_ai()
        if isinstance(values, tuple) and len(values) == 3:
            self.set_ai_values(values[0], values[1], values[2])
            self.ai_page_status_label.setText("Loaded current AI settings.")

    def _open_docs(self) -> None:
        self.docsRequested.emit()
        if callable(self._on_docs_requested):
            self._on_docs_requested()
        self._suppress_next_user_hidden = True
        self.hide()
        if callable(self._on_open_docs):
            self._on_open_docs()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._hidden_for_custom_editor = False
        editor = self.__dict__.get("_custom_theme_editor_dialog")
        if isinstance(editor, CustomThemeEditorDialog) and editor.isVisible():
            editor.hide()
        super().closeEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self.profile_editor.save_name()
        super().hideEvent(event)
        suppressed = bool(self._suppress_next_user_hidden)
        self._suppress_next_user_hidden = False
        if self._hidden_for_custom_editor:
            return
        editor = self.__dict__.get("_custom_theme_editor_dialog")
        if isinstance(editor, CustomThemeEditorDialog) and editor.isVisible():
            editor.hide()
        if suppressed:
            return
        self.userHidden.emit()
        if callable(self._on_user_hidden):
            self._on_user_hidden()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):  # type: ignore[override]
        return super().eventFilter(watched, event)

    def _is_custom_theme_name(self, theme_name: str) -> bool:
        candidate = str(theme_name or "").strip()
        if not candidate:
            return False
        manager = get_theme_manager()
        try:
            return bool(manager.is_custom_theme(candidate))
        except Exception:
            return False

    def _clear_theme_sections(self) -> None:
        while self.theme_sections_layout.count():
            item = self.theme_sections_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if isinstance(widget, QWidget):
                widget.deleteLater()
        self._theme_section_titles = []
        self._theme_section_widgets.clear()
        self._theme_section_layouts.clear()
        self._theme_card_sections.clear()

    def _ordered_theme_sections(self, theme_names: List[str]) -> List[Tuple[str, List[str]]]:
        entry = self._theme_creator_entry_name()
        deduped: List[str] = []
        seen: set[str] = set()
        for raw_name in theme_names:
            candidate = str(raw_name or "").strip()
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)

        known_sections: Dict[str, Dict[str, str]] = {
            section_name: {}
            for section_name, _ in self.THEME_SECTION_SPECS
        }
        section_lookup: Dict[str, str] = {}
        for section_name, ordered_names in self.THEME_SECTION_SPECS:
            for name in ordered_names:
                section_lookup[name.casefold()] = section_name

        custom_names: List[str] = []
        extras: List[str] = []
        for candidate in deduped:
            key = candidate.casefold()
            if key == entry.casefold():
                continue
            if self._is_custom_theme_name(candidate):
                custom_names.append(candidate)
                continue
            section_name = section_lookup.get(key)
            if section_name:
                known_sections.setdefault(section_name, {})
                known_sections[section_name][key] = candidate
                continue
            extras.append(candidate)

        sections: List[Tuple[str, List[str]]] = []
        for section_name, ordered_names in self.THEME_SECTION_SPECS:
            if section_name == "Custom":
                unique_custom = list(dict.fromkeys(custom_names))
                custom_sorted = sorted(unique_custom, key=str.casefold)
                section_themes = ([entry] if self._custom_theme_creator_enabled else []) + custom_sorted
            else:
                present = known_sections.get(section_name, {})
                section_themes = [present[name.casefold()] for name in ordered_names if name.casefold() in present]
            if section_themes:
                sections.append((section_name, section_themes))

        extra_unique = list(dict.fromkeys(extras))
        if extra_unique:
            sections.append((self.EXTRA_THEMES_SECTION, sorted(extra_unique, key=str.casefold)))

        return sections

    def theme_section_titles(self) -> List[str]:
        return list(self._theme_section_titles)

    def theme_names_for_section(self, section_name: str) -> List[str]:
        layout = self._theme_section_layouts.get(str(section_name or ""))
        if layout is None:
            return []
        names: List[str] = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, ThemeCardWidget):
                names.append(widget.theme_name())
        return names

    def set_theme_names(self, theme_names: List[str]) -> None:
        available = set(get_theme_manager().theme_names())
        names = [str(name) for name in theme_names if str(name) in available]
        if names == self._theme_names and self._theme_cards:
            return

        previously_selected = self._selected_theme_text()
        self._theme_names = names
        display_names = list(names)
        entry = self._theme_creator_entry_name()
        if self._custom_theme_creator_enabled and all(name.casefold() != entry.casefold() for name in display_names):
            display_names.append(entry)

        self._theme_cards.clear()
        self._selected_theme_name = ""
        self._clear_theme_sections()

        for section_title, section_themes in self._ordered_theme_sections(display_names):
            section_widget = QWidget(self.theme_sections_container)
            section_widget.setObjectName("settingsThemeSection")
            section_layout = QVBoxLayout(section_widget)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(8)

            section_label = QLabel(section_title, section_widget)
            section_label.setObjectName("settingsThemeGroupLabel")
            section_layout.addWidget(section_label)

            cards_container = QWidget(section_widget)
            cards_layout = FlowLayout(cards_container, margin=0, h_spacing=12, v_spacing=12)
            cards_container.setLayout(cards_layout)
            section_layout.addWidget(cards_container)

            self.theme_sections_layout.addWidget(section_widget)
            self._theme_section_titles.append(section_title)
            self._theme_section_widgets[section_title] = section_widget
            self._theme_section_layouts[section_title] = cards_layout

            for name in section_themes:
                primary, secondary = self._theme_colors_for(name)
                is_creator = name.casefold() == entry.casefold()
                card = ThemeCardWidget(
                    name,
                    primary_color=primary,
                    secondary_color=secondary,
                    is_creator=is_creator,
                    parent=cards_container,
                )
                card.clicked.connect(self._on_theme_card_clicked)
                card.contextRequested.connect(self._on_theme_card_context_requested)
                cards_layout.addWidget(card)
                key = name.casefold()
                self._theme_cards[key] = card
                self._theme_card_sections[key] = section_title

        self._apply_theme_cards_runtime_theme()
        if previously_selected:
            self.set_selected_theme(previously_selected)
        elif names:
            self.set_selected_theme(names[0])
        self._filter_theme_list(self.theme_search_input.text())
        self._sync_delete_theme_button_state()

    def _theme_colors_for(self, theme_name: str) -> Tuple[str, str]:
        entry = self._theme_creator_entry_name()
        if str(theme_name).casefold() == entry.casefold():
            return "#4B5563", "#9CA3AF"
        manager = get_theme_manager()
        try:
            tokens = manager.get_theme_tokens(str(theme_name or ""))
        except Exception:
            tokens = {}
        primary = str(tokens.get("PRIMARY") or tokens.get("ACCENT_CYAN") or "#4CC9F0")
        secondary = str(tokens.get("SECONDARY") or tokens.get("PRIMARY_HOVER") or "#A855F7")
        if theme_name in CLASSIC_THEME_NAMES:
            # Classic previews show the actual canvas beside its main accent.
            primary, secondary = tokens["BG_DARK"], tokens["PRIMARY"]
        if not QColor(primary).isValid():
            primary = "#4CC9F0"
        if not QColor(secondary).isValid():
            secondary = "#A855F7"
        return primary, secondary

    def _apply_theme_cards_runtime_theme(self) -> None:
        accent = str(getattr(Colors, "ACCENT_CYAN", "") or Colors.PRIMARY)
        card_bg = _mix_hex(str(Colors.BG_CARD), str(Colors.BG_MEDIUM), 0.15)
        card_bg_selected = _mix_hex(card_bg, accent, 0.22)
        card_border = _mix_hex(str(Colors.BG_LIGHT), str(Colors.BG_DARK), 0.34)
        text_color = Colors.contrast_text_for_bg(card_bg)
        muted_color = _mix_hex(text_color, card_bg, 0.48)
        for card in self._theme_cards.values():
            card.apply_runtime_theme(
                accent=accent,
                text_color=text_color,
                muted_color=muted_color,
                card_bg=card_bg,
                card_bg_selected=card_bg_selected,
                card_border=card_border,
            )

    def set_font_options(self, font_names: list[str]) -> None:
        names = [str(name) for name in font_names if str(name).strip()]
        if not names:
            names = ["Default"]
        if names[0].casefold() != "default":
            names.insert(0, "Default")
        deduped: list[str] = []
        seen: set[str] = set()
        for name in names:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(name)
        if deduped == self._font_names:
            return
        selected = self.font_combo.currentText()
        self._font_names = deduped
        self._suppress_font_signal = True
        try:
            self.font_combo.clear()
            self.font_combo.addItems(deduped)
        finally:
            self._suppress_font_signal = False
        self.set_selected_font(selected or "Default")

    def set_selected_font(self, font_name: str) -> None:
        target = str(font_name or "").strip() or "Default"
        self._suppress_font_signal = True
        try:
            for index in range(self.font_combo.count()):
                text = self.font_combo.itemText(index)
                if text.casefold() != target.casefold():
                    continue
                self.font_combo.setCurrentIndex(index)
                return
            if self.font_combo.count() > 0:
                self.font_combo.setCurrentIndex(0)
        finally:
            self._suppress_font_signal = False


    def _sync_language_choice(self, code):
        blocker = QSignalBlocker(self.language_combo)
        self.language_combo.setCurrentIndex(self.language_combo.findData(code))
        del blocker

    def set_sound_enabled(self, enabled: bool) -> None:
        self._suppress_sound_signal = True
        try:
            self.sound_toggle.setChecked(bool(enabled))
        finally:
            self._suppress_sound_signal = False

    def set_scale_enabled(self, enabled: bool) -> None:
        self._suppress_scale_signal = True
        try:
            self.scale_toggle.setChecked(bool(enabled))
        finally:
            self._suppress_scale_signal = False

    def set_system_accent_enabled(self, enabled: bool) -> None:
        self._suppress_system_accent_signal = True
        try:
            self.system_accent_toggle.setChecked(bool(enabled))
        finally:
            self._suppress_system_accent_signal = False

    def set_random_theme_enabled(self, enabled: bool) -> None:
        self._suppress_random_theme_signal = True
        try:
            self.random_theme_toggle.setChecked(bool(enabled))
        finally:
            self._suppress_random_theme_signal = False

    @staticmethod
    def _normalize_answer_panel_position(position: str) -> str:
        normalized = str(position or "").strip().lower()
        return normalized if normalized in {"left", "right", "bottom"} else "bottom"

    def set_answer_panel_position(self, position: str) -> None:
        normalized = self._normalize_answer_panel_position(position)
        combo = getattr(self, "answer_panel_position_combo", None)
        if not isinstance(combo, QComboBox):
            return
        idx = combo.findData(normalized)
        if idx < 0:
            idx = combo.findData("bottom")
        self._suppress_answer_panel_position_signal = True
        try:
            if idx >= 0:
                combo.setCurrentIndex(idx)
        finally:
            self._suppress_answer_panel_position_signal = False

    def set_answer_panel_position_control_state(self, enabled: bool, tooltip: str = "", *, visible: bool = True) -> None:
        combo = getattr(self, "answer_panel_position_combo", None)
        label = getattr(self, "answer_panel_position_pref_label", None)
        if isinstance(label, QWidget):
            label.setVisible(bool(visible))
        if not isinstance(combo, QComboBox):
            return
        combo.setVisible(bool(visible))
        combo.setEnabled(bool(enabled) and bool(visible))
        if tooltip:
            combo.setToolTip(str(tooltip))
        elif enabled:
            combo.setToolTip("Choose where the exam answer panel appears.")
        else:
            combo.setToolTip("Answer panel position is unavailable.")


    def set_sound_control_state(self, enabled: bool, tooltip: str = "", *, visible: bool = True) -> None:
        show_toggle = bool(visible)
        label = getattr(self, "sound_pref_label", None)
        if isinstance(label, QWidget):
            label.setVisible(show_toggle)
        self.sound_toggle.setVisible(show_toggle)
        self.sound_toggle.setEnabled(bool(enabled) and show_toggle)
        if tooltip:
            self.sound_toggle.setToolTip(str(tooltip))
        elif enabled:
            self.sound_toggle.setToolTip("Enable UI sounds and easter egg audio.")
        else:
            self.sound_toggle.setToolTip("Sound is unavailable.")

    def set_scale_control_state(self, enabled: bool, tooltip: str = "", *, visible: bool = True) -> None:
        show_toggle = bool(visible)
        label = getattr(self, "scale_pref_label", None)
        if isinstance(label, QWidget):
            label.setVisible(show_toggle)
        self.scale_toggle.setVisible(show_toggle)
        self.scale_toggle.setEnabled(bool(enabled) and show_toggle)
        if tooltip:
            self.scale_toggle.setToolTip(str(tooltip))
        elif enabled:
            self.scale_toggle.setToolTip("Show centimeter scale overlay in exam mode.")
        else:
            self.scale_toggle.setToolTip("Scale overlay is unavailable.")

    def set_system_accent_control_state(self, enabled: bool, tooltip: str = "", *, visible: bool = True) -> None:
        show_toggle = bool(visible)
        label = getattr(self, "system_accent_pref_label", None)
        if isinstance(label, QWidget):
            label.setVisible(show_toggle)
        self.system_accent_toggle.setVisible(show_toggle)
        self.system_accent_toggle.setEnabled(bool(enabled) and show_toggle)
        if tooltip:
            self.system_accent_toggle.setToolTip(str(tooltip))
        elif enabled:
            self.system_accent_toggle.setToolTip("Use operating system accent colors when available.")
        else:
            self.system_accent_toggle.setToolTip("System accent matching is unavailable.")

    def set_selected_theme(self, theme_name: str) -> None:
        target = str(theme_name or "").strip()
        if not target:
            return
        if self._selected_theme_name and self._selected_theme_name.casefold() == target.casefold():
            matched = self._theme_cards.get(target.casefold())
            if matched is None:
                return
            self.theme_scroll_area.ensureWidgetVisible(matched)
            self._sync_delete_theme_button_state()
            return
        matched: Optional[ThemeCardWidget] = None
        for card in self._theme_cards.values():
            is_match = card.theme_name().casefold() == target.casefold()
            card.set_selected(is_match)
            if is_match:
                matched = card
        if matched is None:
            return
        self._selected_theme_name = matched.theme_name()
        self.theme_scroll_area.ensureWidgetVisible(matched)
        self._sync_delete_theme_button_state()

    def set_ai_values(self, api_key: str, text_model: str, vision_model: str) -> None:
        values = (
            str(api_key or ""),
            str(text_model or ""),
            str(vision_model or ""),
        )
        if values == self._cached_ai_values:
            return
        self._cached_ai_values = values
        self.ai_api_key_input.setText(self._cached_ai_values[0])
        self.ai_text_model_input.setText(self._cached_ai_values[1])
        self.ai_vision_model_input.setText(self._cached_ai_values[2])
        if self._ai_dialog is not None:
            self._ai_dialog.set_ai_values(*self._cached_ai_values)

    def _selected_theme_text(self) -> str:
        return str(self._selected_theme_name or "")

    def _is_custom_theme_candidate(self, theme_name: str) -> bool:
        candidate = str(theme_name or "").strip()
        if not candidate:
            return False
        if candidate.casefold() == self._theme_creator_entry_name().casefold():
            return False
        return self._is_custom_theme_name(candidate)

    def _sync_delete_theme_button_state(self) -> None:
        button = getattr(self, "delete_theme_btn", None)
        if not isinstance(button, QPushButton):
            return
        candidate = self._selected_theme_text()
        button.setEnabled(self._is_custom_theme_candidate(candidate))

    def _delete_selected_theme(self) -> None:
        self._delete_theme_by_name(self._selected_theme_text())

    def _delete_theme_by_name(self, theme_name: str) -> None:
        candidate = str(theme_name or "").strip()
        if not self._is_custom_theme_candidate(candidate):
            return
        reply = QMessageBox.question(
            self,
            "Delete Custom Theme",
            f"Delete custom theme '{candidate}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not callable(self._on_delete_theme):
            QMessageBox.warning(self, "Delete Theme", "Theme delete handler is unavailable.")
            return
        deleted = bool(self._on_delete_theme(candidate))
        if not deleted:
            QMessageBox.warning(self, "Delete Theme", f"Could not delete '{candidate}'.")
            return
        self.set_theme_names(get_theme_manager().theme_names())
        self.set_selected_theme(str(get_theme_manager().current_theme() or "Default"))
        self._sync_delete_theme_button_state()

    def _on_theme_card_context_requested(self, theme_name: str, global_pos: QPoint) -> None:
        candidate = str(theme_name or "").strip()
        if not self._is_custom_theme_candidate(candidate):
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete Custom Theme")
        chosen = menu.exec(global_pos)
        if chosen == delete_action:
            self._delete_theme_by_name(candidate)

    def _filter_theme_list(self, text: str) -> None:
        needle = str(text or "").strip().casefold()
        first_visible: Optional[ThemeCardWidget] = None
        visible_sections: Dict[str, bool] = {section: False for section in self._theme_section_titles}
        for card in self._theme_cards.values():
            visible = not needle or needle in card.theme_name().casefold()
            card.setVisible(visible)
            if visible and first_visible is None:
                first_visible = card
            if visible:
                section_name = self._theme_card_sections.get(card.theme_name().casefold())
                if section_name:
                    visible_sections[section_name] = True

        for section_name, widget in self._theme_section_widgets.items():
            widget.setVisible(bool(visible_sections.get(section_name, False)))

        has_matches = any(visible_sections.values())
        self.theme_empty_state_label.setVisible(not has_matches)

        current = self._theme_cards.get(self._selected_theme_name.casefold())
        if current is not None and not current.isVisible() and first_visible is not None:
            self._selected_theme_name = ""
            self.set_selected_theme(first_visible.theme_name())
        self.theme_sections_container.updateGeometry()
        self._sync_delete_theme_button_state()

    def _on_theme_card_clicked(self, theme_name: str) -> None:
        if self._suppress_theme_signal:
            return
        candidate = str(theme_name or "").strip()
        if not candidate:
            return
        if candidate.casefold() == self._theme_creator_entry_name().casefold():
            self._open_custom_theme_editor()
            previous = str(self._last_emitted_theme or "").strip()
            if previous and previous.casefold() != self._theme_creator_entry_name().casefold():
                self.set_selected_theme(previous)
            else:
                self.set_selected_theme(str(get_theme_manager().current_theme() or "Default"))
            self._sync_delete_theme_button_state()
            return
        self.set_selected_theme(candidate)
        self._emit_theme_selection(candidate)
        self._sync_delete_theme_button_state()

    def _emit_theme_selection(self, theme_name: str) -> None:
        candidate = str(theme_name or "").strip()
        if not candidate or candidate.casefold() == self._theme_creator_entry_name().casefold():
            return
        if self._last_emitted_theme.casefold() == candidate.casefold():
            return
        self._last_emitted_theme = candidate
        if callable(self._on_theme_selected):
            self._on_theme_selected(candidate)

    def _on_custom_theme_saved(self, theme_name: str) -> None:
        saved_name = str(theme_name or "").strip()
        if not saved_name:
            return
        self.set_theme_names(get_theme_manager().theme_names())
        self.set_selected_theme(saved_name)
        self._last_emitted_theme = saved_name
        if callable(self._on_theme_selected):
            self._on_theme_selected(saved_name)
        editor = self.__dict__.get("_custom_theme_editor_dialog")
        if isinstance(editor, CustomThemeEditorDialog) and editor.isVisible():
            editor.hide()
        self._sync_delete_theme_button_state()

    def _theme_creator_entry_name(self) -> str:
        return str(self.CUSTOM_THEME_CREATOR_ENTRY)

    def _target_root_widget(self) -> Optional[QWidget]:
        parent_root = self.parentWidget()
        if isinstance(parent_root, QWidget):
            parent_root = parent_root.window()
        if isinstance(parent_root, QWidget):
            return parent_root
        return None

    def _ensure_custom_theme_editor_dialog(self) -> None:
        if self._custom_theme_editor_dialog is not None:
            self._custom_theme_editor_dialog.set_target_root_widget(self._target_root_widget())
            return
        dialog = CustomThemeEditorDialog(
            self,
            on_theme_saved=self._on_custom_theme_saved,
            on_closed=self._on_custom_theme_editor_hidden,
            target_root_widget=self._target_root_widget(),
        )
        self._custom_theme_editor_dialog = dialog

    def _open_custom_theme_editor(self) -> None:
        if not self._custom_theme_creator_enabled:
            return
        self._ensure_custom_theme_editor_dialog()
        dialog = self._custom_theme_editor_dialog
        if dialog is None:
            return
        self._hidden_for_custom_editor = True
        self.hide()
        dialog.apply_runtime_theme()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_custom_theme_editor_hidden(self) -> None:
        self._hidden_for_custom_editor = False
        parent_root = self.parentWidget()
        if isinstance(parent_root, QWidget) and not parent_root.isVisible():
            return
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_font_selected_changed(self, text: str) -> None:
        if self._suppress_font_signal:
            return
        if callable(self._on_font_selected):
            self._on_font_selected(str(text or "Default"))


    def _add_preference_toggle(self, layout, parent, row, label_text, key, default):
        label = QLabel(label_text, parent)
        label.setObjectName("settingsPreferenceLabel")
        toggle = ToggleSwitch(parent)
        toggle.setObjectName("settingsBodyToggle")
        toggle.setAccessibleName(label_text)
        toggle.setChecked(default)
        toggle._animation.stop()
        toggle.slideProgress = 1.0 if default else 0.0
        self._preference_toggles[key] = toggle
        toggle.toggled.connect(lambda enabled: self._preference_changed(key, enabled))
        layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(toggle, row, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return toggle

    def set_preferences(self, *, show_startup_animation, full_screen_on_startup, custom_theme_creator_enabled):
        values = dict(show_startup_animation=show_startup_animation,
                      full_screen_on_startup=full_screen_on_startup,
                      custom_theme_creator_enabled=custom_theme_creator_enabled)
        for key, value in values.items():
            toggle = self._preference_toggles[key]
            if toggle.isChecked() == bool(value):
                # Synchronizing a user click must not stop its running animation.
                continue
            blocked = toggle.blockSignals(True)
            try:
                toggle.setChecked(bool(value))
                toggle._animation.stop()
                toggle.slideProgress = 1.0 if value else 0.0
            finally:
                toggle.blockSignals(blocked)
        self._set_creator_enabled(bool(custom_theme_creator_enabled))

    def _set_creator_enabled(self, enabled):
        if self._custom_theme_creator_enabled == enabled:
            return
        self._custom_theme_creator_enabled = enabled
        if not enabled and self._custom_theme_editor_dialog is not None:
            self._custom_theme_editor_dialog.close()
        names = list(self._theme_names)
        self._theme_names = []  # Rebuild the gallery when only the opt-in changes.
        self.set_theme_names(names)

    def _preference_changed(self, key, enabled):
        if key == "custom_theme_creator_enabled":
            self._set_creator_enabled(bool(enabled))
        if callable(self._on_preference_toggled):
            self._on_preference_toggled(key, bool(enabled))

    def _on_sound_toggled_changed(self, enabled: bool) -> None:
        if self._suppress_sound_signal:
            return
        if callable(self._on_sound_toggled):
            self._on_sound_toggled(bool(enabled))

    def _on_scale_toggled_changed(self, enabled: bool) -> None:
        if self._suppress_scale_signal:
            return
        if callable(self._on_scale_toggled):
            self._on_scale_toggled(bool(enabled))

    def _on_system_accent_toggled_changed(self, enabled: bool) -> None:
        if self._suppress_system_accent_signal:
            return
        if callable(self._on_system_accent_toggled):
            self._on_system_accent_toggled(bool(enabled))

    def _on_answer_panel_position_combo_changed(self, index: int) -> None:
        if self._suppress_answer_panel_position_signal:
            return
        combo = getattr(self, "answer_panel_position_combo", None)
        if not isinstance(combo, QComboBox):
            return
        value = self._normalize_answer_panel_position(str(combo.itemData(index) or "bottom"))
        if callable(self._on_answer_panel_position_changed):
            self._on_answer_panel_position_changed(value)

    def _on_random_theme_toggled_changed(self, enabled: bool) -> None:
        if self._suppress_random_theme_signal:
            return
        if callable(self._on_random_theme_toggled):
            self._on_random_theme_toggled(bool(enabled))

    def apply_runtime_theme(self) -> None:
        accent = str(getattr(Colors, "ACCENT_CYAN", "") or Colors.SECONDARY)
        panel_bg = _opaque_settings_panel_bg()
        signature = (get_theme_manager().current_theme(), get_theme_manager()._theme_revision, tuple(self._theme_cards))
        if getattr(self, '_appearance_signature', None) == signature:
            return
        self._appearance_signature = signature
        pages_bg = _mix_hex(str(Colors.BG_CARD), str(Colors.BG_MEDIUM), 0.12)
        nav_bg = _mix_hex(str(Colors.BG_MEDIUM), panel_bg, 0.22)
        nav_item_hover_bg = _mix_hex(nav_bg, accent, 0.12)
        nav_item_selected_bg = _mix_hex(nav_bg, accent, 0.24)
        input_bg = _mix_hex(str(Colors.BG_LIGHT), pages_bg, 0.2)
        action_row_bg = _mix_hex(str(Colors.BG_CARD), pages_bg, 0.15)
        neutral_button_bg = _mix_hex(str(Colors.BG_LIGHT), pages_bg, 0.24)
        neutral_button_hover_bg = _mix_hex(neutral_button_bg, accent, 0.12)
        neutral_button_disabled_bg = _mix_hex(neutral_button_bg, panel_bg, 0.55)
        border_soft = _mix_hex(str(Colors.BG_LIGHT), str(Colors.BG_DARK), 0.36)
        border_strong = _mix_hex(accent, panel_bg, 0.42)
        scroll_track = _mix_hex(nav_bg, panel_bg, 0.28)
        scroll_handle = _mix_hex(accent, nav_bg, 0.4)

        text_color = Colors.contrast_text_for_bg(pages_bg)
        muted_text = _mix_hex(text_color, pages_bg, 0.48)
        nav_text = Colors.contrast_text_for_bg(nav_bg)
        nav_muted_text = _mix_hex(nav_text, nav_bg, 0.44)
        nav_hover_text = Colors.contrast_text_for_bg(nav_item_hover_bg)
        nav_selected_text = Colors.contrast_text_for_bg(nav_item_selected_bg)
        input_text = Colors.contrast_text_for_bg(input_bg)
        action_row_text = Colors.contrast_text_for_bg(action_row_bg)
        action_row_muted = _mix_hex(action_row_text, action_row_bg, 0.46)
        neutral_button_text = Colors.contrast_text_for_bg(neutral_button_bg)
        neutral_button_hover_text = Colors.contrast_text_for_bg(neutral_button_hover_bg)
        neutral_button_disabled_text = _mix_hex(neutral_button_text, neutral_button_disabled_bg, 0.5)
        popup_selection_bg = _mix_hex(input_bg, accent, 0.28)
        popup_selection_text = Colors.contrast_text_for_bg(popup_selection_bg)
        section_text = _mix_hex(accent, text_color, 0.18)

        button_bg = str(Colors.PRIMARY)
        button_hover = str(Colors.PRIMARY_HOVER)
        button_text = Colors.contrast_text_for_bg(button_bg)
        button_hover_text = Colors.contrast_text_for_bg(button_hover)

        self.setStyleSheet(
            "QDialog {"
            f"background-color: {panel_bg};"
            f"color: {text_color};"
            f"border: 1px solid {border_soft};"
            "}"
            "QWidget#settingsHeader {"
            "background-color: transparent;"
            "}"
            "QLabel#settingsTitle {"
            f"color: {text_color};"
            "font-size: 22px;"
            "font-weight: 750;"
            "}"
            "QLabel#settingsSubtitle {"
            f"color: {muted_text};"
            "font-size: 13px;"
            "font-weight: 500;"
            "}"
            "QLabel#settingsSectionLabel {"
            f"color: {section_text};"
            "font-size: 14px;"
            "font-weight: 700;"
            "padding-bottom: 4px;"
            "}"
            "QWidget#settingsThemeSection {"
            "background-color: transparent;"
            "border: none;"
            "}"
            "QLabel#settingsThemeGroupLabel {"
            f"color: {section_text};"
            "font-size: 11px;"
            "font-weight: 760;"
            "letter-spacing: 1.3px;"
            "text-transform: uppercase;"
            "padding-top: 6px;"
            "padding-bottom: 2px;"
            "}"
            "QLabel#settingsThemeEmptyState {"
            f"color: {muted_text};"
            "font-size: 13px;"
            "font-weight: 600;"
            "padding: 8px 0px;"
            "}"
            "QWidget#settingsSectionContainer {"
            "background-color: transparent;"
            "border: none;"
            "}"
            "QLabel#settingsPreferenceLabel {"
            f"color: {text_color};"
            "font-size: 13px;"
            "font-weight: 600;"
            "}"
            "QLabel#settingsHintLabel {"
            f"color: {muted_text};"
            "font-size: 12px;"
            "font-weight: 500;"
            "}"
            "QLabel#settingsVersionLabel {"
            "font-family: \"JetBrains Mono\", \"Menlo\", \"Consolas\", monospace;"
            f"color: {muted_text};"
            "font-size: 11px;"
            "font-weight: 500;"
            "}"
            "QLabel#settingsSourcingNotice {"
            f"color: {_mix_hex(text_color, pages_bg, 0.3)};"
            "font-size: 11px;"
            "font-weight: 400;"
            "}"
            "QListWidget#settingsNavList {"
            f"background-color: {nav_bg};"
            f"border: 1px solid {border_soft};"
            "border-radius: 12px;"
            "padding: 8px;"
            "font-size: 13px;"
            "font-weight: 600;"
            "}"
            "QListWidget#settingsNavList::item {"
            f"color: {nav_muted_text};"
            "background-color: transparent;"
            "border: none;"
            "border-radius: 8px;"
            "padding: 10px 12px;"
            "margin: 2px 0;"
            "}"
            "QListWidget#settingsNavList::item:selected {"
            f"background-color: {nav_item_selected_bg};"
            f"color: {nav_selected_text};"
            "}"
            "QListWidget#settingsNavList::item:hover:!selected {"
            f"background-color: {nav_item_hover_bg};"
            f"color: {nav_hover_text};"
            "}"
            "QStackedWidget#settingsPages {"
            f"background-color: {pages_bg};"
            f"border: 1px solid {border_soft};"
            "border-radius: 14px;"
            "}"
            "QLineEdit, QComboBox {"
            f"background-color: {input_bg};"
            f"color: {input_text};"
            f"border: 1px solid {border_soft};"
            "border-radius: 10px;"
            "padding: 8px 10px;"
            "min-height: 34px;"
            "font-size: 12px;"
            "}"
            "QLineEdit:focus, QComboBox:focus {"
            f"border: 1px solid {border_strong};"
            "}"
            "QComboBox QAbstractItemView {"
            f"background-color: {input_bg};"
            f"color: {input_text};"
            f"border: 1px solid {border_soft};"
            f"selection-background-color: {popup_selection_bg};"
            f"selection-color: {popup_selection_text};"
            "}"
            "QWidget#settingsActionRow {"
            f"background-color: {action_row_bg};"
            f"border: 1px solid {border_soft};"
            "border-radius: 12px;"
            "}"
            "QLabel#settingsActionTitle {"
            f"color: {action_row_text};"
            "font-size: 13px;"
            "font-weight: 700;"
            "}"
            "QLabel#settingsActionDescription {"
            f"color: {action_row_muted};"
            "font-size: 12px;"
            "font-weight: 500;"
            "}"
            "QPushButton {"
            f"background-color: {neutral_button_bg};"
            f"color: {neutral_button_text};"
            f"border: 1px solid {border_soft};"
            "border-radius: 10px;"
            "padding: 8px 14px;"
            "min-height: 34px;"
            "font-size: 12px;"
            "font-weight: 650;"
            "}"
            "QPushButton:hover:!disabled {"
            f"background-color: {neutral_button_hover_bg};"
            f"color: {neutral_button_hover_text};"
            f"border: 1px solid {border_strong};"
            "}"
            "QPushButton:disabled {"
            f"background-color: {neutral_button_disabled_bg};"
            f"color: {neutral_button_disabled_text};"
            f"border: 1px solid {border_soft};"
            "}"
            "QPushButton#settingsActionButton {"
            f"background-color: {button_bg};"
            f"color: {button_text};"
            "border: none;"
            "font-weight: 700;"
            "}"
            "QPushButton#settingsActionButton:hover:!disabled {"
            f"background-color: {button_hover};"
            f"color: {button_hover_text};"
            "border: none;"
            "}"
            "QScrollArea#settingsThemeScroll, QScrollArea#settingsGeneralScroll {"
            "background-color: transparent;"
            "border: none;"
            "}"
            "QScrollBar:vertical {"
            f"background: {scroll_track};"
            "width: 10px;"
            "margin: 2px;"
            "border-radius: 5px;"
            "}"
            "QScrollBar::handle:vertical {"
            f"background: {scroll_handle};"
            "min-height: 20px;"
            "border-radius: 5px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            "height: 0px;"
            "}"
        )
        self._apply_theme_cards_runtime_theme()
        self._sync_delete_theme_button_state()
        if self._ai_dialog is not None:
            self._ai_dialog.apply_runtime_theme()
        editor = self.__dict__.get("_custom_theme_editor_dialog")
        if isinstance(editor, CustomThemeEditorDialog):
            editor.apply_runtime_theme()


def _rgba(color_text: str, alpha: float) -> str:
    color = QColor(str(color_text or "#000000"))
    if not color.isValid():
        color = QColor("#000000")
    clamped = max(0.0, min(1.0, float(alpha)))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {int(round(clamped * 255.0))})"


def _mix_hex(start_color: str, end_color: str, ratio: float) -> str:
    start = QColor(str(start_color or "#000000"))
    end = QColor(str(end_color or "#000000"))
    if not start.isValid():
        start = QColor("#000000")
    if not end.isValid():
        end = QColor("#000000")
    t = max(0.0, min(1.0, float(ratio)))
    red = int(round(start.red() + (end.red() - start.red()) * t))
    green = int(round(start.green() + (end.green() - start.green()) * t))
    blue = int(round(start.blue() + (end.blue() - start.blue()) * t))
    return QColor(red, green, blue).name()


def _opaque_settings_panel_bg() -> str:
    if str(get_theme_manager().current_theme() or "").strip().casefold() == "parker's blueprint":
        return str(Colors.BG_MEDIUM or Colors.BG_DARK)
    color = QColor(str(Colors.BG_CARD))
    if color.isValid() and color.alpha() < 255:
        return _rgba(Colors.BG_MEDIUM, 0.96)
    candidate = str(Colors.BG_CARD or "").strip()
    if candidate:
        return candidate
    return _rgba(Colors.BG_MEDIUM, 0.96)
