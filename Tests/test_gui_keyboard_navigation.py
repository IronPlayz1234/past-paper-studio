import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Core.gui_main import PastPaperFinderGUI


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_search_panel_keyboard_navigation_flow():
    _app()
    gui = PastPaperFinderGUI()

    trigger_count = {"value": 0}
    gui.search_button.clicked.disconnect()
    gui.search_button.clicked.connect(lambda: trigger_count.__setitem__("value", trigger_count["value"] + 1))

    browser = getattr(gui._experimental_shell, 'subject_browser', None)
    subject = browser.search if browser is not None else gui.subject_entry
    subject.setFocus()
    assert gui.focusWidget() is subject

    QTest.keyClick(subject, Qt.Key.Key_Down)
    if browser is not None:
        assert gui.focusWidget() is browser.list
        QTest.keyClick(browser.list, Qt.Key.Key_Return)
        QTest.keyClick(browser.list, Qt.Key.Key_Tab)
    assert gui.focusWidget() is gui.series_vars["MJ"]

    QTest.keyClick(gui.series_vars["MJ"], Qt.Key.Key_Right)
    assert gui.focusWidget() is gui.series_vars["ON"]

    initial_on = gui.series_vars["ON"].isChecked()
    QTest.keyClick(gui.series_vars["ON"], Qt.Key.Key_Return)
    assert gui.series_vars["ON"].isChecked() is (not initial_on)

    first = gui.year_entry if browser is not None else gui.component_entry
    second = gui.component_entry if browser is not None else gui.year_entry
    QTest.keyClick(gui.series_vars["ON"], Qt.Key.Key_Down)
    assert gui.focusWidget() is first

    QTest.keyClick(first, Qt.Key.Key_Down)
    assert gui.focusWidget() is second

    QTest.keyClick(second, Qt.Key.Key_Down)
    assert gui.focusWidget() is gui.paper_var

    initial_ms = gui.ms_var.isChecked()
    QTest.keyClick(gui.paper_var, Qt.Key.Key_Right)
    assert gui.focusWidget() is gui.ms_var
    QTest.keyClick(gui.ms_var, Qt.Key.Key_Return)
    assert gui.ms_var.isChecked() is (not initial_ms)

    QTest.keyClick(gui.ms_var, Qt.Key.Key_Down)
    assert gui.focusWidget() is gui.search_button

    QTest.keyClick(gui.search_button, Qt.Key.Key_Return)
    assert trigger_count["value"] == 1

    gui.close()


def test_enter_on_year_field_triggers_search():
    _app()
    gui = PastPaperFinderGUI()

    trigger_count = {"value": 0}
    gui.search_button.clicked.disconnect()
    gui.search_button.clicked.connect(lambda: trigger_count.__setitem__("value", trigger_count["value"] + 1))

    gui.year_entry.setFocus()
    assert gui.focusWidget() is gui.year_entry

    QTest.keyClick(gui.year_entry, Qt.Key.Key_Return)
    assert trigger_count["value"] == 1

    gui.close()


def test_document_type_checkboxes_use_same_focus_style_as_series():
    _app()
    gui = PastPaperFinderGUI()

    series_style = gui.series_vars["MJ"].styleSheet().strip()
    assert series_style
    assert gui.paper_var.styleSheet().strip() == series_style
    assert gui.ms_var.styleSheet().strip() == series_style
    assert gui.gt_var.styleSheet().strip() == series_style

    gui.close()
