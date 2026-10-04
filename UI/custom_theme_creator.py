from __future__ import annotations

from typing import List, Optional, Set

from PySide6.QtCore import QObject, QEvent, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Utils.gui_utils import Colors
from UI.theme import get_theme_manager


class ThemeEditEventFilter(QObject):
    """Intercept widget clicks while edit mode is active and report picked widget type."""

    widget_type_picked = Signal(str, QWidget)

    EDITABLE_WIDGET_TYPES = (
        "QPushButton",
        "QFrame",
        "QLineEdit",
        "QTextEdit",
        "QPlainTextEdit",
        "QComboBox",
        "QListWidget",
        "QCheckBox",
        "QLabel",
        "QWidget",
    )

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._target_root_widget: Optional[QWidget] = None
        self._ignore_root_widget: Optional[QWidget] = None

    def set_active(self, active: bool) -> None:
        self._active = bool(active)

    def set_target_root_widget(self, widget: Optional[QWidget]) -> None:
        self._target_root_widget = widget

    def set_ignore_root_widget(self, widget: Optional[QWidget]) -> None:
        self._ignore_root_widget = widget

    @staticmethod
    def _is_same_or_descendant(root: Optional[QWidget], widget: QWidget) -> bool:
        if root is None:
            return True
        current: Optional[QWidget] = widget
        while current is not None:
            if current is root:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _resolve_widget_type(widget: QWidget) -> str:
        if isinstance(widget, QPushButton):
            return "QPushButton"
        if isinstance(widget, QFrame):
            return "QFrame"
        if isinstance(widget, QLineEdit):
            return "QLineEdit"
        if isinstance(widget, QTextEdit):
            return "QTextEdit"
        if isinstance(widget, QPlainTextEdit):
            return "QPlainTextEdit"
        if isinstance(widget, QComboBox):
            return "QComboBox"
        if isinstance(widget, QListWidget):
            return "QListWidget"
        if isinstance(widget, QCheckBox):
            return "QCheckBox"
        if isinstance(widget, QLabel):
            return "QLabel"
        return "QWidget"

    def eventFilter(self, watched, event):  # type: ignore[override]
        if not self._active:
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if not isinstance(watched, QWidget):
            return False

        if isinstance(event, QMouseEvent) and event.button() != Qt.MouseButton.LeftButton:
            return False

        if self._ignore_root_widget and self._is_same_or_descendant(self._ignore_root_widget, watched):
            return False
        if self._target_root_widget and not self._is_same_or_descendant(self._target_root_widget, watched):
            return False

        widget_type = self._resolve_widget_type(watched)
        self.widget_type_picked.emit(widget_type, watched)
        return True


