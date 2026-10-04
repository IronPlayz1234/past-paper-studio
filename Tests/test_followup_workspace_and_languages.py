"""Workspace lifecycle and interface translations never mutate examination data."""
import time
from pathlib import Path
import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QTextEdit
from Tests.test_exam_rendering_stability import app, paper, window, pump, wait_for
from Core.gui_main import PastPaperFinderGUI
import Core.exam_mode as exam
from UI.theme import get_theme_manager, ThemeManager
from UI.localization import get_locale_manager, translate
from Data.ui_translations import CATALOGS, LANGUAGES
from Utils.gui_utils import ConfigManager


@pytest.fixture
def main(app, monkeypatch):
    monkeypatch.setenv('PPF_STUDIO_GUI', '1')
    monkeypatch.setattr(PastPaperFinderGUI, '_show_groq_startup_warning_if_needed', lambda self: None)
    monkeypatch.setattr(PastPaperFinderGUI, '_maybe_show_onboarding_dialog', lambda self: None)
    gui = PastPaperFinderGUI(); gui.show(); pump(app)
    yield gui
    gui._graceful_exit_finalizing = True; gui.close(); gui.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


@pytest.fixture(autouse=True)
def english(app):
    locale = get_locale_manager(app)
    locale.set_language('en_US')
    yield
    locale.set_language('en_US')
    get_theme_manager().apply_font_override(app, 'Default')


def test_workspace_hides_main_and_restores_without_rebuilding(window, main, app):
    from UI.workspace_lifecycle import ExamWorkspaceLifecycle
    main.subjects_set_from_text('0620 - Chemistry')
    main.year_entry.setText('2022-2024'); main.component_entry.setText('42')
    before = (main.subject_code, main.year_entry.text(), main.component_entry.text(), main._central_widget)
    lifecycle = window._workspace_lifecycle = ExamWorkspaceLifecycle(window, main)
    lifecycle.enter()
    assert not main.isVisible() and not main.isEnabled()
    assert window.isEnabled()
    get_theme_manager().apply_theme(app, 'Crimson Meridian')
    assert main._deferred_theme_refresh_needed
    lifecycle.leave()
    wait_for(app, lambda: main.isVisible() and main.isEnabled())
    assert (main.subject_code, main.year_entry.text(), main.component_entry.text(), main._central_widget) == before


def test_real_launcher_owns_fullscreen_and_releases_exam(main, paper, app, monkeypatch):
    monkeypatch.setattr(exam.ExamModeWindow, '_show_groq_startup_warning_if_needed', lambda self: None)
    monkeypatch.setattr(exam.ExamModeWindow, '_prefetch_mark_scheme_in_background', lambda self: None)
    def structure(self):
        ids = ['1a', '2a']; self.question_items = self._build_items_from_ids(ids)
        self.question_items[-1].response_type = 'drawing'
        return ids, {qid: 2.0 for qid in ids}
    monkeypatch.setattr(exam.ExamModeWindow, '_build_ai_question_structure', structure)
    for _ in range(3):
        w = exam.launch_exam_mode(main, '0620', 'Chemistry', '42', '2024',
                                 pdf_url=str(paper), manual_grading_only=True, session_mode='practice')
        pump(app)
        assert w.isFullScreen() and w.isVisible() and w.isEnabled()
        assert not main.isVisible() and not main.isEnabled()
        viewer = w.pdf_viewer
        w._studio_workspace.toggle_protractor(True)
        for value in [.6, 2.5, 1.5]:
            viewer._apply_zoom_factor(value)
        w._allow_resume_autosave = False
        w.graceful_exit()
        wait_for(app, lambda: main.isVisible() and main.isEnabled())
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(w)
        assert not main.findChildren(exam.PDFViewer)
        assert not main.findChildren(exam.DrawingCanvasWidget)


def test_font_change_does_not_rebuild_stylesheet_or_pdf(window, app, monkeypatch):
    manager = get_theme_manager()
    manager.apply_theme(app, 'Archive Blue')
    viewer = window.pdf_viewer
    viewer._apply_zoom_factor(1.5)
    wait_for(app, lambda: viewer._sharp_revision == viewer._render_revision)
    document, image = viewer.doc, viewer.image_label.pixmap().cacheKey()
    revision = viewer._render_revision
    before = window.session_state.to_snapshot() if hasattr(window.session_state, 'to_snapshot') else window.session_state.active_question
    sheet = app.styleSheet()
    monkeypatch.setattr(app, 'setStyleSheet', lambda *a: pytest.fail('Font change reparsed the color stylesheet'))
    label = QLabel('Settings'); label.setFont(QFont('Arial', 18, QFont.Weight.Bold)); label.show()
    manager.apply_font_override(app, 'Georgia'); pump(app)
    assert label.font().family() == 'Georgia' and label.font().pointSize() == 18
    assert app.styleSheet() == sheet and viewer.doc is document
    assert viewer._render_revision == revision and viewer.image_label.pixmap().cacheKey() == image
    manager.apply_font_override(app, 'Default'); label.close(); label.deleteLater()


