"""Small presentation widgets reused by the second-pass desktop shell."""

import math
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QGridLayout, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """Keep complete text accessible while painting a compact, elided line."""

    def __init__(self, text, parent=None, *, middle=False):
        super().__init__(text, parent)
        self.middle = middle
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sizeHint(self):
        return QSize(100, self.fontMetrics().height() + 2)

    def minimumSizeHint(self):
        return QSize(16, self.fontMetrics().height() + 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().windowText().color())
        text = self.fontMetrics().elidedText(
            self.text(),
            (
                Qt.TextElideMode.ElideMiddle
                if self.middle
                else Qt.TextElideMode.ElideRight
            ),
            self.contentsRect().width(),
        )
        painter.drawText(
            self.contentsRect(), self.alignment() | Qt.AlignmentFlag.AlignVCenter, text
        )
        painter.end()


class ResponsiveActions(QWidget):
    """Reflow existing action buttons into four, two or one readable columns."""

    def __init__(self, buttons, parent=None):
        super().__init__(parent)
        self.buttons = list(buttons)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.columns = 0
        self._arranging = False
        for button in self.buttons:
            button.setStyleSheet(button.styleSheet() + "QPushButton {min-width:72px;}")
            button.ensurePolished()
            button.setFixedHeight(36)
            button.setMinimumWidth(max(84, button.sizeHint().width()))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def button_widths(self):
        return [
            max(84, button.minimumWidth(), button.sizeHint().width())
            for button in self.buttons
        ]

    def preferred_width(self):
        return sum(self.button_widths()) + 8 * max(0, len(self.buttons) - 1)

    def fit_width(self, width):
        if self._arranging:
            return
        self._arranging = True
        try:
            widths = self.button_widths()
            width = max(max(widths, default=84), width)
            candidates = (
                [len(self.buttons), 2, 1]
                if len(self.buttons) > 2
                else [len(self.buttons), 1]
            )
            columns = 1
            for candidate in candidates:
                required = sum(
                    max(
                        (w for i, w in enumerate(widths) if i % candidate == c),
                        default=0,
                    )
                    for c in range(candidate)
                ) + 8 * (candidate - 1)
                if required <= width:
                    columns = candidate
                    break
            if self.columns != columns:
                while self.grid.count():
                    self.grid.takeAt(0)
                for i in range(4):
                    self.grid.setColumnStretch(i, 0)
                for i, button in enumerate(self.buttons):
                    self.grid.addWidget(button, i // columns, i % columns)
                for i in range(columns):
                    self.grid.setColumnStretch(i, 1)
                self.columns = columns
            rows = math.ceil(len(self.buttons) / columns) if self.buttons else 0
            self.setFixedHeight(rows * 36 + max(0, rows - 1) * 8)
            self.grid.activate()
        finally:
            self._arranging = False

    def resizeEvent(self, event):
        self.fit_width(event.size().width())
        super().resizeEvent(event)
