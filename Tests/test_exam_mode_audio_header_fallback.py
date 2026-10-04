import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import Core.exam_mode as exam_mode
from Core.exam_mode import ExamModeWindow, ListeningHeader, QMediaPlayer
from Utils.gui_utils import ConfigManager


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _set_temp_config_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(ConfigManager, "CONFIG_FILE", str(path))
    defaults = ConfigManager.get_default_config()
    path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
    return path


class _FakePlayer:
    def __init__(self):
        self.stop_calls = 0
        self.play_calls = 0
        self.pause_calls = 0
        self.source = None
        if QMediaPlayer is not None:
            self._state = QMediaPlayer.PlaybackState.StoppedState
        else:
            self._state = 0

    def stop(self):
        self.stop_calls += 1
        if QMediaPlayer is not None:
            self._state = QMediaPlayer.PlaybackState.StoppedState

    def play(self):
        self.play_calls += 1
        if QMediaPlayer is not None:
            self._state = QMediaPlayer.PlaybackState.PlayingState

    def pause(self):
        self.pause_calls += 1
        if QMediaPlayer is not None:
            self._state = QMediaPlayer.PlaybackState.PausedState

    def playbackState(self):
        return self._state

    def setSource(self, source):
        self.source = source

    def position(self):
        return 0


def test_listening_header_shows_sound_off_warning_and_stops_player(monkeypatch, tmp_path):
    app = _app()
    _set_temp_config_path(monkeypatch, tmp_path)
    ConfigManager.set_sound_enabled(False)

    header = ListeningHeader()
    header.show()
    app.processEvents()
    header._player = _FakePlayer()
    header._audio_source = "https://example.com/audio.mp3"
    header._streaming_mode = True

    header.refresh_sound_state()
    app.processEvents()

    assert header._player.stop_calls == 1
    assert header.sound_warning_label.isHidden() is False
    assert header.sound_warning_label.toolTip() == "Sound is turned off."
    assert header.play_pause_btn.isEnabled() is False
    assert header.scrub_slider.isEnabled() is False


def test_listening_header_keeps_controls_available_when_sound_on(monkeypatch, tmp_path):
    app = _app()
    _set_temp_config_path(monkeypatch, tmp_path)
    ConfigManager.set_sound_enabled(True)

    header = ListeningHeader()
    header.show()
    app.processEvents()
    header._player = _FakePlayer()
    header._audio_source = "file:///tmp/audio.mp3"
    header._streaming_mode = False

    header.refresh_sound_state()
    app.processEvents()

    assert header.sound_warning_label.isHidden() is True
    assert header.play_pause_btn.isEnabled() is True
    assert header.scrub_slider.isEnabled() is True


def test_exam_mode_settings_window_wires_sound_toggle(monkeypatch):
    captured = {}

    class _StubSettings:
        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

        def setWindowTitle(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(exam_mode, "FloatingSettingsWindow", _StubSettings)

    window = ExamModeWindow.__new__(ExamModeWindow)
    window._sync_settings_window_state = lambda: None

    ExamModeWindow._ensure_settings_window(window)

    assert callable(captured.get("on_sound_toggled"))


def test_exam_mode_on_sound_toggled_refreshes_listening_header(monkeypatch, tmp_path):
    _app()
    _set_temp_config_path(monkeypatch, tmp_path)
    ConfigManager.set_sound_enabled(True)

    class _Header:
        def __init__(self):
            self.calls = 0

        def refresh_sound_state(self):
            self.calls += 1

    header = _Header()
    viewer = type("Viewer", (), {"audio_header": header})()

    window = ExamModeWindow.__new__(ExamModeWindow)
    window.pdf_viewer = viewer
    window._sync_settings_window_state = lambda: None

    ExamModeWindow.on_sound_toggled(window, False)

    assert ConfigManager.get_sound_enabled() is False
    assert header.calls == 1


