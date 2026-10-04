"""Theme resolution before first paint, persistence, motion and startup handoff."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QMainWindow

from UI.studio_startup import StudioBootSplashWindow
from UI.theme import get_theme_manager
from Utils.gui_utils import ConfigManager, setup_appearance


@pytest.fixture
def app(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    manager = get_theme_manager()
    previous = manager.current_theme()
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(tmp_path/'settings.json'))
    monkeypatch.setattr(ConfigManager, '_CACHE', None)
    monkeypatch.setattr(ConfigManager, '_CACHE_SIGNATURE', None)
    yield app
    manager.apply_theme(app, previous)


def dispose(splash):
    splash.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('theme', get_theme_manager().theme_names())
def test_saved_theme_is_active_before_first_splash_frame_and_art_is_cached(app, theme):
    ConfigManager.set_value('ui.theme', theme)
    saved = Path(ConfigManager.CONFIG_FILE).read_bytes()
    setup_appearance(app)
    splash = StudioBootSplashWindow(reduced_motion=False)
    assert get_theme_manager().current_theme() == theme
    assert app.palette().color(QPalette.ColorRole.Window).name() == get_theme_manager().get_theme_tokens(theme)['BG_DARK'].lower()
    splash.show()
    splash._finish_intro()
    splash.progress = .6
    assert not splash.grab().isNull()
    count = splash._artwork._render_count
    splash._tick_ambient()
    splash.grab()
    assert splash._artwork._render_count == count
    assert Path(ConfigManager.CONFIG_FILE).read_bytes() == saved
    dispose(splash)


def test_first_launch_uses_archive_blue_without_writing_a_theme_preference(app):
    get_theme_manager().apply_theme(app, 'Coffee Shop')
    assert not Path(ConfigManager.CONFIG_FILE).exists()
    setup_appearance(app)
    assert get_theme_manager().current_theme() == 'Archive Blue'
    assert not Path(ConfigManager.CONFIG_FILE).exists()


@pytest.mark.parametrize('saved,expected', [('Legacy','Archive Blue'),('Matrix Purple','Cipher Purple'),('removed theme','Archive Blue')])
def test_old_aliases_and_unavailable_themes_use_existing_resolution(app, saved, expected):
    Path(ConfigManager.CONFIG_FILE).write_text(json.dumps({'ui':{'theme':saved}}))
    original=Path(ConfigManager.CONFIG_FILE).read_bytes()
    setup_appearance(app)
    assert get_theme_manager().current_theme() == expected
    assert Path(ConfigManager.CONFIG_FILE).read_bytes() == original


def test_future_custom_theme_uses_shared_tokens_without_a_splash_variant(app, monkeypatch):
    import UI.theme as theme_module
    manager=theme_module.ThemeManager()
    monkeypatch.setattr(theme_module,'_THEME_MANAGER',manager)
    assert manager.save_custom_theme('Quiet Study',{'QPushButton':'#346A58'},base_theme='Matcha Latte')
    ConfigManager.set_value('ui.theme','Quiet Study')
    setup_appearance(app)
    splash=StudioBootSplashWindow(reduced_motion=True)
    splash.show();splash.start_intro()
    assert manager.current_theme() == 'Quiet Study'
    assert manager.get_theme_tokens('Quiet Study')['BG_DARK'] == manager.get_theme_tokens('Matcha Latte')['BG_DARK']
    assert not splash.grab().isNull()
    dispose(splash)


def test_random_launch_theme_is_resolved_once_and_shared_with_splash(app, monkeypatch):
    import random
    calls = []
    monkeypatch.setattr(random, 'choice', lambda choices: calls.append(choices) or 'Cipher Purple')
    ConfigManager.set_random_theme_enabled(True)
    setup_appearance(app)
    splash = StudioBootSplashWindow(reduced_motion=True)
    splash.show(); splash.grab()
    assert get_theme_manager().current_theme() == ConfigManager.get_value('ui.theme') == 'Cipher Purple'
    assert len(calls) == 1
    dispose(splash)


@pytest.mark.parametrize('size', [(820,440),(600,360),(400,300),(1100,440)])
def test_reduced_motion_and_compact_layout_skip_slides_sweep_and_completion_wait(app, size):
    setup_appearance(app)
    splash = StudioBootSplashWindow(reduced_motion=True)
    splash.resize(*size); splash.show(); splash.start_intro()
    assert splash.titleProgress == splash.subtitleProgress == 1
    assert splash._intro.state() == QAbstractAnimation.State.Stopped
    assert not splash._ambient_timer.isActive()
    splash.set_stage('Paper tools', 2, 5)
    assert splash.progress == .4
    splash.finish_loading()
    assert splash.progress == 1 and splash._stage_text == 'Ready'
    assert not splash._progress_animation.state() == QAbstractAnimation.State.Running
    assert splash.rect().contains(splash._bar_rect().toRect())
    assert splash._title_rect().bottom() < splash._subtitle_rect().top()
    assert splash._subtitle_rect().bottom() < splash._bar_rect().top()
    assert not splash.grab().isNull()
    dispose(splash)


def test_startup_continues_during_intro_and_ready_cancels_decorative_wait(app):
    splash = StudioBootSplashWindow(reduced_motion=False)
    splash.show(); splash.start_intro()
    assert not splash._intro_finished
    assert splash._intro.state() == QAbstractAnimation.State.Running
    splash.finish_loading()
    assert splash._intro_finished and splash.progress == 1
    assert not splash._intro_timeout.isActive()
    assert splash._intro.state() == QAbstractAnimation.State.Stopped
    dispose(splash)


@pytest.mark.parametrize('cancel_during_startup', [False, True])
def test_main_applies_saved_theme_before_show_and_does_not_hold_ready_window(app, monkeypatch, cancel_during_startup):
    import Core.gui_main as gui
    ConfigManager.set_value('ui.theme', "Synthwave '84")
    events = []
    class ExistingApp:
        def __new__(cls, *args): return app
        processEvents = staticmethod(app.processEvents)
    class Splash(StudioBootSplashWindow):
        def show_centered(self):
            events.append(('first show', get_theme_manager().current_theme()))
            super().show_centered()
            if cancel_during_startup: self.close()
        def play_intro_blocking(self): raise AssertionError('Startup must not wait for decoration')
    class Dashboard(QMainWindow):
        def __init__(self):
            super().__init__(); events.append(('window',get_theme_manager().current_theme()))
        def refresh_history(self): events.append(('history',None))
    def warmup():
        pytest.fail('OCR must load only when needed, never during startup')
    def handoff(splash, window):
        assert splash._intro_finished and splash.progress == 1
        events.append(('handoff',get_theme_manager().current_theme()))
        splash.close(); window.show(); QTimer.singleShot(0,app.quit)
    monkeypatch.setenv('PPF_STUDIO_STARTUP','1')
    monkeypatch.setenv('PPF_REDUCED_MOTION','1')
    monkeypatch.setattr(gui,'QApplication',ExistingApp)
    monkeypatch.setattr(gui,'StudioBootSplashWindow',Splash)
    monkeypatch.setattr(gui,'PastPaperFinderGUI',Dashboard)
    monkeypatch.setattr(gui,'_running_under_idle',lambda:False)
    monkeypatch.setattr(gui,'_maybe_reexec_project_python',lambda:None)
    monkeypatch.setattr(gui,'_acquire_single_instance_lock',lambda:True)
    releases=[]
    monkeypatch.setattr(gui,'_release_single_instance_lock',lambda:releases.append(True))
    monkeypatch.setattr(gui,'_should_run_full_startup_sequence',lambda:False)
    monkeypatch.setattr(gui,'_warmup_ocr_runtime',warmup)
    monkeypatch.setattr(gui,'_wait_with_events',lambda ms:pytest.fail('Artificial startup hold'))
    monkeypatch.setattr(gui,'_crossfade_splash_to_main',handoff)
    monkeypatch.setattr(sys,'excepthook',sys.excepthook)
    if cancel_during_startup:
        assert gui.main() is None
        assert events == [('first show',"Synthwave '84")]
        assert releases == [True]
    else:
        with pytest.raises(SystemExit): gui.main()
        assert events == [('first show',"Synthwave '84"),('window',"Synthwave '84"),('history',None),('handoff',"Synthwave '84")]
    for window in app.topLevelWidgets():
        if isinstance(window,Dashboard): window.close(); window.deleteLater()


@pytest.mark.parametrize('theme', [None,"Synthwave '84",'Coffee Shop','Simple Light','OLED Dark'])
def test_theme_preference_survives_a_fresh_process_restart(tmp_path, theme):
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PAST_PAPER_FINDER_DATA_DIR=str(tmp_path/'data'), PAST_PAPER_FINDER_CACHE_DIR=str(tmp_path/'cache'))
    if theme:
        subprocess.run([sys.executable,'-B','-c',
                        'from Utils.gui_utils import ConfigManager; ConfigManager.set_value("ui.theme", '+repr(theme)+')'],
                       cwd=root,env=env,check=True,capture_output=True,text=True,timeout=20)
    code='''
import json
from PySide6.QtWidgets import QApplication
from Utils.gui_utils import ConfigManager, setup_appearance
from UI.studio_startup import StudioBootSplashWindow
from UI.theme import get_theme_manager
app=QApplication([])
setup_appearance(app)
splash=StudioBootSplashWindow(reduced_motion=True)
splash.show(); splash.start_intro(); splash.grab()
print(json.dumps({"theme":get_theme_manager().current_theme(),"saved":ConfigManager.get_value("ui.theme"),"title":splash.TITLE}))
splash.close()
'''
    result=subprocess.run([sys.executable,'-B','-c',code],cwd=root,env=env,check=True,capture_output=True,text=True,timeout=20)
    assert 'Traceback' not in result.stderr
    expected_theme = 'Solid White' if theme == 'Simple Light' else (theme or 'Archive Blue')
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {'theme':expected_theme,'saved':expected_theme,'title':'Past Paper Studio'}


@pytest.mark.parametrize('system,output,expected',[('Darwin','1',True),('Darwin','0',False),('Linux','false',True),('Linux','true',False)])
def test_native_motion_preferences_are_read_without_writing_settings(monkeypatch, system, output, expected):
    from UI import startup_motion
    monkeypatch.delenv('PPF_REDUCED_MOTION',raising=False)
    monkeypatch.setattr(startup_motion.platform,'system',lambda:system)
    monkeypatch.setattr(startup_motion.subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a[0],0,output,''))
    assert startup_motion.reduced_motion_requested() is expected


def test_missing_native_motion_provider_and_explicit_override(monkeypatch):
    from UI import startup_motion
    monkeypatch.delenv('PPF_REDUCED_MOTION',raising=False)
    monkeypatch.setattr(startup_motion.platform,'system',lambda:'Linux')
    monkeypatch.setattr(startup_motion.subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(FileNotFoundError()))
    assert not startup_motion.reduced_motion_requested()
    monkeypatch.setenv('PPF_REDUCED_MOTION','1')
    assert startup_motion.reduced_motion_requested()


def test_native_motion_probe_timeout_is_bounded_and_false_override_respects_os(monkeypatch):
    from UI import startup_motion
    monkeypatch.setenv('PPF_REDUCED_MOTION','0')
    monkeypatch.setattr(startup_motion.platform,'system',lambda:'Darwin')
    def timeout(command, **kwargs):
        assert kwargs['timeout'] <= .25
        raise subprocess.TimeoutExpired(command,kwargs['timeout'])
    monkeypatch.setattr(startup_motion.subprocess,'run',timeout)
    assert not startup_motion.reduced_motion_requested()
    monkeypatch.setattr(startup_motion.subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a[0],0,'1',''))
    assert startup_motion.reduced_motion_requested()
