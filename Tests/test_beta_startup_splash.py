"""Startup choreography, completion and teardown on real offscreen Qt widgets."""
import sys
import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
from shiboken6 import isValid
from UI.startup_splash import BetaBootSplashWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def pump(milliseconds=30):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def dispose(splash):
    splash.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('full_sequence', [True, False])
def test_opposing_slides_run_on_first_and_repeat_launches(app, full_sequence):
    splash = BetaBootSplashWindow(full_sequence)
    splash.show_centered()
    frames = []
    QTimer.singleShot(80, lambda: frames.append((splash.titleProgress, splash.subtitleProgress)))
    splash.play_intro_blocking()
    assert frames and 0 < frames[0][0] < 1 and frames[0][1] == 0
    assert splash._intro_finished
    assert splash.titleProgress == splash.subtitleProgress == 1.0
    assert splash._title_rect().center().x() == splash._subtitle_rect().center().x()
    assert splash._title_rect().bottom() < splash._subtitle_rect().top()
    assert splash._subtitle_rect().bottom() < splash._bar_rect().top()
    assert splash._intro.state() == QAbstractAnimation.State.Stopped
    assert not splash._intro_timeout.isActive()
    dispose(splash)


def test_progress_tracks_milestones_monotonically_and_finishes(app):
    splash = BetaBootSplashWindow()
    splash.show()
    splash._finish_intro()
    splash.set_stage('Preparing your paper tools', 2, 5)
    pump(330)
    assert splash.progress == pytest.approx(0.4)
    splash.set_stage('Late notification', 1, 5)
    assert splash._target_progress == 0.4
    splash.set_stage('Invalid total is safely clamped', 20, 0)
    assert splash._target_progress == 1.0
    splash.finish_loading()
    assert splash.progress == 1.0
    assert splash._stage_text == 'Your workspace is ready'
    dispose(splash)


def test_closing_mid_intro_exits_wait_and_stops_owned_animations(app):
    splash = BetaBootSplashWindow()
    splash.show()
    QTimer.singleShot(60, splash.close)
    splash.play_intro_blocking()
    assert splash._closed
    if isValid(splash):
        assert not splash._ambient_timer.isActive()
        assert not splash._intro_timeout.isActive()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_closing_mid_progress_wait_is_safe(app):
    splash = BetaBootSplashWindow()
    splash.show()
    splash._finish_intro()
    QTimer.singleShot(50, splash.close)
    splash.finish_loading()
    assert splash._closed
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('width,height', [(820, 440), (600, 360), (400, 300)])
def test_rendered_title_and_loading_bar_fit_compact_screens(app, width, height):
    splash = BetaBootSplashWindow()
    splash.resize(width, height)
    splash.show()
    splash._finish_intro()
    splash.progress = 0.6
    pixmap = splash.grab()
    assert not pixmap.isNull()
    assert splash.rect().contains(splash._bar_rect().toRect())
    # Title fitting is verified visually too; geometry and all surfaces remain bounded.
    assert splash._title_rect().left() >= 0
    assert splash._title_rect().right() <= width
    dispose(splash)


@pytest.mark.parametrize("cancel_intro", [False, True])
def test_real_startup_sequence_finishes_bar_before_dashboard_handoff(app, monkeypatch, cancel_intro):
    import Core.gui_main as gui
    monkeypatch.setenv('PPF_STUDIO_STARTUP', '0')
    checkpoints = []
    releases = []
    class ExistingApplication:
        def __new__(cls, *args):
            return app
        processEvents = staticmethod(app.processEvents)
    class Dashboard(QMainWindow):
        def refresh_history(self):
            checkpoints.append('history')
    monkeypatch.setattr(gui, 'QApplication', ExistingApplication)
    monkeypatch.setattr(gui, 'PastPaperFinderGUI', Dashboard)
    monkeypatch.setattr(gui, '_running_under_idle', lambda: False)
    monkeypatch.setattr(gui, '_maybe_reexec_project_python', lambda: None)
    monkeypatch.setattr(gui, '_acquire_single_instance_lock', lambda: True)
    monkeypatch.setattr(gui, '_release_single_instance_lock', lambda: releases.append(True))
    monkeypatch.setattr(gui, '_should_run_full_startup_sequence', lambda: False)
    monkeypatch.setattr(gui, '_warmup_ocr_runtime', lambda: checkpoints.append('paper tools'))
    monkeypatch.setattr(gui, 'setup_appearance', lambda app: checkpoints.append('appearance'))
    monkeypatch.setattr(sys, 'excepthook', sys.excepthook)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    if cancel_intro:
        class ClosingSplash(BetaBootSplashWindow):
            def play_intro_blocking(self):
                QTimer.singleShot(30, self.close)
                super().play_intro_blocking()
        monkeypatch.setattr(gui, 'BetaBootSplashWindow', ClosingSplash)
        assert gui.main() is None
        assert checkpoints == [] and releases == [True]
        return
    def handoff(splash, dashboard):
        assert splash._intro_finished and splash.progress == 1.0
        assert splash.SUBTITLE == 'Beta 1.0'
        checkpoints.append('handoff')
        splash.close()
        dashboard.show()
        QTimer.singleShot(20, app.quit)
    monkeypatch.setattr(gui, '_crossfade_splash_to_main', handoff)
    with pytest.raises(SystemExit) as exit:
        gui.main()
    assert exit.value.code == 0
    assert checkpoints == ['paper tools', 'appearance', 'history', 'handoff']
    for window in app.topLevelWidgets():
        if isinstance(window, Dashboard):
            window.close()
            window.deleteLater()


def test_handoff_can_close_splash_mid_crossfade(app):
    import Core.gui_main as gui
    splash = BetaBootSplashWindow()
    splash.show()
    splash._finish_intro()
    dashboard = QMainWindow()
    QTimer.singleShot(40, splash.close)
    gui._crossfade_splash_to_main(splash, dashboard)
    assert dashboard.isVisible() and dashboard.windowOpacity() == 1.0
    dashboard.close()
    dashboard.deleteLater()
