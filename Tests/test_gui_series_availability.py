import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from Core.gui_main import PastPaperFinderGUI
from Utils.gui_utils import SubjectDatabase


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_0607_and_0580_keep_fm_enabled_with_zone_tooltip():
    _app()
    gui = PastPaperFinderGUI()

    gui.update_series_availability("0607")
    assert gui.series_vars["FM"].isEnabled() is True
    assert "zone" in gui.series_vars["FM"].toolTip().lower()

    gui.update_series_availability("0580")
    assert gui.series_vars["FM"].isEnabled() is True
    assert "zone" in gui.series_vars["FM"].toolTip().lower()

    gui.close()


def test_retired_subject_disables_series_controls():
    _app()
    gui = PastPaperFinderGUI()
    gui.update_series_availability("9998")
    assert all(not cb.isEnabled() for cb in gui.series_vars.values())
    gui.close()


def test_retained_subject_keeps_all_series_enabled_with_data_check_tooltip():
    _app()
    gui = PastPaperFinderGUI()
    gui.update_series_availability("0620")
    assert all(cb.isEnabled() for cb in gui.series_vars.values())
    assert all("data check" in cb.toolTip().lower() for cb in gui.series_vars.values())
    gui.close()
