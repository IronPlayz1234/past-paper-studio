"""Single-hue themes stay plain, readable, selectable, and persistent."""
import pytest
from PySide6.QtGui import QColor

from UI.solid_color_themes import SOLID_COLOR_HUES, SOLID_COLOR_THEME_NAMES
from UI.static_theme_surface import StaticThemeSurface
from UI.theme import get_theme_manager, ThemeManager
from Utils.gui_utils import ConfigManager
from Tests.test_experimental_main_shell import window, groups, pump


@pytest.mark.parametrize('name', SOLID_COLOR_THEME_NAMES)
def test_solid_theme_uses_one_hue_with_readable_surfaces(name):
    manager = get_theme_manager()
    assert name in manager.theme_names()
    tokens = manager.get_theme_tokens(name)
    for value in tokens.values():
        color = QColor(value)
        assert color.isValid()
        if name == 'Solid Gray':
            assert color.red() == color.green() == color.blue()
        # Near-white text has too few chromatic RGB steps for precise hue
        # round-trips; check visibly colored shades instead.
        if max(color.red(), color.green(), color.blue()) - min(color.red(), color.green(), color.blue()) >= 10:
            distance = abs(color.hslHue() - SOLID_COLOR_HUES[name])
            assert min(distance, 360-distance) <= 6
    for surface in ('BG_DARK', 'BG_CARD', 'INPUT_BG'):
        for text in ('TEXT_WHITE', 'TEXT_LIGHT', 'TEXT_GRAY'):
            assert ThemeManager._contrast_ratio(tokens[text], tokens[surface]) >= 4.5
    assert tokens['PRIMARY'] == tokens['SECONDARY']
    stylesheet = manager.build_stylesheet(name)
    assert 'qlineargradient' not in stylesheet


@pytest.mark.parametrize('name', SOLID_COLOR_THEME_NAMES)
def test_solid_theme_applies_to_dashboard_and_has_no_decorations(window, name):
    app, gui = window
    manager = get_theme_manager()
    manager.apply_theme(app, name)
    gui.display_results(groups(), record_history=False)
    pump(app)
    assert manager.current_theme() == name
    for surface in gui.findChildren(StaticThemeSurface):
        assert surface.background_pixmap() is None
    gui._ensure_settings_window()
    settings = gui._settings_window
    assert settings.theme_names_for_section('Solid Colors') == list(SOLID_COLOR_THEME_NAMES)
    assert 'Signature Themes' in settings.theme_section_titles()
    assert 'Colorful' not in settings.theme_section_titles()
    settings._theme_cards[name.casefold()].clicked.emit(name)
    assert ConfigManager.get_value('ui.theme') == name
    ConfigManager._CACHE = None
    assert ConfigManager.get_value('ui.theme') == name