@pytest.mark.parametrize('language', [code for code, _ in LANGUAGES])
def test_language_changes_interface_not_inputs_or_pdf(window, app, language):
    locale = get_locale_manager(app)
    editor = QLineEdit(); editor.setText('My answer: colour = color'); editor.setPlaceholderText('Enter your answer...')
    label = QLabel('Settings'); button = QPushButton('Search Papers')
    for widget in (editor, label, button): widget.show()
    viewer = window.pdf_viewer
    wait_for(app, lambda: viewer._sharp_revision == viewer._render_revision)
    document = viewer.doc
    active, pauses = window.session_state.active_question, window.session_state.pause_count
    locale.set_language(language); pump(app)
    assert label.text() == translate('Settings', language)
    assert button.text() == translate('Search Papers', language)
    assert editor.text() == 'My answer: colour = color'
    assert viewer.doc is document
    assert (window.session_state.active_question, window.session_state.pause_count) == (active, pauses)
    assert ConfigManager.get_value('ui.language') == language
    label.setText('Page 3'); pump(app)
    # Newly built and dynamic controls also use the current language.
    locale._translate_widget(label)
    assert label.text() == translate('Page 3', language)
    locale.set_language('en_US')
    assert label.text() == 'Page 3' and button.text() == 'Search Papers'
    for widget in (editor, label, button): widget.close(); widget.deleteLater()


def test_settings_language_selection_persists_and_preserves_stable_ids(main, app):
    main._show_settings_window(); settings = main._settings_window
    settings.language_combo.setCurrentIndex(settings.language_combo.findData('hi'))
    pump(app)
    assert get_locale_manager(app).language == 'hi'
    assert settings.nav_list.item(0).text() == 'सामान्य'
    assert settings.language_combo.currentData() == 'hi'
    assert settings.startup_animation_toggle.isChecked()
    settings.nav_list.setCurrentRow(1)
    assert settings.pages.currentWidget() is settings.appearance_page
    get_locale_manager(app).set_language('fr'); pump(app)
    assert settings.language_combo.currentData() == 'fr'
    assert settings.nav_list.item(0).text() == 'Général'


def test_drawing_after_appearance_changes_translates_tools_without_changing_ids(window, app, tmp_path):
    manager = get_theme_manager()
    manager.apply_font_override(app, 'Georgia')
    manager.apply_theme(app, 'Crimson Meridian')
    dialog = exam.DrawingEditorDialog(str(tmp_path / 'answer.png'), parent=window)
    dialog.show(); pump(app)
    locale = get_locale_manager(app)
    ids = [dialog.tool_combo.itemData(i) for i in range(dialog.tool_combo.count())]
    for language in ('es', 'hi', 'fr', 'en_US'):
        locale.set_language(language); pump(app)
        assert dialog.tool_combo.itemText(3) == translate('Rectangle', language)
        assert dialog.save_btn.text() == translate('Save / Done', language)
        widest = max(dialog.tool_combo.fontMetrics().horizontalAdvance(dialog.tool_combo.itemText(i))
                     for i in range(dialog.tool_combo.count()))
        assert dialog.tool_combo.width() >= widest + 40
        assert [dialog.tool_combo.itemData(i) for i in range(dialog.tool_combo.count())] == ids
    canvas = dialog.canvas
    dialog.reject(); dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(canvas)


def test_catalogs_complete_and_preserve_template_fields():
    import re
    assert len(CATALOGS['es']) >= 180
    for source in CATALOGS['es']:
        fields = set(re.findall(r'\{\w+\}', source))
        for catalog in CATALOGS.values():
            assert source in catalog and catalog[source]
            assert set(re.findall(r'\{\w+\}', catalog[source])) == fields
    assert translate('Ink Color', 'en_GB') == 'Ink Colour'


def test_new_palettes_are_distinct_and_signature_has_art():
    manager = get_theme_manager()
    assert manager.get_theme_tokens('Solid Silver') != manager.get_theme_tokens('Solid Gray')
    assert manager.get_theme_tokens('Solid Gold') != manager.get_theme_tokens('Solid Yellow')
    for name in ('Solid Silver', 'Solid Gold', 'Solid Teal', 'Crimson Meridian'):
        tokens = manager.get_theme_tokens(name)
        for surface in ('BG_DARK', 'BG_CARD', 'INPUT_BG'):
            assert ThemeManager._contrast_ratio(tokens['TEXT_LIGHT'], tokens[surface]) >= 4.5
