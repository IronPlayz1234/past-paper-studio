from UI.theme import get_theme_manager


NEW_THEME_PALETTES = {
    "Violet Afterburn": {
        "background": "#0F0A15",
        "surface": "#1B1324",
        "surface_alt": "#251A31",
        "input_bg": "#20162B",
        "primary": "#A855F7",
        "secondary": "#F97316",
        "accent": "#E879F9",
        "text_primary": "#F9F4FF",
        "text_secondary": "#CDBEE3",
        "success": "#22D3A5",
        "warning": "#FFCA5A",
        "danger": "#FB7185",
        "selection": "#34214A",
        "disabled_bg": "#3A2E49",
        "disabled_text": "#9385A7",
    },
}


def _mapped_tokens(palette):
    return {
        "PRIMARY": palette["primary"],
        "PRIMARY_HOVER": palette["secondary"],
        "SECONDARY": palette["secondary"],
        "SECONDARY_HOVER": palette["accent"],
        "BG_DARK": palette["background"],
        "BG_MEDIUM": palette["surface"],
        "BG_LIGHT": palette["surface_alt"],
        "BG_CARD": palette["input_bg"],
        "TEXT_WHITE": palette["text_primary"],
        "TEXT_GRAY": palette["text_secondary"],
        "TEXT_LIGHT": palette["text_primary"],
        "SUCCESS": palette["success"],
        "WARNING": palette["warning"],
        "ERROR": palette["danger"],
        "INFO": palette["accent"],
        "ACCENT_PURPLE": palette["accent"],
        "ACCENT_PINK": palette["primary"],
        "ACCENT_CYAN": palette["secondary"],
        "ACCENT_LIGHT_BLUE": palette["selection"],
        "DISABLED_BG": palette["disabled_bg"],
        "DISABLED_TEXT": palette["disabled_text"],
    }


def test_new_theme_registry_contains_all_requested_theme_names():
    manager = get_theme_manager()
    for theme_name in NEW_THEME_PALETTES:
        assert theme_name in manager.theme_names()


def test_new_theme_registry_token_mapping_matches_required_values():
    manager = get_theme_manager()
    for theme_name, palette in NEW_THEME_PALETTES.items():
        tokens = manager.get_theme_tokens(theme_name)
        expected = _mapped_tokens(palette)
        for key, value in expected.items():
            assert tokens.get(key) == value
