"""Reversible Beta main-window presentation experiment; no application handlers.

Set PPF_EXPERIMENTAL_MAIN_GUI=0 before launch to use the unchanged original shell.
"""
from dataclasses import dataclass
import os
import weakref

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel,
                              QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from UI.theme import ThemeManager
from Utils.gui_utils import Colors


@dataclass(frozen=True)
class ShellSpacing:
    small: int = 4
    control: int = 8
    section: int = 16
    panel: int = 16
    toolbar: int = 12
    control_height: int = 36
    sidebar_min: int = 280
    sidebar_max: int = 340


SPACING = ShellSpacing()


def enabled():
    return os.environ.get('PPF_EXPERIMENTAL_MAIN_GUI', '1').strip().lower() not in {'0', 'false', 'off'}


class ExperimentalMainShell(QObject):
    """Arrange/style the existing widgets while preserving ownership and signals."""

    def __init__(self, window):
        super().__init__(window)
        self.window = weakref.proxy(window)
        self._responsive = False
        self._header_direction = None
        self._results_direction = None
        self._install_layout()
        window.results_panel.installEventFilter(self)
        window.results_scroll.viewport().installEventFilter(self)
        window.history_list.viewport().installEventFilter(self)
        self.refresh()
        self.resize()

    def sidebar_background(self):
        # Pale themed surfaces can be the sidebar itself instead of a nested form.
        if (ThemeManager._relative_luminance(Colors.BG_LIGHT) > .4
                and ThemeManager._relative_luminance(Colors.BG_DARK) < .2):
            return self.window._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, .28)
        return self.window._mix_colors(Colors.BG_CARD, Colors.BG_MEDIUM, .24)

    def _install_layout(self):
        w = self.window
        w.setMinimumSize(800, 560)
        w.main_layout.setContentsMargins(12, 8, 12, 8)
        w.main_layout.setSpacing(8)
        header = w.header_card.layout()
        self.title = header.itemAt(0).widget()
        self.title.setFont(QFont('Arial', 18, QFont.Weight.Bold))
        header.setContentsMargins(4, 8, 4, 12)
        header.setSpacing(SPACING.section)
        while header.count():
            header.takeAt(0)
        self.header_actions = QWidget(w.header_card)
        actions = QHBoxLayout(self.header_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        actions.addWidget(self.title)
        actions.addWidget(w.settings_btn)
        actions.addStretch(1)
        header.addWidget(self.header_actions, 1)
        header.addWidget(w.level_selector_card, 0, Qt.AlignmentFlag.AlignRight)
        w.level_selector_card.layout().setContentsMargins(4, 3, 4, 3)
        w.level_selector_card.layout().setSpacing(4)
        w.control_center_title.setFont(QFont('Arial', 15, QFont.Weight.Bold))
        w.control_center_content_layout.setSpacing(12)
        w.search_layout.setContentsMargins(16, 16, 16, 16)

        tabs = w.control_center_tabs
        page = tabs.widget(0)
        layout = page.layout()
        layout.setContentsMargins(0, 16, 0, 4)
        layout.setSpacing(16)
        # Group the existing Subject label/entry just like the other form sections.
        subject_label = layout.itemAt(0).widget()
        layout.removeWidget(subject_label)
        layout.removeWidget(w.subject_entry)
        subject_group = QWidget(page)
        subject_layout = QVBoxLayout(subject_group)
        subject_layout.setContentsMargins(0, 0, 0, 0)
        subject_layout.setSpacing(6)
        subject_layout.addWidget(subject_label)
        subject_layout.addWidget(w.subject_entry)
        layout.insertWidget(0, subject_group)
        for i in range(layout.count()):
            item = layout.itemAt(i)
            layout.setStretch(i, 1 if item.spacerItem() else 0)
            if item.widget() is not None and item.widget() is not w.search_button:
                item.widget().setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        for name in ('series_section_widget', 'year_section_widget', 'component_section_widget', 'doctype_section_widget'):
            section = getattr(w, name)
            section.layout().setSpacing(6)
        for entry in (w.subject_entry, w.year_entry, w.component_entry):
            entry.setFixedHeight(SPACING.control_height)
        for checkbox in w._search_panel_checkbox_widgets():
            checkbox.setFixedHeight(32)
        # A scrollable form handles short windows without stretching gaps or losing controls.
        self.search_scroll = QScrollArea(tabs)
        self.search_scroll.setObjectName('experimentalSearchScroll')
        self.search_scroll.setWidgetResizable(True)
        self.search_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.search_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tabs.removeTab(0)
        self.search_scroll.setWidget(page)
        page.setAutoFillBackground(False)
        # Keep the primary action visible even when the filter form needs scrolling.
        layout.removeWidget(w.search_button)
        self.search_page = QWidget(tabs)
        search_host = QVBoxLayout(self.search_page)
        search_host.setContentsMargins(0, 0, 0, 0)
        search_host.setSpacing(12)
        search_host.addWidget(self.search_scroll, 0)
        search_host.addWidget(w.search_button, 0)
        search_host.addStretch(1)
        tabs.insertTab(0, self.search_page, 'Search')
        tabs.setCurrentIndex(0)
        tabs.widget(1).layout().setContentsMargins(0, 12, 0, 0)
        tabs.widget(1).layout().setSpacing(8)

        results_layout = w.results_panel.layout()
        results_layout.setContentsMargins(16, 8, 0, 0)
        results_layout.setSpacing(12)
        self.results_toolbar = results_layout.itemAt(0).layout()
        heading = self.results_toolbar.itemAt(0).widget()
        heading.setFont(QFont('Arial', 16, QFont.Weight.Bold))
        while self.results_toolbar.count():
            self.results_toolbar.takeAt(0)
        self.results_heading = QWidget(w.results_panel)
        labels = QHBoxLayout(self.results_heading)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(8)
        labels.addWidget(heading)
        labels.addWidget(w.results_count)
        labels.addStretch(1)
        self.results_actions = QWidget(w.results_panel)
        actions = QHBoxLayout(self.results_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.view_segment = QFrame(self.results_actions)
        segment = QHBoxLayout(self.view_segment)
        segment.setContentsMargins(3, 3, 3, 3)
        segment.setSpacing(2)
        segment.addWidget(w.results_view_list_btn)
        segment.addWidget(w.results_view_grid_btn)
        actions.addWidget(self.view_segment)
        actions.addWidget(w.open_all_button)
        actions.addWidget(w.download_all_button)
        self.results_toolbar.addWidget(self.results_heading, 1)
        self.results_toolbar.addWidget(self.results_actions, 0, Qt.AlignmentFlag.AlignRight)
        self.results_toolbar.setSpacing(12)
        w.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        w.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.results_container_layout.setContentsMargins(4, 8, 8, 8)
        w.results_container_layout.setSpacing(12)
        for button in (w.settings_btn, w.launch_exam_btn, w.open_all_button, w.download_all_button):
            if button is not None:
                button.setMinimumWidth(0)
                button.setFixedHeight(36)
        w.sidebar_toggle_btn.setFixedSize(30, 30)
        for button in (w.results_view_list_btn, w.results_view_grid_btn):
            button.setFixedHeight(30)
        self.collapsed(w._sidebar_is_collapsed)

    def _secondary_button(self):
        w = self.window
        surface = Colors.BG_DARK
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, surface)
        hover = w._mix_colors(Colors.BG_CARD, Colors.BG_LIGHT, .14)
        hover_text = ThemeManager._ensure_text_contrast(Colors.TEXT_WHITE, hover)
        return (
            f'QPushButton {{background: transparent; color: {text}; border: 1px solid transparent;'
            'border-radius: 6px; padding: 6px 10px; min-height: 22px; font-size: 12px; font-weight: 600;}'
            f'QPushButton:hover:!disabled {{background: {hover}; color: {hover_text};}}'
            f'QPushButton:focus {{border: 1px solid {Colors.PRIMARY};}}'
            f'QPushButton:disabled {{color: {ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, surface, min_ratio=3)};}}'
        )

    def refresh(self):
        w = self.window
        for entry in (w.subject_entry, w.year_entry, w.component_entry):
            entry.setFixedHeight(SPACING.control_height)
        bg = self.sidebar_background()
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, bg)
        muted = ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, bg)
        border = w._mix_colors(w._mix_colors(Colors.ACCENT_CYAN, Colors.BG_DARK, .55), bg, .55)
        w.header_card.setStyleSheet(
            f'QFrame#card {{background: transparent; border: none; border-bottom: 1px solid {border}; border-radius: 0;}}')
        w.search_panel.setStyleSheet(
            f'QFrame#card {{background: {bg}; border: none; border-radius: 8px;}}')
        w.results_panel.setStyleSheet('QFrame#card {background: transparent; border: none; border-radius: 0;}')
        w.control_center_title.setStyleSheet(f'color: {text}; font-size: 18px; font-weight: 700;')
        selected = w._mix_colors(Colors.PRIMARY, bg, .75)
        selected_text = ThemeManager._ensure_text_contrast(text, selected)
        w.control_center_tabs.setStyleSheet(
            'QTabWidget#controlCenterTabs, QTabWidget::pane {background: transparent; border: none;}'
            'QTabWidget::tab-bar {alignment: left;}'
            f'QTabBar::tab {{background: transparent; color: {muted}; padding: 8px 12px;'
            'min-width: 74px; margin-right: 4px; border: 1px solid transparent; border-radius: 6px; font-size: 12px; font-weight: 600;}'
            f'QTabBar::tab:selected {{background: {selected}; color: {selected_text}; border-bottom: 2px solid {Colors.PRIMARY};}}'
            f'QTabBar::tab:hover:!selected {{border-color: {border};}}')
        for label in self.search_scroll.findChildren(QLabel):
            if label.text().upper() in {'SUBJECT', 'SERIES', 'YEARS', 'PAPER COMPONENTS', 'DOCUMENT OPTIONS'}:
                label.setStyleSheet(f'color: {text}; font-size: 12px; font-weight: 600; letter-spacing: 0; text-transform: none;')
        w.sidebar_toggle_btn.setStyleSheet(
            f'QToolButton {{background: transparent; color: {text}; border: 1px solid transparent; border-radius: 5px;}}'
            f'QToolButton:hover {{border-color: {border};}} QToolButton:focus {{border: 2px solid {Colors.PRIMARY};}}')
        w.settings_btn.setFixedHeight(44)
        w.settings_btn.setStyleSheet(w._build_action_button_stylesheet(Colors.BG_LIGHT) +
                                  'QPushButton {font-size:16px;font-weight:700;padding:8px 18px;min-height:26px;max-height:26px;min-width:74px;}')
        for button in (w.open_all_button, w.download_all_button):
            button.setStyleSheet(self._secondary_button())
        if w.launch_exam_btn is not None:
            w.launch_exam_btn.setStyleSheet(w._build_action_button_stylesheet(Colors.ACCENT_PURPLE) +
                                           'QPushButton {padding: 6px 12px; min-height: 22px; font-size: 12px;}')
        self.view_segment.setStyleSheet(
            f'QFrame {{background: {Colors.BG_CARD}; border: 1px solid {border}; border-radius: 6px;}}')
        for button in (w.results_view_list_btn, w.results_view_grid_btn):
            button.setStyleSheet(
                f'QToolButton {{background: transparent; color: {ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, Colors.BG_CARD)};'
                'border: 1px solid transparent; border-radius: 4px; padding: 4px 10px; min-height: 18px; max-height: 18px; font-size: 12px;}'
                f'QToolButton:checked {{background: {Colors.PRIMARY}; color: {ThemeManager._ensure_text_contrast(Colors.TEXT_WHITE, Colors.PRIMARY)};}}'
                f'QToolButton:focus {{border: 2px solid {Colors.PRIMARY_HOVER};}}')
        level_bg = Colors.BG_CARD
        level_text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, level_bg)
        checked_bg = w._mix_colors(Colors.PRIMARY, level_bg, .78)
        w.level_label.setStyleSheet(f'color: {ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, level_bg)}; font-size: 11px;')
        w.level_selector_card.setStyleSheet(
            f'QFrame#examLevelSelectorCard {{background: {level_bg}; border: 1px solid {border}; border-radius: 6px;}}'
            f'QRadioButton {{color: {level_text}; background: transparent; border: 1px solid transparent;'
            'padding: 3px 8px; spacing: 4px; font-size: 12px; font-weight: 600; border-radius: 4px;}'
            f'QRadioButton:checked {{background: {checked_bg}; color: {ThemeManager._ensure_text_contrast(level_text, checked_bg)};}}'
            f'QRadioButton:focus {{border: 1px solid {Colors.PRIMARY};}}'
            f'QRadioButton::indicator {{width: 10px; height: 10px; border-radius: 5px; border: 1px solid {level_text}; background: {level_bg};}}'
            f'QRadioButton::indicator:checked {{background: {Colors.PRIMARY}; border-color: {Colors.PRIMARY};}}')
        # Keep native, narrow scrollbars and leave all painted canvas artwork visible.
        scroll_style = (
            'QScrollArea {background: transparent; border: none;}'
            'QScrollBar:vertical {background: transparent; width: 7px; margin: 0;}'
            f'QScrollBar::handle:vertical {{background: {border}; min-height: 24px; border-radius: 3px;}}'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0;}'
            'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background: transparent;}')
        self.search_scroll.setStyleSheet(scroll_style + f'QWidget#searchTabWidget {{background: {bg}; border: none;}}')
        self.search_scroll.setMaximumHeight(self.search_scroll.widget().sizeHint().height())
        w.history_list.setStyleSheet(w.history_list.styleSheet() + f'QListWidget {{background: {bg}; color: {text};}}')
        hint = getattr(w, 'history_scroll_hint', None)
        if isinstance(hint, QLabel):
            hint.setStyleSheet(f'color: {muted}; font-size: 11px;')
        w.history_list.setSpacing(8)
        w.history_list.setViewportMargins(0, 0, 0, 0)
        w.results_scroll.setStyleSheet(scroll_style)
        for scroll in (self.search_scroll, w.results_scroll):
            scroll.viewport().setAutoFillBackground(False)
        w.search_button.setStyleSheet(w.search_button.styleSheet() + 'QPushButton {min-height: 24px; padding: 6px 10px;}')
        w.search_button.setFixedHeight(40)
        self.restyle_history()
        self.resize()

    def collapsed(self, collapsed):
        self.window.search_layout.setContentsMargins(*( (12, 12, 12, 12) if collapsed else (16, 16, 16, 16)))
        self.window.search_layout.setSpacing(12)

    def resize(self):
        if self._responsive:
            return
        self._responsive = True
        try:
            w = self.window
            w._sidebar_expanded_width = max(SPACING.sidebar_min, min(SPACING.sidebar_max, round(w.width() * .215)))
            if not w._sidebar_is_animating:
                target = w._sidebar_collapsed_width if w._sidebar_is_collapsed else w._sidebar_expanded_width
                w._set_sidebar_panel_width(target, allow_collapsed=w._sidebar_is_collapsed)
            for layout, left, right, available, name in (
                (w.header_card.layout(), self.header_actions, w.level_selector_card, w.header_card.width() - 8, '_header_direction'),
                (self.results_toolbar, self.results_heading, self.results_actions, w.results_panel.width() - 16, '_results_direction')):
                if name == '_header_direction' and hasattr(w, '_profile_header'):
                    continue
                needed = left.sizeHint().width() + right.sizeHint().width() + layout.spacing()
                direction = QBoxLayout.Direction.LeftToRight if available >= needed else QBoxLayout.Direction.TopToBottom
                if getattr(self, name) != direction:
                    layout.setDirection(direction)
                    layout.setStretch(0, 1 if direction == QBoxLayout.Direction.LeftToRight else 0)
                    layout.setAlignment(right, Qt.AlignmentFlag.AlignRight)
                    setattr(self, name, direction)
        finally:
            self._responsive = False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            if watched is self.window.history_list.viewport():
                self.restyle_history()
            elif hasattr(watched, '_experimental_actions'):
                self._resize_result_card(watched)
            else:
                self.resize()
                self.resize_result_grid()
        return super().eventFilter(watched, event)

    def history_target_width(self):
        return max(120, self.window.history_list.viewport().width() - 8)

    def restyle_history(self):
        w = self.window
        target = self.history_target_width()
        tokens = ThemeManager._augment_runtime_tokens({key: getattr(Colors, key) for key in Colors.default_theme_tokens()})
        for i in range(w.history_list.count()):
            item = w.history_list.item(i)
            card = w.history_list.itemWidget(item)
            if card is None:
                continue
            card.setMinimumHeight(0)
            card.setStyleSheet(
                f"QFrame[themeRole='historyCard'] {{background: {tokens['HISTORY_CARD_BG']}; border: none; border-radius: 6px;}}"
                f"QFrame[themeRole='historyCard'][hovered='true'] {{border: 1px solid {tokens['HISTORY_CARD_BORDER']};}}"
                f"QFrame[themeRole='historyCard']:focus {{border: 2px solid {Colors.PRIMARY};}}")
            for label in card.findChildren(QLabel):
                font = label.font()
                font.setPointSize(10 if label.property('themeRole') else 11)
                if not label.property('themeRole'):
                    font.setWeight(QFont.Weight.DemiBold)
                label.setFont(font)
            for layout in card.findChildren(QVBoxLayout):
                layout.setContentsMargins(10, 8, 10, 8)
                layout.setSpacing(4)
            from PySide6.QtWidgets import QProgressBar
            for bar in card.findChildren(QProgressBar):
                bar.setFixedHeight(5)
            if card.minimumWidth() != target:
                card.setFixedWidth(target)
            card.layout().activate()
            height = card.heightForWidth(target)
            if height < 0:
                height = card.sizeHint().height()
            hint = QSize(target, max(64, height + 4))
            if item.sizeHint() != hint:
                item.setSizeHint(hint)

    def prepare_result_card(self, frame, inline_row, actions, compact):
        from UI.floating_settings_window import FlowLayout
        buttons = []
        while actions.count():
            item = actions.takeAt(0)
            if item.widget() is not None:
                buttons.append(item.widget())
        parent_layout = frame.layout() if compact else inline_row
        parent_layout.removeItem(actions)
        actions.setParent(None)
        actions.deleteLater()
        host = QWidget(frame)
        flow = FlowLayout(host, h_spacing=8, v_spacing=8)
        for button in buttons:
            button.setMinimumWidth(0)
            button.setStyleSheet(button.styleSheet() + 'QPushButton {padding: 5px 8px; min-height: 22px; min-width: 0; font-size: 12px;}')
            button.setFixedHeight(34)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            flow.addWidget(button)
        parent_layout.addWidget(host, 0, Qt.AlignmentFlag.AlignRight)
        for label in frame.findChildren(QLabel):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        for column in frame.findChildren(QVBoxLayout):
            for index in range(column.count()):
                label = column.itemAt(index).widget()
                if isinstance(label, QLabel):
                    column.setAlignment(label, Qt.AlignmentFlag.AlignTop)
        frame._experimental_actions = host
        frame._experimental_inline = None if compact else inline_row
        frame._experimental_action_width = sum(button.sizeHint().width() for button in buttons) + 8 * max(0, len(buttons) - 1)
        frame.installEventFilter(self)
        self._resize_result_card(frame)

    def _resize_result_card(self, frame):
        host = frame._experimental_actions
        preferred = frame._experimental_action_width
        available = max(100, frame.width() - 28)
        target = min(available, preferred)
        if host.minimumWidth() != target:
            host.setFixedWidth(target)
        row = frame._experimental_inline
        if row is not None:
            left_minimum = max(220, row.itemAt(0).minimumSize().width())
            direction = QBoxLayout.Direction.LeftToRight if available >= preferred + left_minimum + 12 else QBoxLayout.Direction.TopToBottom
            if row.direction() != direction:
                row.setDirection(direction)
                row.setStretch(0, 1 if direction == QBoxLayout.Direction.LeftToRight else 0)
        frame.updateGeometry()

    def prepare_results(self):
        w = self.window
        if w.results_container_layout.count():
            first = w.results_container_layout.itemAt(0)
            if first.spacerItem() is not None:
                first.spacerItem().changeSize(0, 8)
        for card in w.results_container.findChildren(QFrame):
            if card.property('themeRole') == 'groupCard':
                for label in card.findChildren(QLabel):
                    label.setWordWrap(True)
        self.resize_result_grid()

    def resize_result_grid(self):
        from PySide6.QtWidgets import QGridLayout
        w = self.window
        width = w.results_scroll.viewport().width()
        columns = max(1, min(3, (width - 22) // 430))
        for host in w.results_container.findChildren(QWidget):
            grid = host.layout()
            if not isinstance(grid, QGridLayout):
                continue
            if getattr(host, '_experimental_columns', None) == columns:
                continue
            cards = getattr(host, '_experimental_grid_cards', None)
            if cards is None:
                cards = [grid.itemAt(i).widget() for i in range(grid.count()) if grid.itemAt(i).widget() is not None]
                host._experimental_grid_cards = cards
            for i in range(3):
                grid.setColumnStretch(i, 0)
            for index, card in enumerate(cards):
                grid.removeWidget(card)
                card.setMinimumWidth(min(392, max(200, width - 24)))
                grid.addWidget(card, index // columns, index % columns)
            for i in range(columns):
                grid.setColumnStretch(i, 1)
            host._experimental_columns = columns
