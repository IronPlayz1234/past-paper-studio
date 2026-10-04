"""Static decorations stay cached, stationary, bounded and theme-specific."""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from UI.static_theme_surface import DECORATED_THEMES, StaticThemeSurface
from UI.theme import get_theme_manager


@pytest.mark.parametrize('theme', sorted(DECORATED_THEMES))
def test_static_artwork_does_not_change_or_allocate_on_repaint(theme):
    app = QApplication.instance() or QApplication([])
    manager = get_theme_manager()
    manager.apply_theme(app, theme)
    surface = StaticThemeSurface(search_canvas=True)
    surface.resize(640, 420)
    surface.show()
    app.processEvents()
    first = surface.grab().toImage()
    count = surface._render_count
    key = surface._background.cacheKey()
    for _ in range(5):
        surface.update()
        app.processEvents()
        assert surface.grab().toImage() == first
    assert surface._render_count == count
    assert surface._background.cacheKey() == key
    assert not surface.findChildren(QTimer)
    bg = manager.get_theme_tokens(theme)['BG_DARK'].lower()
    assert any(first.pixelColor(x, y).name() != bg
               for x in range(0, first.width(), 7) for y in range(0, first.height(), 7))
    surface.resize(700, 440)
    surface.grab()
    assert surface._render_count == count + 1
    assert surface._background.width() * surface._background.height() <= 4_000_000
    manager.apply_theme(app, 'Simple Dark')
    app.processEvents()
    surface.grab()
    assert surface._background is None
    surface.close()
    surface.deleteLater()
    manager.apply_theme(app, 'Archive Blue')


def test_restored_purple_is_a_builtin_and_keeps_original_neon_identity():
    manager = get_theme_manager()
    assert len(manager.THEMES) == 31
    assert 'Cipher Purple' in manager.theme_names()
    assert manager.get_theme_tokens('Cipher Purple')['PRIMARY'] == '#BC13FE'
    assert 'text-shadow' not in manager.build_stylesheet('Cipher Purple')


@pytest.mark.parametrize('theme', ['Matcha Latte', 'Old Library', 'Coffee Shop'])
def test_cafe_and_library_artwork_is_subtle_and_leaves_center_clear(theme):
    from PySide6.QtGui import QColor
    app = QApplication.instance() or QApplication([])
    manager = get_theme_manager()
    manager.apply_theme(app, theme)
    surface = StaticThemeSurface(search_canvas=True)
    surface.resize(960, 640)
    surface.show()
    app.processEvents()
    artwork = surface._background.toImage()
    bg = QColor(manager.get_theme_tokens(theme)['BG_DARK'])
    # Inspect the actual rendered artwork, including anti-aliasing and overlapping ink.
    for x in range(0, 960, 5):
        for y in range(0, 640, 5):
            color = artwork.pixelColor(x, y)
            assert max(abs(color.red() - bg.red()), abs(color.green() - bg.green()),
                       abs(color.blue() - bg.blue())) <= 30
    for x in range(400, 560, 10):
        for y in range(220, 420, 10):
            if theme == 'Coffee Shop':
                # The requested espresso splash now crosses the center, but
                # remains faint enough for empty-state copy and result labels.
                color = artwork.pixelColor(x, y)
                assert max(abs(color.red()-bg.red()), abs(color.green()-bg.green()),
                           abs(color.blue()-bg.blue())) <= 20
            else:
                assert artwork.pixelColor(x, y) == bg
    surface.close()
    surface.deleteLater()
    manager.apply_theme(app, 'Archive Blue')


@pytest.mark.parametrize('theme', ['Archive Blue', "Synthwave '84", 'Carbon Fiber', 'Violet Afterburn'])
def test_new_backdrops_are_search_only_and_switch_without_residual_artwork(theme):
    app = QApplication.instance() or QApplication([])
    manager = get_theme_manager()
    results = StaticThemeSurface(search_canvas=True)
    exam = StaticThemeSurface()
    for surface in (results, exam):
        surface.resize(800, 540)
        surface.show()
    manager.apply_theme(app, 'Coffee Shop')
    app.processEvents()
    assert results._background is not None and exam._background is not None
    manager.apply_theme(app, theme)
    reference = StaticThemeSurface(search_canvas=True)
    reference.resize(800, 540)
    reference.show()
    app.processEvents()
    # A reused canvas matches a clean render exactly after changing themes.
    assert results.grab().toImage() == reference.grab().toImage()
    assert results._background is not None
    assert exam._background is None
    manager.apply_theme(app, 'Simple Dark')
    app.processEvents()
    for surface in (results, reference, exam):
        surface.grab()
        assert surface._background is None
        surface.close()
        surface.deleteLater()
    manager.apply_theme(app, 'Archive Blue')
