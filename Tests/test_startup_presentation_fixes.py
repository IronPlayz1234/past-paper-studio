"""Startup owns loading feedback, and every handoff opens the main window full-screen."""
from concurrent.futures import Future

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('failure', [False, True])
def test_silent_startup_wait_never_constructs_a_pdf_dialog_and_keeps_ticking(app, monkeypatch, failure):
    from PySide6 import QtWidgets
    from Core.background_tasks import await_future, gui_work_pending
    monkeypatch.setattr(QtWidgets, 'QProgressDialog', lambda *a, **k: pytest.fail('Unexpected startup popup'))
    future = Future()
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(gui_work_pending()))
    timer.start()
    def finish():
        if failure:
            future.set_exception(ValueError('Worker failed'))
        else:
            future.set_result('ready')
    QTimer.singleShot(270, finish)
    try:
        if failure:
            with pytest.raises(ValueError, match='Worker failed'):
                await_future(future, show_progress=False)
        else:
            assert await_future(future, show_progress=False) == 'ready'
    finally:
        timer.stop()
    assert len(ticks) >= 5 and all(ticks)
    assert not gui_work_pending()


def test_silent_wait_timeout_releases_pending_state(app):
    from Core.background_tasks import await_future, gui_work_pending
    future = Future()
    cancelled = []
    with pytest.raises(TimeoutError):
        await_future(future, timeout=.04, cancel=lambda: cancelled.append(True), show_progress=False)
    assert cancelled == [True]
    assert not gui_work_pending()


def test_only_startup_warmup_opts_out_of_pdf_progress(app, monkeypatch):
    import Core.gui_main as gui
    import Core.pdf_service as pdf
    calls = []
    monkeypatch.setattr(pdf, '_request', lambda *args, **kwargs: calls.append((args, kwargs)))
    gui._warmup_ocr_runtime()
    assert calls == [(('call', ('Core.ocr_service', 'warmup_ocr_runtime', (), {})), {'show_progress': False})]


@pytest.mark.parametrize('handoff', ['fade', 'no-opacity', 'opacity-error'])
def test_all_startup_handoff_paths_show_full_screen(app, monkeypatch, handoff):
    import Core.gui_main as gui
    from UI.studio_startup import StudioBootSplashWindow
    class Dashboard(QMainWindow):
        def setWindowOpacity(self, opacity):
            if handoff == 'opacity-error':
                raise RuntimeError('Opacity unavailable')
            super().setWindowOpacity(opacity)
    window = Dashboard()
    splash = StudioBootSplashWindow(reduced_motion=True)
    splash.show(); splash.start_intro()
    monkeypatch.setattr(gui, '_supports_window_opacity', lambda widget: handoff != 'no-opacity')
    gui._crossfade_splash_to_main(splash, window)
    assert window.isVisible() and window.isFullScreen()
    window.close(); window.deleteLater()
