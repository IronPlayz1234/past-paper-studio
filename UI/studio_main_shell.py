"""Second-pass studio presentation; PPF_STUDIO_GUI=0 restores the first pass."""

import os
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from UI.experimental_main_shell import ExperimentalMainShell, enabled
from UI.subject_browser import SubjectBrowser
from UI.studio_widgets import ElidedLabel, ResponsiveActions
from UI.theme import ThemeManager
from Utils.gui_utils import Colors, SubjectDatabase


def studio_enabled():
    return os.environ.get("PPF_STUDIO_GUI", "1").strip().lower() not in {
        "0",
        "false",
        "off",
    }


def main_canvas_enabled():
    return enabled() and studio_enabled()


def create_main_shell(window):
    if not enabled():
        return None
    return (
        StudioMainShell(window) if studio_enabled() else ExperimentalMainShell(window)
    )


class StudioMainShell(ExperimentalMainShell):
    """Build forward from the first-pass shell without changing application handlers."""

    def __init__(self, window):
        self._studio_ready = False
        self._syncing_subject = False
        self._history_styling = False
        super().__init__(window)
        self._install_subject_browser()
        self._studio_ready = True
        self.search_scroll.viewport().installEventFilter(self)
        self.search_scroll.widget().installEventFilter(self)
        window.history_list.itemSelectionChanged.connect(self._update_history_selection)
        self.refresh()
        self.sync_subject_browser()
        self.resize()

    def _install_subject_browser(self):
        w = self.window
        page = self.search_scroll.widget()
        layout = page.layout()
        group = layout.itemAt(0).widget()
        # Retain the canonical entry for configuration/history/programmatic selection.
        w.subject_entry.setParent(page)
        w.subject_entry.hide()
        layout.removeWidget(group)
        group.deleteLater()
        self.subject_browser = SubjectBrowser(page)
        self.subject_browser.subjectSelected.connect(w._apply_subject_selection)
        layout.insertWidget(0, self.subject_browser)
        self.subject_browser.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(12)
        # Match the visible order in keyboard navigation too.
        layout.removeWidget(w.year_section_widget)
        layout.insertWidget(
            layout.indexOf(w.component_section_widget), w.year_section_widget
        )
        w._control_anchor_widgets["subject"] = self.subject_browser.search
        w.search_button.setShortcut(QKeySequence())
        w.search_button.setAccessibleName(
            "Search papers using selected subject and filters"
        )
        host = self.search_page.layout()
        for i in range(host.count()):
            host.setStretch(
                i, 1 if host.itemAt(i).widget() is self.search_scroll else 0
            )
        self.search_scroll.setMaximumHeight(16777215)
        QWidget.setTabOrder(self.subject_browser.list, w.series_vars["MJ"])
        sequence = [
            w.series_vars["MJ"],
            w.series_vars["ON"],
            w.series_vars["FM"],
            w.year_entry,
            w.component_entry,
            w.paper_var,
            w.ms_var,
            w.gt_var,
            w.search_button,
        ]
        for first, second in zip(sequence, sequence[1:]):
            QWidget.setTabOrder(first, second)
        w.results_container.setObjectName("studioResultsCanvas")
        w.results_container.set_decorations_enabled(False)
        w.history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        w.history_list.setVerticalScrollMode(w.history_list.ScrollMode.ScrollPerPixel)
        w.history_list.setSpacing(4)

    def keyboard_rows(self):
        w = self.window
        return [
            [self.subject_browser.search],
            list(w.series_vars.values()),
            [w.year_entry],
            [w.component_entry],
            [w.paper_var, w.ms_var, w.gt_var],
            [w.search_button],
        ]

    def handle_subject_keypress(self, watched, event):
        browser = self.subject_browser
        return (
            browser.eventFilter(watched, event)
            if watched in (browser.search, browser.list)
            else False
        )

    def sync_subject_browser(self, *, clear_filter=False):
        if not self._studio_ready or self._syncing_subject:
            return
        self._syncing_subject = True
        try:
            w = self.window
            subjects = SubjectDatabase.get_searchable_subjects(w.current_level)
            if w.subject_code and w.subject_code not in subjects:
                w._clear_subject_selection()
            browser = self.subject_browser
            if clear_filter:
                browser.search.clear()
            if browser.level != w.current_level or browser.subjects != subjects:
                browser.set_catalog(subjects, w.current_level, w.subject_code)
            else:
                browser.sync_selection(w.subject_code)
        finally:
            self._syncing_subject = False

    def refresh(self):
        super().refresh()
        if not self._studio_ready:
            return
        w = self.window
        bg = self.sidebar_background()
        border = w._mix_colors(Colors.PRIMARY, Colors.BG_DARK, 0.28)
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, bg)
        w.main_layout.setContentsMargins(16, 12, 16, 12)
        w.main_layout.setSpacing(12)
        w.header_card.layout().setContentsMargins(16, 12, 16, 12)
        w.header_card.setStyleSheet(
            f"QFrame#card {{background:{Colors.BG_CARD};border:1px solid {border};border-radius:8px;}}"
        )
        self.title.setFont(QFont("Arial", 26, QFont.Weight.Bold))
        self.title.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.title.setStyleSheet(
            f"color:{ThemeManager._ensure_text_contrast(Colors.TEXT_WHITE,Colors.BG_CARD)};"
        )
        if w.launch_exam_btn is not None:
            w.launch_exam_btn.setFixedHeight(44)
            w.launch_exam_btn.setMinimumWidth(194)
            w.launch_exam_btn.setStyleSheet(
                w._build_action_button_stylesheet(Colors.ACCENT_PURPLE)
                + "QPushButton {padding:10px 18px;min-height:22px;font-size:14px;font-weight:700;}"
            )
        w.settings_btn.setFixedHeight(44)
        w.settings_btn.setStyleSheet(
            w._build_action_button_stylesheet(Colors.BG_LIGHT)
            + "QPushButton {font-size:16px;font-weight:700;padding:8px 18px;min-height:26px;max-height:26px;min-width:74px;}"
        )
        w.search_button.setFixedHeight(44)
        w.search_button.setStyleSheet(
            w.search_button.styleSheet()
            + "QPushButton {font-size:13px;font-weight:700;padding:8px 12px;min-height:24px;}"
        )
        w.control_center_title.setStyleSheet(
            f"color:{text};font-size:20px;font-weight:700;"
        )
        self.search_scroll.setMaximumHeight(16777215)
        self.subject_browser.refresh_theme(bg, w._control_filter_line_edit_stylesheet())
        w.results_container.setStyleSheet(
            "QWidget#studioResultsCanvas {background:transparent;}"
        )
        w.results_container.setAutoFillBackground(False)
        w.results_panel.layout().setContentsMargins(20, 10, 0, 0)
        self.results_heading.layout().itemAt(0).widget().setStyleSheet(
            f"color:{ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT,Colors.BG_DARK)};font-size:19px;font-weight:700;"
        )
        w.results_count.setStyleSheet(
            f"color:{ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY,Colors.BG_DARK)};font-size:12px;"
        )
        self.restyle_history()
        self.resize()

    def resize(self):
        if not self._studio_ready:
            return super().resize()
        if self._responsive:
            return
        self._responsive = True
        try:
            w = self.window
            available = max(0, w.width() - 32)
            minimum = 340 if available >= 1200 else 300 if available >= 980 else 280
            w._sidebar_expanded_width = max(minimum, min(440, round(available * 0.265)))
            if not w._sidebar_is_animating:
                target = (
                    w._sidebar_collapsed_width
                    if w._sidebar_is_collapsed
                    else w._sidebar_expanded_width
                )
                w._set_sidebar_panel_width(
                    target, allow_collapsed=w._sidebar_is_collapsed
                )
            body = self.search_scroll.widget()
            body_height = body.layout().totalHeightForWidth(
                self.search_scroll.viewport().width()
            )
            if body_height < 0:
                body_height = body.sizeHint().height()
            fixed_content = body_height - self.subject_browser.list.height()
            subject_height = max(
                132,
                min(300, self.search_scroll.viewport().height() - fixed_content - 4),
            )
            self.subject_browser.list.setFixedHeight(subject_height)
            for layout, left, right, available, name in (
                (
                    w.header_card.layout(),
                    self.header_actions,
                    w.level_selector_card,
                    w.header_card.width() - 32,
                    "_header_direction",
                ),
                (
                    self.results_toolbar,
                    self.results_heading,
                    self.results_actions,
                    w.results_panel.width() - 20,
                    "_results_direction",
                ),
            ):
                if name == '_header_direction' and hasattr(w, '_profile_header'):
                    continue
                needed = (
                    left.sizeHint().width()
                    + right.sizeHint().width()
                    + layout.spacing()
                )
                direction = (
                    QBoxLayout.Direction.LeftToRight
                    if available >= needed
                    else QBoxLayout.Direction.TopToBottom
                )
                if getattr(self, name) != direction:
                    layout.setDirection(direction)
                    layout.setStretch(
                        0, 1 if direction == QBoxLayout.Direction.LeftToRight else 0
                    )
                    layout.setAlignment(right, Qt.AlignmentFlag.AlignRight)
                    setattr(self, name, direction)
        finally:
            self._responsive = False

    def history_target_width(self):
        # QListWidget spacing applies on BOTH sides of every item.
        return max(
            120,
            self.window.history_list.viewport().width()
            - 2 * self.window.history_list.spacing(),
        )

    def _compact_history_labels(self, card):
        if getattr(card, "_studio_history_ready", False):
            return
        for label in list(card.findChildren(QLabel)):
            if label.text().endswith("%"):
                continue
            replacement = ElidedLabel(
                label.text(),
                label.parentWidget(),
                middle=label.property("themeRole") == "paperCode",
            )
            replacement.setProperty("themeRole", label.property("themeRole"))
            replacement.setAlignment(label.alignment())
            replacement.setFont(label.font())
            root = label.parentWidget().layout()
            old_item = (
                root.replaceWidget(
                    label, replacement, Qt.FindChildOption.FindChildrenRecursively
                )
                if root is not None
                else None
            )
            if old_item is None:
                replacement.deleteLater()
                continue
            label.hide()
            label.deleteLater()
        full_details = "\n".join(
            label.text() for label in card.findChildren(ElidedLabel)
        )
        card.setToolTip(full_details)
        card.setAccessibleName(full_details)
        card._studio_history_ready = True
        card.installEventFilter(self)

    def restyle_history(self):
        if not self._studio_ready:
            return super().restyle_history()
        if self._history_styling:
            return
        self._history_styling = True
        try:
            w = self.window
            w.history_list.setSpacing(4)
            target = self.history_target_width()
            tokens = ThemeManager._augment_runtime_tokens(
                {key: getattr(Colors, key) for key in Colors.default_theme_tokens()}
            )
            for i in range(w.history_list.count()):
                item = w.history_list.item(i)
                card = w.history_list.itemWidget(item)
                if card is None:
                    continue
                self._compact_history_labels(card)
                card.setMinimumHeight(0)
                card.setFixedWidth(target)
                card.setStyleSheet(
                    f"QFrame[themeRole='historyCard'] {{background:{tokens['HISTORY_CARD_BG']};border:1px solid transparent;border-radius:5px;}}"
                    f"QFrame[themeRole='historyCard'][hovered='true'] {{border-color:{tokens['HISTORY_CARD_BORDER']};}}"
                    f"QFrame[themeRole='historyCard'][selected='true'],QFrame[themeRole='historyCard']:focus {{border:1px solid {Colors.PRIMARY};}}"
                )
                for layout in card.findChildren(QVBoxLayout):
                    layout.setContentsMargins(10, 8, 10, 8)
                    layout.setSpacing(4)
                for label in card.findChildren(ElidedLabel):
                    font = label.font()
                    font.setPixelSize(11 if label.property("themeRole") else 13)
                    font.setWeight(
                        QFont.Weight.Normal
                        if label.property("themeRole")
                        else QFont.Weight.DemiBold
                    )
                    label.setFont(font)
                    if label.property("themeRole") == "paperCode":
                        label.setMaximumWidth(max(60, min(150, round(target * 0.43))))
                for bar in card.findChildren(QProgressBar):
                    bar.setFixedHeight(5)
                    bar.setMinimumWidth(0)
                card.layout().activate()
                height = max(64, card.layout().totalSizeHint().height() + 4)
                hint = QSize(target, height)
                if item.sizeHint() != hint:
                    item.setSizeHint(hint)
            self._update_history_selection()
        finally:
            self._history_styling = False

    def _update_history_selection(self):
        if not self._studio_ready:
            return
        w = self.window
        for i in range(w.history_list.count()):
            item = w.history_list.item(i)
            card = w.history_list.itemWidget(item)
            if card is None:
                continue
            selected = item.isSelected()
            if card.property("selected") != selected:
                card.setProperty("selected", selected)
                card.style().unpolish(card)
                card.style().polish(card)
                card.update()

    def eventFilter(self, watched, event):
        if self._studio_ready and event.type() == QEvent.Type.LayoutRequest:
            if watched is self.search_scroll.widget():
                self.resize()
        if self._studio_ready and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
        ):
            if (
                isinstance(watched, QFrame)
                and watched.property("themeRole") == "historyCard"
            ):
                w = self.window
                for i in range(w.history_list.count()):
                    if w.history_list.itemWidget(w.history_list.item(i)) is watched:
                        w.history_list.setCurrentRow(i)
                        break
        return super().eventFilter(watched, event)

    def prepare_result_card(self, frame, inline_row, actions, compact):
        buttons = []
        while actions.count():
            item = actions.takeAt(0)
            if item.widget() is not None:
                buttons.append(item.widget())
        parent_layout = frame.layout() if compact else inline_row
        parent_layout.removeItem(actions)
        actions.setParent(None)
        actions.deleteLater()
        for button in buttons:
            button.setMinimumWidth(0)
            button.setStyleSheet(
                button.styleSheet()
                + "QPushButton {padding:6px 10px;min-height:22px;min-width:0;font-size:13px;}"
            )
        host = ResponsiveActions(buttons, frame)
        parent_layout.addWidget(
            host, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        frame._experimental_actions = host
        frame._experimental_inline = None if compact else inline_row
        frame._disable_layout_lift = True
        frame.setMaximumHeight(16777215)
        frame.setMinimumWidth(0)
        for label in frame.findChildren(QLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            for column in frame.findChildren(QVBoxLayout):
                for i in range(column.count()):
                    if column.itemAt(i).widget() is label:
                        column.setAlignment(label, Qt.AlignmentFlag.AlignTop)
        frame.installEventFilter(self)
        self._resize_result_card(frame)

    def _resize_result_card(self, frame):
        host = frame._experimental_actions
        if not isinstance(host, ResponsiveActions):
            return super()._resize_result_card(frame)
        available = max(
            160, frame.layout().contentsRect().width() or frame.width() - 32
        )
        preferred = host.preferred_width()
        row = frame._experimental_inline
        direction = (
            QBoxLayout.Direction.LeftToRight
            if available >= preferred + 270
            else QBoxLayout.Direction.TopToBottom
        )
        if row is not None:
            row.setDirection(direction)
            row.setStretch(0, 1 if direction == QBoxLayout.Direction.LeftToRight else 0)
        width = min(preferred, available)
        if host.width() != width:
            host.setFixedWidth(width)
        host.fit_width(width)
        frame.updateGeometry()

    def resize_result_grid(self):
        from PySide6.QtWidgets import QGridLayout

        w = self.window
        width = w.results_scroll.viewport().width()
        columns = max(1, min(3, (width - 28) // 450))
        for host in w.results_container.findChildren(QWidget):
            grid = host.layout()
            if not isinstance(grid, QGridLayout):
                continue
            # Action-bar grids are deliberately independent of the document grid.
            if isinstance(host, ResponsiveActions):
                continue
            if getattr(host, "_studio_columns", None) == columns:
                continue
            cards = getattr(host, "_studio_grid_cards", None)
            if cards is None:
                cards = [
                    grid.itemAt(i).widget()
                    for i in range(grid.count())
                    if grid.itemAt(i).widget() is not None
                ]
                host._studio_grid_cards = cards
            for i in range(3):
                grid.setColumnStretch(i, 0)
            for index, card in enumerate(cards):
                grid.removeWidget(card)
                card.setMinimumWidth(min(420, max(240, width - 28)))
                grid.addWidget(card, index // columns, index % columns)
            for i in range(columns):
                grid.setColumnStretch(i, 1)
            host._studio_columns = columns
