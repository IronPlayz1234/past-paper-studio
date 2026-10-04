"""Exercise retained themes and timer behavior on real offscreen Qt windows."""
import re
import time
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from Core.gui_main import PastPaperFinderGUI
from Core.exam_mode import ExamModeWindow, launch_exam_mode
from UI.theme import ThemeManager, get_theme_manager
from UI.theme_assets import themed_empty_state_svg
from Utils.gui_utils import Colors

THEMES = ['Simple Light', 'OLED Light', 'Simple Dark', 'OLED Dark', 'Archive Blue',
          'Coffee Shop', "Synthwave '84", 'Old Library', 'Matcha Latte',
          'Carbon Fiber', 'Violet Afterburn', 'Cipher Red', 'Cipher Green', 'Cipher Purple', 'Aurora Borealis']


def pump(app, seconds=0.12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope='module')
def windows(tmp_path_factory):
    import fitz
    app = QApplication.instance() or QApplication([])
    patch = pytest.MonkeyPatch()
    errors = []
    patch.setattr('Core.exam_mode.show_error', lambda *args: errors.append(args))
    patch.setattr(PastPaperFinderGUI, '_show_groq_startup_warning_if_needed', lambda self: None)
    patch.setattr(ExamModeWindow, '_show_groq_startup_warning_if_needed', lambda self: None)
    paper = tmp_path_factory.mktemp('alpha-ui') / '0620_s24_qp_11.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Chemistry Paper 1. Time allowed: 45 minutes.')
        doc.new_page().insert_text((72, 72), 'Question 1. Choose the correct answer.')
        doc.save(paper)
    dashboard = PastPaperFinderGUI()
    dashboard.show()
    exam = launch_exam_mode(dashboard, '0620', 'Chemistry', '1', '2024', pdf_url=str(paper))
    exam._test_render_errors = errors
    dashboard._ensure_settings_window()
    dashboard._ensure_quick_look_window()
    dashboard._settings_window.show()
    dashboard._quick_look_window.show()
    pump(app)
    yield app, dashboard, exam
    exam._stop_autosave_timers()
    exam.close()
    pump(app, 0.35)
    dashboard.close()
    pump(app, 0.35)
    get_theme_manager().apply_theme(app, 'Archive Blue')
    patch.undo()


def test_catalog_is_exact_and_legacy_alias_preserves_identity():
    manager = get_theme_manager()
    assert set(manager.THEMES) == set(THEMES)
    assert manager.HIDDEN_THEMES == {}
    assert manager.get_theme_tokens('Default') == manager.get_theme_tokens('Archive Blue')
    assert manager.get_theme_tokens('Archive Blue')['PRIMARY'] == '#00B8D9'


@pytest.mark.parametrize('theme', THEMES)
def test_theme_refreshes_main_search_results_settings_quicklook_and_exam(windows, theme):
    app, dashboard, exam = windows
    manager = get_theme_manager()
    manager.apply_theme(app, theme)
    pump(app)
    tokens = manager.get_theme_tokens(theme)
    assert Colors.BG_DARK == tokens['BG_DARK']
    assert Colors.PRIMARY == tokens['PRIMARY']
    assert dashboard._current_theme_name() == exam._current_theme_name() == theme
    shell = getattr(dashboard, '_experimental_shell', None)
    if shell is None:
        expected_panel = dashboard._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.3)
        assert expected_panel in dashboard.control_center_tabs.styleSheet()
    else:
        assert 'background: transparent' in dashboard.control_center_tabs.styleSheet()
        assert shell.sidebar_background() in dashboard.search_panel.styleSheet()
    assert Colors.PRIMARY in dashboard.search_button.styleSheet()
    subtitle = dashboard.results_container.findChild(QLabel, 'resultsEmptySubtitle')
    assert subtitle is not None
    assert subtitle.height() >= subtitle.heightForWidth(subtitle.width())

    chip_style = dashboard._series_checkbox_focus_stylesheet()
    for checkbox in dashboard.series_vars.values():
        assert checkbox.styleSheet() == chip_style
    assert dashboard._mix_colors(Colors.PRIMARY, Colors.BG_DARK, 0.25) in chip_style
    assert dashboard._settings_window._selected_theme_name == theme
    assert not hasattr(dashboard._settings_window, 'animations_toggle')
    assert Colors.BG_LIGHT in dashboard._quick_look_window_prev_btn.styleSheet()
    assert dashboard._quick_look_window_view.backgroundBrush().color().name().lower() == Colors.BG_DARK.lower()
    svg = themed_empty_state_svg(dashboard._empty_state_svg_path).decode()
    assert Colors.BG_CARD in svg and Colors.PRIMARY in svg
    assert exam.timer_label.isVisibleTo(exam)
    assert exam.timer_label.text() != '00:00'
    style = exam.timer_label.styleSheet()
    foreground = re.search(r'(?<!-)color: (#[0-9a-fA-F]+)', style)[1]
    background = re.search(r'background-color: (#[0-9a-fA-F]+)', style)[1]
    assert ThemeManager._contrast_ratio(foreground, background) >= 4.5


