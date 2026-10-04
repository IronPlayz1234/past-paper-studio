"""Four distinct, restrained studio palettes with plain backgrounds."""


def _palette(background, surface, raised, input_bg, text, muted, primary, hover, secondary):
    return dict(
        BG_DARK=background, BG_MEDIUM=surface, BG_CARD=surface, BG_LIGHT=raised,
        INPUT_BG=input_bg, TEXT_WHITE=text, TEXT_LIGHT=text, TEXT_GRAY=muted,
        PRIMARY=primary, PRIMARY_HOVER=hover, SECONDARY=secondary,
        SECONDARY_HOVER=hover, ACCENT_PURPLE=secondary, ACCENT_PINK=secondary,
        ACCENT_CYAN=primary, ACCENT_LIGHT_BLUE=secondary,
        SUCCESS=primary, WARNING=secondary, ERROR=secondary, INFO=primary,
    )


CLASSIC_THEMES = {
    "Solid White": _palette("#FAF9F6", "#FDFCF9", "#E7E5E1", "#FFFEFC",
                            "#292D34", "#64666B", "#343A43", "#232830", "#565D67"),
    "OLED Light": _palette("#FFFFFF", "#FFFFFF", "#E7EEF7", "#FFFFFF",
                           "#111827", "#536174", "#087AF0", "#0063CC", "#087AF0"),
    "Solid Dark": _palette("#050810", "#0B101A", "#1A2332", "#070B13",
                           "#EDF1F8", "#A6B0C1", "#CED8E8", "#E7EDF7", "#A5B4CD"),
    "OLED Dark": _palette("#000000", "#080808", "#171717", "#000000",
                          "#F5F7FA", "#A4ADB8", "#189DFF", "#55B9FF", "#189DFF"),
}
CLASSIC_THEME_NAMES = tuple(CLASSIC_THEMES)
CLASSIC_THEME_ALIASES = {
    "Simple Light": "Solid White", "Simple Dark": "Solid Dark",
    "Dark Mode": "Solid Dark", "Light Mode": "Solid White", "Simple White": "Solid White",
    "Porcelain": "Solid White", "Linen": "OLED Light",
    "Graphite": "Solid Dark", "Midnight": "OLED Dark",
}
