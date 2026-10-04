import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton

from Core.gui_main import PastPaperFinderGUI


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pump_events(seconds: float = 0.2) -> None:
    deadline = time.time() + max(0.0, float(seconds))
    app = _app()
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_drop_shadow_effect_is_parented_and_guarded():
    _app()
    gui = PastPaperFinderGUI()

    button = QPushButton("Test", gui)
    effect = gui._create_drop_shadow_effect(button, 14.0)
    assert effect is not None
    assert effect.parent() is button

    # Guard should refuse hidden widgets.
    button.hide()
    assert gui._safe_apply_graphics_effect(button, effect) is False

    # Visible parented widget should be accepted.
    button.show()
    _pump_events(0.05)
    assert gui._safe_apply_graphics_effect(button, effect) is True

    gui.close()