def test_timer_survives_focus_mode_resize_pause_and_restore(windows, monkeypatch):
    app, dashboard, exam = windows
    exam.timer.stop()
    assert exam.duration == 45  # Verified from the PDF rather than the metadata fallback.
    exam.remaining_seconds = 1234
    exam._update_timer_label()
    for focused in (True, False):
        exam.focus_mode_enabled = focused
        exam._apply_focus_mode_visibility()
        for width in (1100, 1300, 1600):
            exam.resize(width, 800)
            pump(app)
            assert exam.timer_label.isVisibleTo(exam)
            assert exam.pause_btn.isVisibleTo(exam)
            assert exam.focus_mode_btn.isVisibleTo(exam)
            top_left = exam.timer_label.mapTo(exam, QPoint(0, 0))
            assert exam.rect().contains(top_left)
            assert exam.rect().contains(top_left + exam.timer_label.rect().bottomRight())
    now = [100.0]
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(time, 'monotonic', lambda: now[0])
        exam._timer_last_monotonic = now[0]
        exam._timer_fraction = 0.0
        exam.toggle_pause()
        assert exam.timer_paused and exam.pause_btn.text() == 'Resume'
        before = exam.remaining_seconds
        now[0] += 10
        exam._tick_timer()
        assert exam.remaining_seconds == before
        exam.toggle_pause()
        assert not exam.timer_paused and exam.pause_btn.text() == 'Pause'
        now[0] += 2.1
        exam._tick_timer()
        assert exam.remaining_seconds == before - 2
    exam.resume_snapshot = {'remaining_seconds': 987, 'answers': {}, 'notes': ''}
    exam._apply_resume_snapshot()
    assert exam.remaining_seconds == 987
    assert exam.timer_label.text() == '16:27'
    exam.resume_snapshot = None


def test_public_exam_launch_preserves_resume_arguments(windows, monkeypatch):
    _, dashboard, _ = windows
    captured = {}
    monkeypatch.setattr(dashboard, '_launch_exam_mode_for_item_impl',
                        lambda item, **kwargs: captured.update(kwargs))
    snapshot = {'remaining_seconds': 987}
    dashboard.launch_exam_mode_for_item({}, resume_snapshot=snapshot, paper_num_override='1', paper_resources={})
    assert captured == {'resume_snapshot': snapshot, 'paper_num_override': '1', 'paper_resources': {}}


def test_custom_theme_creator_save_reload_delete(tmp_path, monkeypatch):
    import UI.custom_theme_creator as creator_module
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ThemeManager, 'CUSTOM_THEMES_FILE', tmp_path / 'themes.json')
    manager = ThemeManager()
    monkeypatch.setattr(creator_module, 'get_theme_manager', lambda: manager)
    creator = creator_module.CustomThemeCreatorWidget()
    saved = []
    creator.theme_saved.connect(saved.append)
    creator.theme_name_input.setText('My Study Theme')
    creator._widget_colors['QWidget'] = '#14283c'
    creator._edited_widget_types.add('QWidget')
    creator._save_theme()
    assert saved == ['My Study Theme']
    assert manager.is_custom_theme('My Study Theme')
    reloaded = ThemeManager()
    assert reloaded._custom_entry('My Study Theme')['widget_colors']['QWidget'] == '#14283C'
    assert reloaded._custom_entry('My Study Theme')['base_theme'] == 'Archive Blue'
    assert reloaded.save_custom_theme('Migrated', {'QWidget': '#123456'}, base_theme='Tetris')
    assert reloaded._custom_entry('Migrated')['base_theme'] == 'Archive Blue'
    assert not reloaded.save_custom_theme('Archive Blue', {'QWidget': '#123456'})
    assert not reloaded.save_custom_theme('Invalid', {'QWidget': 'not-a-color'})
    assert reloaded.delete_custom_theme('My Study Theme')
    assert not ThemeManager().is_custom_theme('My Study Theme')
    creator.close()
    creator.deleteLater()
    app.processEvents()
    get_theme_manager().apply_theme(app, 'Archive Blue')


