"""Future-year searches and real pointer interactions must avoid unnecessary work."""
from datetime import datetime

import pytest
from PySide6.QtCore import QPoint, Qt, QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

import Core.gui_main as main
from Tests.test_experimental_main_shell import window, groups, pump


def prepare_search(gui, years):
    gui.subject_code = '0620'
    gui.subject_name = 'Chemistry'
    gui.update_series_availability('0620')
    gui.component_entry.setText('11')
    gui.year_entry.setText(years)


@pytest.mark.parametrize('current_year, query', [(2026, '2027'), (2026, '27'),
                                               (2031, '2032-2034'), (2040, '41,42')])
def test_future_years_return_without_starting_search(window, monkeypatch, current_year, query):
    _, gui = window
    class Clock:
        @staticmethod
        def now():
            return datetime(current_year, 1, 1)
    monkeypatch.setattr(main, 'datetime', Clock)
    prepare_search(gui, query)
    gui.display_results(groups(), record_history=False)
    monkeypatch.setattr(gui, 'perform_search', lambda: pytest.fail('Future search started'))
    monkeypatch.setattr(gui, '_show_results_skeleton', lambda: pytest.fail('Loading shown'))
    monkeypatch.setattr(main, 'show_error', lambda *a: pytest.fail('Unexpected error dialog'))
    gui.on_search()
    assert gui.search_results == []
    assert not gui._results_skeleton_active
    assert gui.search_button.isEnabled()
    assert not gui.exam_launch_footer.isVisible()
    assert any(label.text() == 'No Papers Found' for label in gui.results_container.findChildren(QLabel))


def test_mixed_query_keeps_only_available_years(window, monkeypatch):
    _, gui = window
    current_year = datetime.now().year
    prepare_search(gui, f'{current_year-1}-{current_year+1}')
    searched = []
    monkeypatch.setattr(gui, 'perform_search', lambda: searched.append(gui.search_params['years']))
    gui.on_search()
    assert searched == [[str(current_year-1), str(current_year)]]


def test_old_search_completion_cannot_replace_future_year_empty_state(window):
    _, gui = window
    stale_generation = gui._active_search_generation
    prepare_search(gui, str(datetime.now().year + 1))
    gui.on_search()
    gui.on_search_complete(groups(), generation=stale_generation)
    assert gui.search_results == []
    assert not gui.exam_launch_footer.isVisible()


def test_filter_padding_toggles_on_first_click_without_mouse_focus_ring(window):
    app, gui = window
    for cb in [*gui.series_vars.values(), gui.paper_var, gui.ms_var, gui.gt_var]:
        if not cb.isEnabled():
            continue
        assert not cb.testAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect)
        before = cb.isChecked()
        QTest.mouseClick(cb, Qt.MouseButton.LeftButton, pos=QPoint(cb.width()-3, cb.height()//2))
        assert cb.isChecked() is not before
        assert cb.property('keyboardFocus') is False
    gui.paper_var.setFocus(Qt.FocusReason.TabFocusReason)
    pump(app)
    assert gui.paper_var.property('keyboardFocus') is True
    before = gui.paper_var.isChecked()
    QTest.keyClick(gui.paper_var, Qt.Key.Key_Space)
    assert gui.paper_var.isChecked() is not before


def test_preference_sync_preserves_each_switch_animation(window):
    _, gui = window
    gui._ensure_settings_window()
    settings = gui._settings_window
    for toggle in (settings.startup_animation_toggle, settings.fullscreen_startup_toggle,
                   settings.custom_theme_creator_toggle):
        target = not toggle.isChecked()
        toggle.click()
        assert toggle._animation.state() == QAbstractAnimation.State.Running
        # Verify a real intermediate frame without relying on a busy event loop
        # returning before the entire 160 ms animation has already completed.
        toggle._animation.pause()
        toggle._animation.setCurrentTime(toggle._animation.duration() // 3)
        assert 0 < toggle.slideProgress < 1
        toggle._animation.resume()
        QTest.qWait(toggle._animation.duration() + 30)
        assert toggle.slideProgress == (1.0 if target else 0.0)


@pytest.mark.parametrize('width', [800, 1366])
def test_larger_title_fits_responsive_header(window, width):
    app, gui = window
    gui.resize(width, 768)
    pump(app)
    logo = gui._profile_header.logo
    assert logo.isVisibleTo(gui) and logo.width() >= 150
    assert not gui.settings_btn.isVisibleTo(gui)
    assert gui._profile_header.control.isVisibleTo(gui)
