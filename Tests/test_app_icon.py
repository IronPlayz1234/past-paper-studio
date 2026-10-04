"""Vector asset transparency and immediate theme changes in the running app."""
from PySide6.QtGui import QColor
from Tests.test_exam_rendering_stability import app
from UI.app_icon import icon_pixmap, install_theme_app_icon
from UI.theme import get_theme_manager


def test_vector_icon_has_transparent_corners_and_readable_mark(app):
    image=icon_pixmap(1024,background='#F5EFE5',foreground='#181817',accent='#181817').toImage()
    assert image.pixelColor(0,0).alpha()==0
    assert image.pixelColor(380,400)==QColor('#181817')
    assert image.pixelColor(900,500).alpha()==255


def test_theme_change_updates_application_icon_without_files(app):
    install_theme_app_icon(app)
    theme=get_theme_manager();original=theme.current_theme()
    try:
        theme.apply_theme(app,'OLED Light');first=app.windowIcon().pixmap(256).toImage()
        theme.apply_theme(app,'Coffee Shop');second=app.windowIcon().pixmap(256).toImage()
        assert not first.isNull() and not second.isNull() and first!=second
        assert first.pixelColor(0,0).alpha()==0
    finally:theme.apply_theme(app,original)