def test_exam_utilities_and_associated_pdf_switching(windows, tmp_path, monkeypatch):
    import fitz
    import Core.exam_mode as exam_module
    app, dashboard, exam = windows
    exam._toggle_notes_dialog()
    assert exam.notes_dialog.isVisible()
    exam.notes_widget.set_notes_text('Keep this working for the resumed exam.')
    assert exam._current_notes_text() == 'Keep this working for the resumed exam.'
    exam._toggle_notes_dialog()
    exam._toggle_calculator_dialog()
    assert not exam._test_render_errors, exam._test_render_errors
    assert exam.calculator_dialog.isVisible()
    exam.calculator_widget.expression_edit.setText('sin(30) + 2^3')
    exam.calculator_widget._evaluate_expression()
    assert exam.calculator_widget.last_result == pytest.approx(8.5)
    exam._toggle_calculator_dialog()
    attachment = tmp_path / '0620_s24_in_11.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Associated document')
        doc.save(attachment)
    exam._register_pdf_source('insert', 'Insert', local_path=str(attachment))
    assert exam._show_pdf_source('insert')
    assert exam.pdf_viewer.page_count == 1
    exam._register_pdf_source('mark_scheme', 'Mark Scheme', local_path=str(attachment))
    monkeypatch.setattr(exam_module, 'show_info', lambda *args: None)
    assert not exam._show_pdf_source('mark_scheme')  # Preserves the submission gate.
    exam._mark_scheme_view_unlocked = True
    try:
        assert exam._show_pdf_source('mark_scheme')
        assert exam._show_pdf_source('question')
        assert exam.pdf_viewer.page_count == 2
    finally:
        exam._mark_scheme_view_unlocked = False
    from UI.font_system import discover_available_ui_fonts
    selected_font = next(name for name in discover_available_ui_fonts() if name != 'Default')
    dashboard.on_font_changed_by_user(selected_font)
    assert get_theme_manager().global_font_family() == selected_font
    dashboard.on_font_changed_by_user('Default')
    assert exam.timer_label.isVisibleTo(exam)


@pytest.mark.parametrize('theme', ['Matcha Latte', 'Old Library', 'Coffee Shop'])
def test_earth_theme_filter_labels_and_actions_remain_readable(windows, theme):
    app, dashboard, _ = windows
    get_theme_manager().apply_theme(app, theme)
    pump(app)
    shell = getattr(dashboard, '_experimental_shell', None)
    panel_bg = shell.sidebar_background() if shell else dashboard._mix_colors(Colors.BG_LIGHT, Colors.BG_DARK, 0.2)
    subject_heading = 'SUBJECTS' if shell is not None and hasattr(shell, 'subject_browser') else 'SUBJECT'
    headings = {subject_heading, 'SERIES', 'YEARS', 'PAPER COMPONENTS', 'DOCUMENT OPTIONS'}
    found = set()
    for label in dashboard.search_panel.findChildren(QLabel):
        if label.text().upper() in headings:
            from PySide6.QtGui import QPalette
            foreground = label.palette().color(QPalette.ColorRole.WindowText).name()
            assert ThemeManager._contrast_ratio(foreground, panel_bg) >= 4.5
            found.add(label.text().upper())
    assert found == headings
    from PySide6.QtGui import QPalette
    for option in (dashboard.paper_var, dashboard.ms_var, dashboard.gt_var):
        option.clearFocus()
        option.ensurePolished()
        foreground = option.palette().color(QPalette.ColorRole.WindowText).name()
        assert ThemeManager._contrast_ratio(foreground, panel_bg) >= 4.5
    checkbox_style = dashboard.paper_var.styleSheet()
    ordinary = re.search(r"QCheckBox\[controlChip='false'\] \{[^}]+}", checkbox_style)[0]
    foreground = re.search(r'(?<!-)color: (#[0-9a-fA-F]+)', ordinary)[1]
    assert ThemeManager._contrast_ratio(foreground, panel_bg) >= 4.5
    focus = re.search(r"QCheckBox\[controlChip='false'\]:focus[^}]+}", checkbox_style)[0]
    foreground = re.search(r'(?<!-)color: (#[0-9a-fA-F]+)', focus)[1]
    background = re.search(r'background-color: (#[0-9a-fA-F]+)', focus)[1]
    assert ThemeManager._contrast_ratio(foreground, background) >= 4.5
    level_bg = Colors.BG_CARD if shell else dashboard._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.18)
    foreground = re.search(r'(?<!-)color: (#[0-9a-fA-F]+)', dashboard.level_label.styleSheet())[1]
    assert ThemeManager._contrast_ratio(foreground, level_bg) >= 4.5
    for color in (Colors.PRIMARY, Colors.SECONDARY, Colors.INFO, Colors.WARNING, Colors.ACCENT_PURPLE):
        style = dashboard._action_button_style_for_theme(color)
        for state in re.findall(r'QPushButton[^{}]*{([^}]+)}', style):
            fg = re.search(r'(?<!-)color: (#[0-9a-fA-F]+)', state)
            bg = re.search(r'background-color: (#[0-9a-fA-F]+)', state)
            if fg and bg:
                minimum = 3.0 if bg[1] == dashboard._mix_colors(color, Colors.BG_CARD, 0.58) else 4.5
                assert ThemeManager._contrast_ratio(fg[1], bg[1]) >= minimum
