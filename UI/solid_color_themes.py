"""Plain, single-hue palettes with readable tonal surfaces and no artwork."""
from PySide6.QtGui import QColor


SOLID_COLOR_HUES = {
    "Solid Red": 0,
    "Solid Orange": 30,
    "Solid Yellow": 55,
    "Solid Green": 140,
    "Solid Blue": 215,
    "Solid Cyan": 185,
    "Solid Violet": 275,
    "Solid Pink": 330,
    "Solid Gray": 0,
    "Solid Brown": 25,
    "Solid Purple": 295,
    "Solid Indigo": 245,
    "Solid Silver": 215,
    "Solid Gold": 43,
    "Solid Teal": 170,
}
SOLID_COLOR_THEME_NAMES = tuple(SOLID_COLOR_HUES)


def _palette(hue, *, saturation_scale=1.0, accent_lightness=.65):
    def shade(saturation, lightness):
        return QColor.fromHslF(hue / 360, saturation * saturation_scale, lightness).name()

    accent = shade(.78, accent_lightness)
    hover = shade(.82, accent_lightness + .08)
    return {
        "PRIMARY": accent,
        "PRIMARY_HOVER": hover,
        "SECONDARY": accent,
        "SECONDARY_HOVER": hover,
        "BG_DARK": shade(.30, .065),
        "BG_MEDIUM": shade(.28, .095),
        "BG_LIGHT": shade(.25, .18),
        "BG_CARD": shade(.28, .12),
        "INPUT_BG": shade(.28, .085),
        "BORDER": shade(.28, .32),
        "SELECTION": shade(.42, .26),
        "TEXT_WHITE": shade(.16, .97),
        "TEXT_LIGHT": shade(.20, .91),
        "TEXT_GRAY": shade(.18, .71),
        "DISABLED_BG": shade(.16, .19),
        "DISABLED_TEXT": shade(.12, .53),
        # Keep every control within the chosen color family. Status labels/icons
        # still distinguish success, warning and error without unrelated hues.
        "SUCCESS": accent,
        "WARNING": hover,
        "ERROR": shade(.85, .76),
        "INFO": accent,
        "ACCENT_PURPLE": accent,
        "ACCENT_PINK": accent,
        "ACCENT_CYAN": accent,
        "ACCENT_LIGHT_BLUE": accent,
    }


SOLID_COLOR_THEMES = {name: _palette(hue) for name, hue in SOLID_COLOR_HUES.items()}
# Gray is achromatic; brown needs softer, deeper accents than orange.
SOLID_COLOR_THEMES["Solid Gray"] = _palette(0, saturation_scale=0.0)
SOLID_COLOR_THEMES["Solid Brown"] = _palette(25, saturation_scale=.55, accent_lightness=.50)
# Silver keeps cool metallic undertones; gold is warmer and deeper than yellow.
SOLID_COLOR_THEMES["Solid Silver"] = _palette(215, saturation_scale=.12, accent_lightness=.78)
SOLID_COLOR_THEMES["Solid Gold"] = _palette(43, saturation_scale=.85, accent_lightness=.58)