class CustomThemeCreatorWidget(QFrame):
    """Compact custom theme editor that supports click-to-pick and save-to-json workflows."""

    theme_saved = Signal(str)
    _BASE_THEME_NAME = "Archive Blue"
    _EDIT_OVERLAY_START = "/* CUSTOM_THEME_EDIT_OVERLAY_START */"
    _EDIT_OVERLAY_END = "/* CUSTOM_THEME_EDIT_OVERLAY_END */"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._target_root_widget: Optional[QWidget] = None
        self._last_widget_type = ""
        self._widget_colors = self._default_widget_colors()
        self._edited_widget_types: Set[str] = set()
        self._highlighted_widgets: List[QWidget] = []

        self._event_filter = ThemeEditEventFilter(self)
        self._event_filter.widget_type_picked.connect(self._on_widget_picked)
        self._event_filter.set_ignore_root_widget(self)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._event_filter)

        self._build_ui()
        self.apply_runtime_theme()

    def set_target_root_widget(self, widget: QWidget) -> None:
        self._target_root_widget = widget
        self._event_filter.set_target_root_widget(widget)
        if self.edit_mode_btn.isChecked():
            self._highlight_editable_widgets(self._last_widget_type or None)

    def _build_ui(self) -> None:
        self.setObjectName("customThemeCreatorCard")
        self.setMaximumHeight(236)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        title = QLabel("Custom Theme Creator", self)
        title.setObjectName("customThemeCreatorTitle")
        root.addWidget(title)

        self.theme_name_input = QLineEdit(self)
        self.theme_name_input.setPlaceholderText("My Cool Theme")
        self.theme_name_input.textChanged.connect(self._sync_save_button_state)
        root.addWidget(self.theme_name_input)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)

        self.edit_mode_btn = QPushButton("Theme Edit Mode", self)
        self.edit_mode_btn.setObjectName("customThemeEditModeButton")
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.toggled.connect(self._on_edit_mode_toggled)
        actions_row.addWidget(self.edit_mode_btn, 1)

        root.addLayout(actions_row)

        self.save_theme_btn = QPushButton("Save Theme", self)
        self.save_theme_btn.setObjectName("customThemeSaveButton")
        self.save_theme_btn.clicked.connect(self._save_theme)
        root.addWidget(self.save_theme_btn)

        self.selection_label = QLabel("Selected Widget Type: None", self)
        self.selection_label.setObjectName("customThemeCreatorSelection")
        root.addWidget(self.selection_label)

        self.status_label = QLabel("Enable edit mode, then click any widget to recolor it.", self)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("customThemeCreatorStatus")
        root.addWidget(self.status_label)
        self.quality_label = QLabel("Readability score: --", self)
        self.quality_label.setObjectName("customThemeCreatorStatus")
        root.addWidget(self.quality_label)

        self._sync_save_button_state()
        self._update_quality_label()

    def _default_widget_colors(self) -> dict[str, str]:
        default_tokens = (
            Colors.default_theme_tokens()
            if hasattr(Colors, "default_theme_tokens")
            else {
                "PRIMARY": Colors.PRIMARY,
                "BG_CARD": Colors.BG_CARD,
                "BG_LIGHT": Colors.BG_LIGHT,
                "BG_MEDIUM": Colors.BG_MEDIUM,
                "TEXT_WHITE": Colors.TEXT_WHITE,
                "BG_DARK": Colors.BG_DARK,
            }
        )
        return {
            "QPushButton": str(default_tokens.get("PRIMARY", "#3B8ED0")),
            "QFrame": str(default_tokens.get("BG_CARD", "#1F2937")),
            "QLineEdit": str(default_tokens.get("BG_LIGHT", "#0F3460")),
            "QTextEdit": str(default_tokens.get("BG_LIGHT", "#0F3460")),
            "QPlainTextEdit": str(default_tokens.get("BG_LIGHT", "#0F3460")),
            "QComboBox": str(default_tokens.get("BG_LIGHT", "#0F3460")),
            "QListWidget": str(default_tokens.get("BG_LIGHT", "#0F3460")),
            "QCheckBox": str(default_tokens.get("BG_MEDIUM", "#16213E")),
            "QLabel": str(default_tokens.get("TEXT_WHITE", "#FFFFFF")),
            "QWidget": str(default_tokens.get("BG_DARK", "#1A1A2E")),
        }

    @staticmethod
    def _refresh_widget_style(widget: QWidget) -> None:
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _candidate_root_widget(self) -> Optional[QWidget]:
        if isinstance(self._target_root_widget, QWidget):
            return self._target_root_widget
        app = QApplication.instance()
        if app is None:
            return None
        active = app.activeWindow()
        if isinstance(active, QWidget):
            return active
        return None

    def _iter_editable_widgets(self) -> List[QWidget]:
        root = self._candidate_root_widget()
        if root is None:
            return []

        editable_types = set(ThemeEditEventFilter.EDITABLE_WIDGET_TYPES)
        editable_types.discard("QWidget")

        widgets: List[QWidget] = []
        seen: Set[int] = set()
        for widget in root.findChildren(QWidget):
            if widget is self:
                continue
            if self._event_filter._is_same_or_descendant(self, widget):
                continue
            widget_type = ThemeEditEventFilter._resolve_widget_type(widget)
            if widget_type not in editable_types:
                continue
            key = id(widget)
            if key in seen:
                continue
            seen.add(key)
            widgets.append(widget)
        return widgets

    def _strip_edit_overlay(self, stylesheet: str) -> str:
        text = str(stylesheet or "")
        start = text.find(self._EDIT_OVERLAY_START)
        if start == -1:
            return text
        end = text.find(self._EDIT_OVERLAY_END, start)
        if end == -1:
            return text[:start].rstrip()
        end += len(self._EDIT_OVERLAY_END)
        return (text[:start] + text[end:]).strip()

    def _build_edit_overlay_qss(self) -> str:
        accent = QColor(str(getattr(Colors, "ACCENT_CYAN", "") or Colors.PRIMARY))
        selected = QColor(str(Colors.WARNING))
        candidate_border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 180)"
        selected_border = selected.name().upper()

        return (
            f"\n{self._EDIT_OVERLAY_START}\n"
            "QPushButton[themeEditCandidate=\"true\"],\n"
            "QLineEdit[themeEditCandidate=\"true\"],\n"
            "QTextEdit[themeEditCandidate=\"true\"],\n"
            "QPlainTextEdit[themeEditCandidate=\"true\"],\n"
            "QComboBox[themeEditCandidate=\"true\"],\n"
            "QListWidget[themeEditCandidate=\"true\"],\n"
            "QCheckBox[themeEditCandidate=\"true\"],\n"
            "QLabel[themeEditCandidate=\"true\"],\n"
            "QFrame[themeEditCandidate=\"true\"] {\n"
            f"    border: 1px dashed {candidate_border};\n"
            "}\n"
            "QCheckBox[themeEditCandidate=\"true\"]::indicator {\n"
            f"    border: 1px dashed {candidate_border};\n"
            "}\n"
            "QPushButton[themeEditSelected=\"true\"],\n"
            "QLineEdit[themeEditSelected=\"true\"],\n"
            "QTextEdit[themeEditSelected=\"true\"],\n"
            "QPlainTextEdit[themeEditSelected=\"true\"],\n"
            "QComboBox[themeEditSelected=\"true\"],\n"
            "QListWidget[themeEditSelected=\"true\"],\n"
            "QCheckBox[themeEditSelected=\"true\"],\n"
            "QLabel[themeEditSelected=\"true\"],\n"
            "QFrame[themeEditSelected=\"true\"] {\n"
            f"    border: 2px solid {selected_border};\n"
            "}\n"
            "QCheckBox[themeEditSelected=\"true\"]::indicator {\n"
            f"    border: 2px solid {selected_border};\n"
            "}\n"
            f"{self._EDIT_OVERLAY_END}\n"
        )

    def _refresh_edit_overlay_stylesheet(self, enabled: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        base = self._strip_edit_overlay(app.styleSheet())
        updated = base + self._build_edit_overlay_qss() if enabled else base
        if updated != app.styleSheet():
            app.setStyleSheet(updated)

    def _highlight_editable_widgets(self, selected_widget_type: Optional[str] = None) -> int:
        for widget in self._highlighted_widgets:
            try:
                widget.setProperty("themeEditCandidate", None)
                widget.setProperty("themeEditSelected", None)
                self._refresh_widget_style(widget)
            except RuntimeError:
                continue
        self._highlighted_widgets = []

        widgets = self._iter_editable_widgets()
        for widget in widgets:
            widget_type = ThemeEditEventFilter._resolve_widget_type(widget)
            try:
                widget.setProperty("themeEditCandidate", True)
                widget.setProperty("themeEditSelected", bool(selected_widget_type and widget_type == selected_widget_type))
                self._refresh_widget_style(widget)
            except RuntimeError:
                continue
        self._highlighted_widgets = widgets

        self._refresh_edit_overlay_stylesheet(self.edit_mode_btn.isChecked())
        return len(widgets)

    def _clear_edit_highlights(self) -> None:
        for widget in self._highlighted_widgets:
            try:
                widget.setProperty("themeEditCandidate", None)
                widget.setProperty("themeEditSelected", None)
                self._refresh_widget_style(widget)
            except RuntimeError:
                continue
        self._highlighted_widgets = []
        self._refresh_edit_overlay_stylesheet(False)

    def _set_edit_mode_cursor(self, enabled: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if enabled:
            app.setOverrideCursor(Qt.CursorShape.CrossCursor)
            return
        while app.overrideCursor() is not None:
            app.restoreOverrideCursor()

    def _sync_save_button_state(self) -> None:
        can_save = bool(str(self.theme_name_input.text() or "").strip()) and bool(self._edited_widget_types)
        self.save_theme_btn.setEnabled(can_save)

    def _on_edit_mode_toggled(self, enabled: bool) -> None:
        self._event_filter.set_active(enabled)
        self._set_edit_mode_cursor(enabled)

        if enabled:
            self.edit_mode_btn.setText("Theme Edit Mode (On)")
            count = self._highlight_editable_widgets(self._last_widget_type or None)
            self.status_label.setText(f"Edit mode active. Click a highlighted widget to recolor it. ({count} targets)")
        else:
            self.edit_mode_btn.setText("Theme Edit Mode")
            self._clear_edit_highlights()
            self.status_label.setText("Edit mode off. Toggle it on to select widgets again.")

    def force_stop_edit_mode(self) -> None:
        was_blocked = self.edit_mode_btn.blockSignals(True)
        self.edit_mode_btn.setChecked(False)
        self.edit_mode_btn.blockSignals(was_blocked)
        self._on_edit_mode_toggled(False)

    def _on_widget_picked(self, widget_type: str, _widget: QWidget) -> None:
        seed_color = QColor(self._widget_colors.get(widget_type, self._widget_colors["QWidget"]))
        picked = QColorDialog.getColor(seed_color, self, f"Pick color for {widget_type}")
        if not picked.isValid():
            return

        color_hex = picked.name().upper()
        self._last_widget_type = widget_type
        self._widget_colors[widget_type] = color_hex
        self._edited_widget_types.add(widget_type)
        self._sync_save_button_state()

        self.selection_label.setText(f"Selected Widget Type: {widget_type} ({color_hex})")
        self._apply_live_preview()
        self._update_quality_label()

        highlighted_count = self._highlight_editable_widgets(widget_type)
        if widget_type == "QWidget":
            self.status_label.setText(
                "Live preview updated for QWidget (global background only). "
                f"({highlighted_count} specific targets highlighted)"
            )
            return
        self.status_label.setText(f"Live preview updated for {widget_type}. ({highlighted_count} targets highlighted)")

    def _apply_live_preview(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        manager = get_theme_manager()
        manager.apply_custom_preview(app, self._widget_colors, base_theme=self._BASE_THEME_NAME)
        if self.edit_mode_btn.isChecked():
            self._refresh_edit_overlay_stylesheet(True)

    def _save_theme(self) -> None:
        theme_name = str(self.theme_name_input.text() or "").strip()
        if not theme_name:
            self.status_label.setText("Theme name required before saving.")
            return
        if not self._edited_widget_types:
            self.status_label.setText("No widget changes detected yet. Pick at least one color.")
            return

        manager = get_theme_manager()
        saved = manager.save_custom_theme(theme_name, self._widget_colors, base_theme=self._BASE_THEME_NAME)
        if not saved:
            self.status_label.setText("Could not save theme. Use a non-empty unique custom name.")
            return

        app = QApplication.instance()
        applied_name = theme_name
        if app is not None:
            applied_name = manager.apply_theme(app, theme_name)

        self.theme_saved.emit(applied_name)
        self._edited_widget_types.clear()
        self._sync_save_button_state()

        self.edit_mode_btn.blockSignals(True)
        self.edit_mode_btn.setChecked(False)
        self.edit_mode_btn.blockSignals(False)
        self._on_edit_mode_toggled(False)

        self.status_label.setText(f"Saved custom theme '{applied_name}'.")

    def _update_quality_label(self) -> None:
        bg = QColor(self._widget_colors.get("QWidget", Colors.BG_DARK))
        fg = QColor(self._widget_colors.get("QLabel", Colors.TEXT_WHITE))
        delta = abs(bg.lightness() - fg.lightness())
        score = max(0, min(100, int(round((float(delta) / 255.0) * 100.0))))
        level = "Good" if score >= 55 else ("Okay" if score >= 40 else "Low")
        self.quality_label.setText(f"Readability score: {score}/100 ({level})")

    def apply_runtime_theme(self) -> None:
        accent = str(getattr(Colors, "ACCENT_CYAN", "") or Colors.SECONDARY)
        border = str(QColor(accent).name())
        title_color = str(Colors.TEXT_WHITE)
        muted = str(Colors.TEXT_GRAY)
        panel_bg = str(Colors.BG_MEDIUM)
        input_bg = str(Colors.BG_LIGHT)
        text_color = str(Colors.TEXT_WHITE)

        edit_bg = str(QColor(Colors.BG_CARD).name())
        edit_hover = str(QColor(Colors.BG_LIGHT).name())
        save_bg = str(QColor(Colors.PRIMARY).name())
        save_hover = str(QColor(Colors.PRIMARY_HOVER).name())
        save_text = Colors.contrast_text_for_bg(save_bg)
        save_disabled_bg = str(QColor(Colors.BG_LIGHT).name())
        save_disabled_text = str(Colors.TEXT_GRAY)

        self.setStyleSheet(
            "QFrame#customThemeCreatorCard {"
            f"background-color: {panel_bg};"
            f"border: 1px solid {border};"
            "border-radius: 8px;"
            "}"
            "QLabel#customThemeCreatorTitle {"
            "font-size: 13px;"
            "font-weight: 700;"
            f"color: {title_color};"
            "}"
            "QLabel#customThemeCreatorSelection, QLabel#customThemeCreatorStatus {"
            f"color: {muted};"
            "font-size: 12px;"
            "}"
            "QLineEdit {"
            f"background-color: {input_bg};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 6px;"
            "padding: 6px 8px;"
            "min-height: 30px;"
            "}"
            "QPushButton#customThemeEditModeButton {"
            f"background-color: {edit_bg};"
            f"color: {text_color};"
            f"border: 1px solid {border};"
            "border-radius: 10px;"
            "padding: 6px 12px;"
            "min-height: 30px;"
            "font-size: 12px;"
            "font-weight: 600;"
            "}"
            "QPushButton#customThemeEditModeButton:hover {"
            f"background-color: {edit_hover};"
            "}"
            "QPushButton#customThemeEditModeButton:checked {"
            f"background-color: {Colors.WARNING};"
            f"color: {Colors.contrast_text_for_bg(Colors.WARNING)};"
            f"border: 1px solid {Colors.WARNING};"
            "}"
            "QPushButton#customThemeSaveButton {"
            f"background-color: {save_bg};"
            f"color: {save_text};"
            f"border: 1px solid {save_hover};"
            "border-radius: 10px;"
            "padding: 7px 14px;"
            "min-height: 34px;"
            "font-size: 13px;"
            "font-weight: 700;"
            "}"
            "QPushButton#customThemeSaveButton:hover:!disabled {"
            f"background-color: {save_hover};"
            f"border: 1px solid {save_hover};"
            "}"
            "QPushButton#customThemeSaveButton:disabled {"
            f"background-color: {save_disabled_bg};"
            f"color: {save_disabled_text};"
            f"border: 1px solid {border};"
            "}"
        )
