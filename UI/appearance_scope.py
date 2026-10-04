"""Apply theme QSS to visible native workspaces, deferring hidden trees until Show."""
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QWidget

_LOCAL_MARKER = '\n/* PPS workspace local styles */\n'


class AppearanceScope(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.stylesheet = ''
        self._busy = False
        # App-global QSS reparses closed/hidden workspaces too. Each visible root
        # gets the shared cached stylesheet, with its existing local rules last.
        if app.styleSheet():
            app.setStyleSheet('')
        app.installEventFilter(self)

    def apply(self, stylesheet):
        self.stylesheet = stylesheet
        self._busy = True
        try:
            for root in self.app.topLevelWidgets():
                if root.isVisible():
                    self._apply_root(root)
        finally:
            self._busy = False

    def _apply_root(self, root):
        current = root.styleSheet()
        local = current.split(_LOCAL_MARKER, 1)[1] if _LOCAL_MARKER in current else current
        composed = self.stylesheet + _LOCAL_MARKER + local
        if composed != current:
            root.setStyleSheet(composed)

    def eventFilter(self, watched, event):
        if self._busy or not self.stylesheet or not isinstance(watched, QWidget):
            return False
        if event.type() not in (QEvent.Type.Show, QEvent.Type.StyleChange):
            return False
        if not watched.isWindow() or not watched.isVisible():
            return False
        self._busy = True
        try:
            self._apply_root(watched)
        finally:
            self._busy = False
        return False
