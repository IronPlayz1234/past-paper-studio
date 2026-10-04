"""Shared, theme-aware button feedback without changing widget geometry."""
from PySide6.QtGui import QColor
from UI.theme import get_theme_manager
from Utils.gui_utils import Colors


def button_style(background=None, foreground=None, *, primary=False, padding='6px 8px'):
    background = background or Colors.BG_CARD
    manager = get_theme_manager()
    foreground = manager._ensure_text_contrast(foreground or Colors.TEXT_LIGHT, background)
    base = QColor(background)
    hover = base.lighter(114).name() if base.lightness() < 150 else base.darker(108).name()
    pressed = base.lighter(125).name() if base.lightness() < 150 else base.darker(116).name()
    border = background if primary else Colors.BG_LIGHT
    return (f'QPushButton,QToolButton {{background:{background};color:{foreground};'
            f'border:1px solid {border};border-radius:6px;padding:{padding};font-size:14px;'
            f'font-weight:{600 if primary else 400};}} '
            f'QPushButton:hover:!disabled,QToolButton:hover:!disabled {{background:{hover};}} '
            f'QPushButton:pressed:!disabled,QToolButton:pressed:!disabled {{background:{pressed};}} '
            f'QPushButton:checked,QToolButton:checked {{border-color:{Colors.PRIMARY};background:{hover};}} '
            f'QPushButton:focus,QToolButton:focus {{border-color:{Colors.PRIMARY};}} '
            f'QPushButton:disabled,QToolButton:disabled {{color:{Colors.TEXT_GRAY};background:{Colors.BG_MEDIUM};}}')
