"""Native UI font changes without reparsing the color stylesheet."""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget


class AppearanceFont(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.default = QFont(app.font())
        self.choice = 'Default'
        self._busy = False
        app.installEventFilter(self)

    def apply(self, choice, *, refresh=False):
        if choice == self.choice and not refresh:
            return
        self.choice = choice
        font = QFont(self.default)
        if choice != 'Default':
            font.setFamily(choice)
        self._busy = True
        try:
            if self.app.font().family() != font.family():
                self.app.setFont(font)
            for widget in self.app.allWidgets():
                self._apply_widget(widget)
        finally:
            self._busy = False

    def _apply_widget(self, widget):
        if not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
            return
        font = widget.font()
        original = widget.property('ppsOriginalFontFamily')
        if original is None:
            original = font.family()
            widget.setProperty('ppsOriginalFontFamily', original)
        family = str(original) if self.choice == 'Default' else self.choice
        if font.family() != family:
            font.setFamily(family)
            widget.setFont(font)

    def eventFilter(self, watched, event):
        if (not self._busy and self.choice != 'Default' and isinstance(watched, QWidget)
                and event.type() in (QEvent.Type.Polish, QEvent.Type.Show)):
            self._busy = True
            try:
                self._apply_widget(watched)
            finally:
                self._busy = False
        return False
