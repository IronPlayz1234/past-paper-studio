"""Permanent, keyboard-accessible catalog browser; selection delegates to the app."""

import weakref

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)
from Data.subject_categories import CATEGORY_ORDER, subject_category
from UI.theme import ThemeManager
from Utils.gui_utils import Colors

DATA_ROLE = Qt.ItemDataRole.UserRole


class SubjectRowDelegate(QStyledItemDelegate):
    """Paint two aligned columns, with full names available to assistive tools/tooltips."""

    def __init__(self, browser):
        super().__init__(browser.list)
        self.browser = weakref.proxy(browser)

    def sizeHint(self, option, index):
        data = index.data(DATA_ROLE) or {}
        return QSize(180, 28 if data.get("header") else 36)

    def paint(self, painter, option, index):
        data = index.data(DATA_ROLE) or {}
        bg = self.browser.surface_color
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, bg)
        muted = ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, bg)
        painter.save()
        rect = option.rect.adjusted(2, 1, -2, -1)
        font = QFont(option.font)
        font.setPixelSize(11 if data.get("header") else 13)
        if data.get("header"):
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(muted))
            painter.drawText(
                rect.adjusted(8, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter,
                data["header"].upper(),
            )
            painter.restore()
            return
        selected = data.get("code") == self.browser.selected_code
        cursor = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or cursor or hovered:
            fill = self.browser.mix(Colors.PRIMARY, bg, 0.24 if selected else 0.12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, 5, 5)
            text = ThemeManager._ensure_text_contrast(text, fill)
            muted = ThemeManager._ensure_text_contrast(muted, fill)
        if selected:
            painter.fillRect(
                QRect(rect.left(), rect.top() + 5, 3, rect.height() - 10),
                QColor(Colors.PRIMARY),
            )
        if cursor and self.browser.list.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(Colors.PRIMARY), 1))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        code_width = painter.fontMetrics().horizontalAdvance(data["code"]) + 16
        name_rect = rect.adjusted(10, 0, -code_width - 8, 0)
        painter.setPen(QColor(text))
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                data["name"], Qt.TextElideMode.ElideRight, max(0, name_rect.width())
            ),
        )
        font.setFamily("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(muted))
        painter.drawText(
            rect.adjusted(0, 0, -10, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            data["code"],
        )
        painter.restore()


class SubjectBrowser(QWidget):
    subjectSelected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.subjects = {}
        self.level = ""
        self.selected_code = ""
        self.surface_color = Colors.BG_CARD
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.heading = QLabel("Subjects", self)
        self.heading.setObjectName("subjectBrowserHeading")
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search subjects or codes…")
        self.search.setAccessibleName(
            "Search supported subjects by name or syllabus code"
        )
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(36)
        self.search.installEventFilter(self)
        self.list = QListWidget(self)
        self.list.setObjectName("subjectBrowserList")
        self.list.setAccessibleName("Supported subjects")
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setItemDelegate(SubjectRowDelegate(self))
        self.list.setMinimumHeight(132)
        self.list.setMaximumHeight(300)
        self.list.installEventFilter(self)
        self.selection_label = QLabel("Select a subject to begin", self)
        self.selection_label.setWordWrap(True)
        self.selection_label.setObjectName("subjectBrowserSelection")
        layout.addWidget(self.heading)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.selection_label)
        self.search.textChanged.connect(self.filter_subjects)
        self.list.itemClicked.connect(self._choose_item)
        QWidget.setTabOrder(self.search, self.list)

    @staticmethod
    def mix(first, second, weight):
        a, b = QColor(first), QColor(second)
        return QColor(
            round(a.red() * weight + b.red() * (1 - weight)),
            round(a.green() * weight + b.green() * (1 - weight)),
            round(a.blue() * weight + b.blue() * (1 - weight)),
        ).name()

    def set_catalog(self, subjects, level, selected_code=""):
        changed = self.level != level or self.subjects != subjects
        self.subjects = dict(subjects)
        self.level = level
        if changed:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self.selected_code = selected_code if selected_code in self.subjects else ""
        self.filter_subjects(self.search.text())
        self.sync_selection(self.selected_code)

    def sync_selection(self, code):
        self.selected_code = code if code in self.subjects else ""
        self.selection_label.setText(
            f"{self.selected_code} · {self.subjects[self.selected_code]}"
            if self.selected_code
            else "Select a subject to begin"
        )
        self.selection_label.setToolTip(self.selection_label.text())
        self.list.viewport().update()

    def filter_subjects(self, query):
        query = str(query).strip().casefold()
        current = self.list.currentItem()
        current_code = (current.data(DATA_ROLE) or {}).get("code") if current else None
        self.list.clear()
        matches = [
            (code, name)
            for code, name in self.subjects.items()
            if query in code.casefold() or query in name.casefold()
        ]
        for category in CATEGORY_ORDER:
            rows = sorted(
                (
                    (code, name)
                    for code, name in matches
                    if subject_category(code) == category
                ),
                key=lambda row: row[1].casefold(),
            )
            if not rows:
                continue
            header = QListWidgetItem(category)
            header.setData(DATA_ROLE, {"header": category})
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(header)
            for code, name in rows:
                item = QListWidgetItem(f"{name} — {code}")
                item.setData(DATA_ROLE, {"code": code, "name": name})
                item.setToolTip(f"{name}\nSyllabus {code} · {self.level}")
                item.setData(
                    Qt.ItemDataRole.AccessibleTextRole, f"{name}, syllabus {code}"
                )
                self.list.addItem(item)
                if code == current_code:
                    self.list.setCurrentItem(item)
        if not matches:
            item = QListWidgetItem("No matching subjects")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)

    def visible_codes(self):
        return [
            (self.list.item(i).data(DATA_ROLE) or {}).get("code")
            for i in range(self.list.count())
            if (self.list.item(i).data(DATA_ROLE) or {}).get("code")
        ]

    def _first_subject(self, reverse=False):
        indices = (
            range(self.list.count() - 1, -1, -1)
            if reverse
            else range(self.list.count())
        )
        return next(
            (
                self.list.item(i)
                for i in indices
                if (self.list.item(i).data(DATA_ROLE) or {}).get("code")
            ),
            None,
        )

    def _choose_item(self, item):
        data = item.data(DATA_ROLE) or {}
        if "code" not in data:
            return
        self.sync_selection(data["code"])
        self.subjectSelected.emit(data["code"], data["name"])

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if watched is self.search and key in (
                Qt.Key.Key_Down,
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                item = self._first_subject()
                if item:
                    self.list.setCurrentItem(item)
                    self.list.setFocus(Qt.FocusReason.TabFocusReason)
                    if key != Qt.Key.Key_Down:
                        self._choose_item(item)
                return True
            if watched is self.list and key in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Space,
            ):
                item = self.list.currentItem()
                if item:
                    self._choose_item(item)
                return True
            if (
                watched is self.list
                and key == Qt.Key.Key_Up
                and self.list.currentItem() is self._first_subject()
            ):
                self.search.setFocus(Qt.FocusReason.TabFocusReason)
                return True
            if key == Qt.Key.Key_Escape:
                self.search.clear()
                self.search.setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def refresh_theme(self, background, input_style):
        self.surface_color = background
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, background)
        muted = ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, background)
        border = self.mix(Colors.PRIMARY, background, 0.3)
        self.heading.setStyleSheet(f"color:{text};font-size:13px;font-weight:700;")
        self.selection_label.setStyleSheet(f"color:{muted};font-size:11px;")
        self.search.setStyleSheet(input_style)
        self.list.setStyleSheet(
            f"QListWidget {{background:transparent;color:{text};border:1px solid {border};border-radius:6px;padding:3px;}}"
            "QListWidget::item {background:transparent;border:none;padding:0;}"
            f"QListWidget:focus {{border:1px solid {Colors.PRIMARY};}}"
            "QScrollBar:vertical {background:transparent;width:7px;}"
            f"QScrollBar::handle:vertical {{background:{border};min-height:24px;border-radius:3px;}}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}"
        )
        self.list.viewport().setAutoFillBackground(False)
        self.list.viewport().update()
