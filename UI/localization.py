"""Small, reversible native-Qt interface translation layer.

Only catalogued presentation text is translated. Editable values, PDF images,
answer content, combo IDs, source metadata and saved attempts are never rewritten.
English is the safe fallback for diagnostic messages without a translation yet.
"""
import re
from PySide6.QtCore import QObject, QEvent, QLocale, QSignalBlocker, Signal, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QAbstractButton,
                             QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QMenu, QListWidget)
from Data.ui_translations import CATALOGS, LANGUAGES

LANGUAGE_CODES = {code for code, _ in LANGUAGES}
_SOURCE_LOOKUP = {source.casefold(): source for source in CATALOGS['es']}
_TEMPLATES = []
for source in CATALOGS['es']:
    if '{' not in source:
        continue
    names = re.findall(r'\{(\w+)\}', source)
    pattern = re.escape(source)
    for name in names:
        value = r'\d+' if name in {'count', 'total', 'groups', 'page'} else (r'\d[\w().]*' if name == 'qid' else r'[^\n]+')
        pattern = pattern.replace(re.escape('{'+name+'}'), f'(?P<{name}>{value})')
    _TEMPLATES.append((source, re.compile('^'+pattern+'$')))


def translate(source, language):
    if not source or language == 'en_US':
        return source
    if language == 'en_GB':
        return re.sub(r'\b(color|colors|Color|Colors|center|Center|canceled|Canceled)\b',
                      lambda m: {'color':'colour','colors':'colours','Color':'Colour','Colors':'Colours',
                                 'center':'centre','Center':'Centre','canceled':'cancelled','Canceled':'Cancelled'}[m[0]], source)
    catalog = CATALOGS.get(language, {})
    if source in catalog:
        return catalog[source]
    canonical = _SOURCE_LOOKUP.get(source.casefold())
    if canonical and source.upper() != source:
        return catalog.get(canonical, source)
    for template, pattern in _TEMPLATES:
        match = pattern.fullmatch(source)
        if match:
            return catalog.get(template, template).format(**match.groupdict())
    if source.upper() == source and source.title() in catalog:
        return catalog[source.title()].upper()
    if source.startswith('&') and source[1:] in catalog:
        return '&' + catalog[source[1:]]
    if source.startswith('(') and source.endswith(')'):
        return '(' + translate(source[1:-1], language) + ')'
    for separator in ('\n', ' · '):
        if separator in source:
            return separator.join(translate(part, language) for part in source.split(separator))
    return source


class LocaleManager(QObject):
    language_changed = Signal(str)

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._busy = False
        from Utils.gui_utils import ConfigManager
        saved = ConfigManager.get_value('ui.language', 'en_US')
        self.language = saved if saved in LANGUAGE_CODES else 'en_US'
        QLocale.setDefault(QLocale(self.language))
        app.installEventFilter(self)

    def set_language(self, language):
        language = language if language in LANGUAGE_CODES else 'en_US'
        from Utils.gui_utils import ConfigManager
        ConfigManager.set_value('ui.language', language)
        if language == self.language:
            return
        self.language = language
        QLocale.setDefault(QLocale(language))
        self._busy = True
        try:
            for widget in self.app.allWidgets():
                self._translate_widget(widget)
            for widget in self.app.topLevelWidgets():
                QApplication.sendEvent(widget, QEvent(QEvent.Type.LanguageChange))
        finally:
            self._busy = False
        self.language_changed.emit(language)

    def _field(self, obj, field, current, setter):
        key = 'ppsLocale_' + field
        saved = obj.property(key)
        if isinstance(saved, list) and len(saved) == 2 and current == saved[1]:
            source = saved[0]
        else:
            source = current
        output = translate(source, self.language)
        if output != current:
            setter(output)
        if output != source or saved is not None:
            obj.setProperty(key, [source, output])

    def _translate_widget(self, widget):
        if widget.property('ppsNoTranslation'):
            return
        if isinstance(widget, (QLabel, QAbstractButton)):
            self._field(widget, 'text', widget.text(), widget.setText)
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            self._field(widget, 'placeholder', widget.placeholderText(), widget.setPlaceholderText)
        if widget.isWindow():
            self._field(widget, 'title', widget.windowTitle(), widget.setWindowTitle)
        self._field(widget, 'tooltip', widget.toolTip(), widget.setToolTip)
        self._field(widget, 'accessible', widget.accessibleName(), widget.setAccessibleName)
        if isinstance(widget, QComboBox) and widget.property('ppsTranslateItems'):
            blocker = QSignalBlocker(widget)
            for i in range(widget.count()):
                key = f'item{i}'
                self._field(widget, key, widget.itemText(i), lambda text, index=i: widget.setItemText(index, text))
            del blocker
        if isinstance(widget, QMenu):
            for action in widget.actions():
                self._field(action, 'text', action.text(), action.setText)
        if isinstance(widget, QListWidget) and widget.objectName() == 'settingsNavList':
            # Navigation uses stable row indices, so translated labels never become IDs.
            role = int(Qt.ItemDataRole.UserRole) + 201
            for i in range(widget.count()):
                item = widget.item(i)
                saved = item.data(role)
                source = saved[0] if saved and item.text() == saved[1] else item.text()
                output = translate(source, self.language)
                if output != item.text():
                    item.setText(output)
                item.setData(role, [source, output])

    def eventFilter(self, watched, event):
        if self._busy or self.language == 'en_US' or not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind not in (QEvent.Type.Polish, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            return False
        self._busy = True
        try:
            self._translate_widget(watched)
            if kind == QEvent.Type.Show and watched.isWindow():
                for widget in watched.findChildren(QWidget):
                    self._translate_widget(widget)
            elif kind == QEvent.Type.LayoutRequest:
                for widget in watched.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                    self._translate_widget(widget)
        finally:
            self._busy = False
        return False


def get_locale_manager(app=None):
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError('Create QApplication before configuring interface language')
    manager = getattr(app, '_pps_locale_manager', None)
    if manager is None:
        manager = app._pps_locale_manager = LocaleManager(app)
    return manager


def tr(source):
    app = QApplication.instance()
    return translate(source, get_locale_manager(app).language) if app else source


def source_text(widget, field='text'):
    """Presentation comparisons must use the canonical source, never a translated label."""
    current = widget.placeholderText() if field == 'placeholder' else widget.text()
    saved = widget.property('ppsLocale_' + field)
    return saved[0] if isinstance(saved, list) and len(saved) == 2 and current == saved[1] else current
