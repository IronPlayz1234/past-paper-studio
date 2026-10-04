"""Behavior and geometry checks for the reversible main-window experiment."""
import time
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar
from Core.gui_main import PastPaperFinderGUI
from UI.theme import ThemeManager, get_theme_manager
from Utils.gui_utils import Colors, ConfigManager
from Utils.sources_manager import PaperGroup, PaperResource


def pump(app):
    deadline = time.monotonic() + .08
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)


def close_gui(app, gui):
    gui.close()
    deadline = time.monotonic() + 2
    while gui.isVisible() and time.monotonic() < deadline:
        pump(app)
    gui.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def groups(count=1):
    return [PaperGroup(subject_code='0620', subject_name='Chemistry', session='MJ', year='2024',
                       component=str(11 + i % 3), source='test', primary_docs={
        'QP': PaperResource('QP', f'0620_s24_qp_{11 + i % 3}.pdf', f'https://example.com/{i}/qp.pdf', 'test'),
        'MS': PaperResource('MS', f'0620_s24_ms_{11 + i % 3}.pdf', f'https://example.com/{i}/ms.pdf', 'test')})
        for i in range(count)]


@pytest.fixture
def window(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('PPF_EXPERIMENTAL_MAIN_GUI', '1')
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(ConfigManager, '_CACHE', None)
    monkeypatch.setattr(ConfigManager, '_CACHE_SIGNATURE', None)
    monkeypatch.setattr(PastPaperFinderGUI, '_show_groq_startup_warning_if_needed', lambda self: None)
    monkeypatch.setattr(PastPaperFinderGUI, '_maybe_show_onboarding_dialog', lambda self: None)
    ConfigManager.set_dashboard_sidebar_collapsed(False)
    gui = PastPaperFinderGUI()
    gui.show()
    pump(app)
    yield app, gui
    close_gui(app, gui)


@pytest.mark.parametrize('theme', get_theme_manager().theme_names())
def test_sidebar_and_controls_are_readable_in_every_builtin_theme(window, theme):
    app, gui = window
    get_theme_manager().apply_theme(app, theme)
    pump(app)
    bg = gui._experimental_shell.sidebar_background()
    labels = gui._experimental_shell.search_scroll.findChildren(QLabel)
    headings = {'Subject', 'Subjects', 'Series', 'Years', 'Paper Components', 'Document Options'}
    for label in labels:
        if label.text() in headings:
            text = label.palette().color(QPalette.ColorRole.WindowText).name()
            assert ThemeManager._contrast_ratio(text, bg) >= 4.5
    assert gui._experimental_shell.search_scroll.widget().palette().color(QPalette.ColorRole.Window).isValid()
    for entry in (gui.subject_entry, gui.year_entry, gui.component_entry):
        assert entry.height() >= 34
    assert gui.results_container.isVisibleTo(gui)
    assert gui.results_scroll.frameWidth() == 0
    hint = gui.history_scroll_hint
    hint.ensurePolished()
    assert ThemeManager._contrast_ratio(hint.palette().color(QPalette.ColorRole.WindowText).name(), bg) >= 4.5


@pytest.mark.parametrize('size', [(800, 560), (900, 650), (1280, 850), (1680, 1000)])
@pytest.mark.parametrize('mode', ['list', 'grid'])
def test_many_results_resize_without_overflow_and_sidebar_state_survives(window, size, mode):
    app, gui = window
    gui.resize(*size)
    gui.subjects_set_from_text('0620 - Chemistry')
    gui.year_entry.setText('2020-2024')
    gui.component_entry.setText('11-13')
    gui._set_results_view_mode(mode, persist=False, rerender=False)
    gui.display_results(groups(18), record_history=False)
    pump(app)
    # Exercise resize of already populated content, including grid column reduction.
    gui.resize(1680, 1000)
    pump(app)
    gui.resize(*size)
    pump(app)
    assert gui.width() == size[0]
    assert 280 <= gui.search_panel.width() <= (440 if hasattr(gui._experimental_shell, 'subject_browser') else 340)
    assert gui.results_panel.width() > gui.search_panel.width()
    assert gui.results_container.width() <= gui.results_scroll.viewport().width()
    shell = gui._experimental_shell
    assert shell.results_actions.width() >= shell.results_actions.sizeHint().width()
    assert shell.results_toolbar.geometry().height() <= 100
    assert gui.search_button.isVisibleTo(gui)
    assert gui.search_button.mapTo(gui, gui.search_button.rect().bottomRight()).y() < gui.height()
    for widget in (shell.results_actions, shell.results_heading):
        assert widget.geometry().right() <= gui.results_panel.width()
    for card in gui.results_container.findChildren(type(gui.results_panel)):
        if card.property('themeRole') != 'resultCard':
            continue
        for button in card.findChildren(QPushButton):
            assert button.mapTo(card, button.rect().topRight()).x() < card.width()
        for label in card.findChildren(QLabel):
            if label.wordWrap():
                assert label.height() >= label.heightForWidth(label.width())
    before = (gui.subject_entry.text(), gui.year_entry.text(), gui.component_entry.text(),
              tuple(cb.isChecked() for cb in gui._search_panel_checkbox_widgets()))
    workspace = gui.results_panel.width()
    gui.control_center_tabs.setCurrentIndex(1)
    gui._set_sidebar_collapsed(True, persist=False, animate=False)
    pump(app)
    assert gui.results_panel.width() > workspace
    gui._set_sidebar_collapsed(False, persist=False, animate=False)
    pump(app)
    assert gui.control_center_tabs.currentIndex() == 1
    assert before == (gui.subject_entry.text(), gui.year_entry.text(), gui.component_entry.text(),
                      tuple(cb.isChecked() for cb in gui._search_panel_checkbox_widgets()))


def test_history_remains_clickable_compact_and_scrollable(window, monkeypatch):
    app, gui = window
    attempts = [{'subject_code': '0620', 'subject_name': 'Chemistry', 'attempt_key': f'paper-{i}',
                 'component': '11', 'year': '2024', 'series': 'MJ', 'saved_at': '2026-10-03T10:00:00',
                 'answers': {'1': 'A'}, 'question_ids': ['1', '2', '3', '4']} for i in range(14)]
    monkeypatch.setattr('Core.gui_main.ExamAttemptManager.list_attempts', lambda: attempts)
    monkeypatch.setattr('Core.gui_main.HistoryManager.get_history', lambda: [])
    continued = []
    monkeypatch.setattr(gui, 'continue_saved_exam_attempt', continued.append)
    gui.refresh_history()
    gui.control_center_tabs.setCurrentIndex(1)
    pump(app)
    assert gui.history_list.count() == 14
    assert gui.history_list.verticalScrollBar().maximum() > 0
    first = gui.history_list.itemWidget(gui.history_list.item(0))
    first.activated.emit()
    assert continued == ['paper-0']
    assert first.findChildren(QProgressBar)
    assert any(label.text().endswith('%') for label in first.findChildren(QLabel))
    assert gui.history_list.item(0).sizeHint().height() < 132
    assert first.width() <= gui.history_list.viewport().width()


def test_original_layout_remains_available_without_experiment(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('PPF_EXPERIMENTAL_MAIN_GUI', '0')
    monkeypatch.setattr(PastPaperFinderGUI, '_show_groq_startup_warning_if_needed', lambda self: None)
    monkeypatch.setattr(PastPaperFinderGUI, '_maybe_show_onboarding_dialog', lambda self: None)
    ConfigManager.set_dashboard_sidebar_collapsed(False)
    gui = PastPaperFinderGUI()
    gui.show()
    pump(app)
    assert gui._experimental_shell is None
    assert gui._sidebar_expanded_width == 360
    assert gui.control_center_tabs.widget(0).objectName() == 'searchTabWidget'
    close_gui(app, gui)


def test_toolbar_and_result_actions_keep_existing_handlers(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('PPF_EXPERIMENTAL_MAIN_GUI', '1')
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(ConfigManager, '_CACHE', None)
    monkeypatch.setattr(ConfigManager, '_CACHE_SIGNATURE', None)
    monkeypatch.setattr(PastPaperFinderGUI, '_show_groq_startup_warning_if_needed', lambda self: None)
    monkeypatch.setattr(PastPaperFinderGUI, '_maybe_show_onboarding_dialog', lambda self: None)
    clicked = []
    for method in ('_show_settings_window', 'launch_standalone_exam_mode', 'on_search',
                   'open_all_results', 'download_all_results'):
        monkeypatch.setattr(PastPaperFinderGUI, method, lambda self, _checked=False, name=method: clicked.append(name))
    gui = PastPaperFinderGUI()
    gui.show()
    pump(app)
    gui.settings_btn.click()
    gui.launch_exam_btn.click()
    gui.search_button.click()
    gui.display_results(groups(), record_history=False)
    pump(app)
    gui.open_all_button.click()
    gui.download_all_button.click()
    assert clicked == ['_show_settings_window', 'launch_standalone_exam_mode', 'on_search',
                       'open_all_results', 'download_all_results']
    calls = []
    monkeypatch.setattr(gui, 'open_papers', lambda items: calls.append(('open', items[0]['type'])))
    monkeypatch.setattr(gui, 'download_papers', lambda items: calls.append(('download', items[0]['type'])))
    monkeypatch.setattr(gui, '_open_quick_look_window', lambda item: calls.append(('preview', item['type'])))
    monkeypatch.setattr(gui, 'launch_exam_mode_for_item', lambda item, **kwargs: calls.append(('exam', item['type'])))
    from PySide6.QtWidgets import QFrame
    paper = next(card for card in gui.results_container.findChildren(QFrame)
                 if card.property('themeRole') == 'resultCard' and any(b.text() == 'Start Exam' for b in card.findChildren(QPushButton)))
    for name in ('Quick Look', 'Start Exam', 'Open', 'Download'):
        next(b for b in paper.findChildren(QPushButton) if b.text() == name).click()
    assert calls == [('preview', 'QP'), ('exam', 'QP'), ('open', 'QP'), ('download', 'QP')]
    gui.alevel_level_btn.click()
    assert gui.current_level == 'A Level'
    gui.igcse_level_btn.click()
    assert gui.current_level == 'IGCSE'
    close_gui(app, gui)
