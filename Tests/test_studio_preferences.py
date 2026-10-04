"""Preferences persist, govern launch, and reveal Exam Mode only with question papers."""
import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from UI.floating_settings_window import FloatingSettingsWindow
from UI.theme import get_theme_manager
from Utils.gui_utils import ConfigManager
from Tests.test_experimental_main_shell import window, groups, pump


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch, tmp_path):
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(tmp_path/'config.json'))
    monkeypatch.setattr(ConfigManager, '_CACHE', None)
    monkeypatch.setattr(ConfigManager, '_CACHE_SIGNATURE', None)


def test_defaults_and_creator_opt_in_do_not_emit_on_sync():
    app = QApplication.instance() or QApplication([])
    calls = []
    settings = FloatingSettingsWindow(on_preference_toggled=lambda *args: calls.append(args))
    settings.set_theme_names(get_theme_manager().theme_names())
    settings.set_preferences(show_startup_animation=True, full_screen_on_startup=True, custom_theme_creator_enabled=False)
    assert calls == []
    assert settings.startup_animation_toggle.isChecked()
    assert settings.fullscreen_startup_toggle.isChecked()
    assert not settings.custom_theme_creator_toggle.isChecked()
    assert 'Beta' in settings.custom_theme_creator_toggle.accessibleName()
    assert 'custom theme creator' not in settings._theme_cards
    assert all(label.text() != 'Answer Panel Position' for label in settings.findChildren(QLabel))
    settings._open_custom_theme_editor()
    assert settings._custom_theme_editor_dialog is None
    settings.custom_theme_creator_toggle.setChecked(True)
    assert calls == [('custom_theme_creator_enabled', True)]
    assert 'custom theme creator' in settings._theme_cards
    selected_card = settings._theme_cards[settings._selected_theme_text().casefold()]
    assert selected_card._selected
    settings.custom_theme_creator_toggle.setChecked(False)
    assert 'custom theme creator' not in settings._theme_cards
    settings.close(); settings.deleteLater()


def test_settings_save_all_preferences_and_restore_them_on_reopening(window):
    app, gui = window
    gui._ensure_settings_window()
    settings = gui._settings_window
    settings.startup_animation_toggle.setChecked(False)
    settings.fullscreen_startup_toggle.setChecked(False)
    settings.custom_theme_creator_toggle.setChecked(True)
    saved = json.loads(Path(ConfigManager.CONFIG_FILE).read_text())['ui']
    assert saved['show_startup_animation'] is False
    assert saved['full_screen_on_startup'] is False
    assert saved['custom_theme_creator_enabled'] is True
    # Read from disk rather than a previously synchronized widget/cache.
    ConfigManager._CACHE = None
    gui._show_settings_window()
    assert not settings.startup_animation_toggle.isChecked()
    assert not settings.fullscreen_startup_toggle.isChecked()
    assert settings.custom_theme_creator_toggle.isChecked()
    from PySide6.QtTest import QTest
    QTest.qWait(180)
    assert settings.startup_animation_toggle.slideProgress == 0
    assert settings.fullscreen_startup_toggle.slideProgress == 0
    assert settings.custom_theme_creator_toggle.slideProgress == 1


def test_saved_custom_themes_remain_available_when_creator_is_disabled():
    app = QApplication.instance() or QApplication([])
    manager = get_theme_manager()
    name = 'Preference Test Theme'
    assert manager.save_custom_theme(name, {'QPushButton':'#445566'}, base_theme='Archive Blue')
    try:
        settings = FloatingSettingsWindow()
        settings.set_theme_names(manager.theme_names())
        assert name.casefold() in settings._theme_cards
        assert 'custom theme creator' not in settings._theme_cards
        settings.close(); settings.deleteLater()
    finally:
        manager.delete_custom_theme(name)


@pytest.mark.parametrize('mode', ['list','grid'])
def test_exam_launch_is_below_results_only_when_question_papers_exist(window, mode):
    app, gui = window
    assert gui.settings_btn.text() == 'Settings'
    assert gui.settings_btn.height() >= 44
    assert gui.launch_exam_btn.text() == 'Launch Exam Mode'
    assert gui.launch_exam_btn.parentWidget() == gui.exam_launch_footer
    assert not gui.exam_launch_footer.isVisible()
    gui._set_results_view_mode(mode, persist=False, rerender=False)
    gui.display_results(groups(), record_history=False)
    pump(app)
    assert gui.exam_launch_footer.isVisible()
    assert gui.exam_launch_footer.geometry().top() >= gui.results_scroll.geometry().bottom()
    assert gui.launch_exam_btn.isVisibleTo(gui)
    ms_only = groups()
    ms_only[0].primary_docs.pop('QP')
    gui.display_results(ms_only, record_history=False)
    assert not gui.exam_launch_footer.isVisible()
    gui.display_results(groups(), record_history=False)
    gui._show_results_skeleton()
    assert not gui.exam_launch_footer.isVisible()
    gui.display_results([], record_history=False)
    assert not gui.exam_launch_footer.isVisible()


@pytest.mark.parametrize('fullscreen', [True, False])
def test_disabling_animation_creates_no_splash_and_honors_fullscreen_preference(monkeypatch, fullscreen):
    import Core.gui_main as gui
    app = QApplication.instance() or QApplication([])
    ConfigManager.set_value('ui.show_startup_animation', False)
    ConfigManager.set_value('ui.full_screen_on_startup', fullscreen)
    ConfigManager.set_value('ui.theme', 'Coffee Shop')
    events = []
    class ExistingApp:
        def __new__(cls,*args): return app
        processEvents = staticmethod(app.processEvents)
    class Dashboard(QMainWindow):
        def __init__(self): super().__init__(); events.append('created')
        def refresh_history(self): events.append('history')
    original_show = gui._show_main_on_startup
    def show(window):
        original_show(window)
        assert window.isFullScreen() is fullscreen
        assert get_theme_manager().current_theme() == 'Coffee Shop'
        events.append('shown')
        QTimer.singleShot(0, app.quit)
    monkeypatch.setattr(gui,'QApplication',ExistingApp)
    monkeypatch.setattr(gui,'PastPaperFinderGUI',Dashboard)
    monkeypatch.setattr(gui,'_running_under_idle',lambda:False)
    monkeypatch.setattr(gui,'_maybe_reexec_project_python',lambda:None)
    monkeypatch.setattr(gui,'_acquire_single_instance_lock',lambda:True)
    monkeypatch.setattr(gui,'_release_single_instance_lock',lambda:None)
    monkeypatch.setattr(gui,'_warmup_ocr_runtime',lambda:events.append('warmup'))
    monkeypatch.setattr(gui,'_show_main_on_startup',show)
    monkeypatch.setattr(gui,'StudioBootSplashWindow',lambda **kw:pytest.fail('Disabled splash constructed'))
    monkeypatch.setattr(gui,'BetaBootSplashWindow',lambda **kw:pytest.fail('Disabled splash constructed'))
    monkeypatch.setattr(gui,'_should_run_full_startup_sequence',lambda:pytest.fail('Disabled animation marked seen'))
    monkeypatch.setattr(gui,'_crossfade_splash_to_main',lambda *a:pytest.fail('Disabled startup animated'))
    monkeypatch.setattr(sys,'excepthook',sys.excepthook)
    with pytest.raises(SystemExit): gui.main()
    assert events == ['warmup','created','history','shown']
    for window in app.topLevelWidgets():
        if isinstance(window,Dashboard): window.close(); window.deleteLater()
