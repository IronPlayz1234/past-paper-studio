"""Centralized Qt theme management for the application."""

from __future__ import annotations
from Core.runtime_paths import user_data_path
from Core.atomic_storage import atomic_write_json

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from Core.runtime_paths import resource_path
from UI.font_system import DEFAULT_FONT_OPTION, build_global_font_qss
from UI.solid_color_themes import SOLID_COLOR_THEMES, SOLID_COLOR_THEME_NAMES
from UI.classic_themes import CLASSIC_THEMES, CLASSIC_THEME_NAMES, CLASSIC_THEME_ALIASES


def _resource_uri(*parts: str) -> str:
    """Return a QSS-safe resource URI/path in source or bundled runtime."""
    path = Path(resource_path(*parts))
    # Plain absolute paths are the most reliable for Qt stylesheet image urls.
    # file:// URIs can fail on some platforms/themes when spaces are present.
    try:
        return str(path.resolve()).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


class ThemeConfig:
    """Central registry for theme dictionaries and resource wiring."""

    DEFAULT_THEME = "Archive Blue"
    CUSTOM_THEMES_FILE = user_data_path("custom_themes.json")
    THEME_ALIASES: Dict[str, str] = {}
    THEMES: Dict[str, Dict[str, str]] = {}
    THEME_EXTRAS: Dict[str, str] = {}

    @classmethod
    def register(
        cls,
        *,
        theme_aliases: Dict[str, str],
        themes: Dict[str, Dict[str, str]],
        theme_extras: Dict[str, str],
    ) -> None:
        cls.THEME_ALIASES = dict(theme_aliases)
        cls.THEMES = {name: dict(tokens) for name, tokens in themes.items()}
        cls.THEME_EXTRAS = dict(theme_extras)


class ThemeManager(QObject):
    """Stores and applies app-wide themes."""

    theme_changed = Signal(str)
    _RGBA_COLOR_RE = re.compile(
        r"rgba?\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})(?:\s*,\s*([0-9]*\.?[0-9]+%?))?\s*\)",
        re.IGNORECASE,
    )
    _ASSETS_DIR = Path(resource_path("UI", "assets"))
    _CHECKBOX_TICK_LIGHT_PATH = _resource_uri("UI", "assets", "checkbox_tick_light.png")
    _CHECKBOX_TICK_DARK_PATH = _resource_uri("UI", "assets", "checkbox_tick_dark.png")

    DEFAULT_THEME = ThemeConfig.DEFAULT_THEME
    CUSTOM_THEMES_FILE = ThemeConfig.CUSTOM_THEMES_FILE
    _CUSTOM_THEMES_VERSION = 1
    _HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
    _CUSTOM_WIDGET_TYPES = (
        "QPushButton",
        "QFrame",
        "QLineEdit",
        "QTextEdit",
        "QPlainTextEdit",
        "QComboBox",
        "QListWidget",
        "QCheckBox",
        "QLabel",
        "QWidget",
    )
    THEME_ALIASES = {'Legacy': 'Archive Blue', 'Default': 'Archive Blue', 'Dark Mode': 'Simple Dark', 'Light Mode': 'Simple Light', 'Simple White': 'Simple Light', 'Matrix Rain': 'Cipher Green', 'Matrix Green': 'Cipher Green', 'Matrix Red': 'Cipher Red', 'Matrix Purple': 'Cipher Purple'}
    THEMES = {
        "Archive Blue": {
            "PRIMARY": "#00B8D9",
            "PRIMARY_HOVER": "#18D1F0",
            "SECONDARY": "#7B2FF7",
            "SECONDARY_HOVER": "#6923D6",
            "BG_DARK": "#0E1220",
            "BG_MEDIUM": "#151A2E",
            "BG_LIGHT": "#1D2440",
            "BG_CARD": "#121830",
            "TEXT_WHITE": "#F5F7FF",
            "TEXT_GRAY": "#AAB4D6",
            "TEXT_LIGHT": "#DCE3FF",
            "SUCCESS": "#32D583",
            "WARNING": "#F9C74F",
            "ERROR": "#FF5D73",
            "INFO": "#4CC9F0",
            "ACCENT_PURPLE": "#9D4EDD",
            "ACCENT_PINK": "#FF4FD8",
            "ACCENT_CYAN": "#2EE6FF",
            "ACCENT_LIGHT_BLUE": "#B7FF2A",
        },
        "Synthwave '84": {
            "PRIMARY": "#FF4FA3",
            "PRIMARY_HOVER": "#E64294",
            "SECONDARY": "#FF8C42",
            "SECONDARY_HOVER": "#E67735",
            "BG_DARK": "#120B2E",
            "BG_MEDIUM": "#1A1240",
            "BG_LIGHT": "#23185A",
            "BG_CARD": "#2A1D66",
            "TEXT_WHITE": "#F4EDFF",
            "TEXT_GRAY": "#CDBCEB",
            "TEXT_LIGHT": "#E9DBFF",
            "SUCCESS": "#50C878",
            "WARNING": "#FFB347",
            "ERROR": "#FF5D73",
            "INFO": "#7CD1FF",
            "ACCENT_PURPLE": "#B68CFF",
            "ACCENT_PINK": "#FF4FA3",
            "ACCENT_CYAN": "#59D6FF",
            "ACCENT_LIGHT_BLUE": "#8EC8FF",
        },
        "Coffee Shop": {
            "PRIMARY": "#A8754E",
            "PRIMARY_HOVER": "#92613E",
            "SECONDARY": "#B4926E",
            "SECONDARY_HOVER": "#A1815E",
            "BG_DARK": "#2D241E",
            "BG_MEDIUM": "#3A2F27",
            "BG_LIGHT": "#4A3B31",
            "BG_CARD": "#56453A",
            "TEXT_WHITE": "#F3E8DB",
            "TEXT_GRAY": "#D4C2B0",
            "TEXT_LIGHT": "#EADFD3",
            "SUCCESS": "#8B9670",
            "WARNING": "#C89B68",
            "ERROR": "#B85B5B",
            "INFO": "#9B8069",
            "ACCENT_PURPLE": "#9B7A63",
            "ACCENT_PINK": "#B6846A",
            "ACCENT_CYAN": "#BE9C7B",
            "ACCENT_LIGHT_BLUE": "#D4B99B",
        },
        "Old Library": {
            "PRIMARY": "#AC8B56",
            "PRIMARY_HOVER": "#967647",
            "SECONDARY": "#8C7047",
            "SECONDARY_HOVER": "#765D3A",
            "BG_DARK": "#2C1E12",
            "BG_MEDIUM": "#3A281A",
            "BG_LIGHT": "#C7B58F",
            "BG_CARD": "#352417",
            "TEXT_WHITE": "#F5ECDD",
            "TEXT_GRAY": "#DCCCB2",
            "TEXT_LIGHT": "#EFE4D0",
            "SUCCESS": "#8A9161",
            "WARNING": "#C6A76D",
            "ERROR": "#B5685B",
            "INFO": "#9B8060",
            "ACCENT_PURPLE": "#997044",
            "ACCENT_PINK": "#AD8063",
            "ACCENT_CYAN": "#BAA070",
            "ACCENT_LIGHT_BLUE": "#D4C29C",
        },
        "Matcha Latte": {
            "PRIMARY": "#93AB8D",
            "PRIMARY_HOVER": "#819A7B",
            "SECONDARY": "#C9A66B",
            "SECONDARY_HOVER": "#B69158",
            "BG_DARK": "#31473A",
            "BG_MEDIUM": "#3B5647",
            "BG_LIGHT": "#D4D5BE",
            "BG_CARD": "#2A3D32",
            "TEXT_WHITE": "#F7F3EC",
            "TEXT_GRAY": "#CED6C4",
            "TEXT_LIGHT": "#E8E2D8",
            "SUCCESS": "#8FA77E",
            "WARNING": "#C9A66B",
            "ERROR": "#B56C58",
            "INFO": "#93A98D",
            "ACCENT_PURPLE": "#C9A66B",
            "ACCENT_PINK": "#B79C70",
            "ACCENT_CYAN": "#A9B69A",
            "ACCENT_LIGHT_BLUE": "#CCD1B7",
        },
        "Cipher Green": {
            "PRIMARY": "#22C55E",
            "PRIMARY_HOVER": "#34D472",
            "SECONDARY": "#15803D",
            "SECONDARY_HOVER": "#16A34A",
            "BG_DARK": "#050B07",
            "BG_MEDIUM": "#0B1710",
            "BG_LIGHT": "#102219",
            "BG_CARD": "#0C1A12",
            "TEXT_WHITE": "#E5FCE8",
            "TEXT_GRAY": "#9DC7A6",
            "TEXT_LIGHT": "#CFF7D5",
            "SUCCESS": "#50C878",
            "WARNING": "#C7A447",
            "ERROR": "#D46A6A",
            "INFO": "#58D68D",
            "ACCENT_PURPLE": "#2EB872",
            "ACCENT_PINK": "#4ADE80",
            "ACCENT_CYAN": "#14532D",
            "ACCENT_LIGHT_BLUE": "#86EFAC",
        },
        "Cipher Purple": {
            "PRIMARY": "#BC13FE",
            "PRIMARY_HOVER": "#CF49FF",
            "SECONDARY": "#8A2BE2",
            "SECONDARY_HOVER": "#A245FF",
            "BG_DARK": "#0B0711",
            "BG_MEDIUM": "#170E22",
            "BG_LIGHT": "#241432",
            "BG_CARD": "#1B1028",
            "TEXT_WHITE": "#F3E6FF",
            "TEXT_GRAY": "#C4A1DC",
            "TEXT_LIGHT": "#F8EEFF",
            "SUCCESS": "#50C878",
            "WARNING": "#C7A447",
            "ERROR": "#D46A6A",
            "INFO": "#BC13FE",
            "ACCENT_PURPLE": "#BC13FE",
            "ACCENT_PINK": "#D67BFF",
            "ACCENT_CYAN": "#2D005C",
            "ACCENT_LIGHT_BLUE": "#8A54B8",
        },
        "Cipher Red": {
            "PRIMARY": "#FF3131",
            "PRIMARY_HOVER": "#FF5C5C",
            "SECONDARY": "#C1121F",
            "SECONDARY_HOVER": "#D22727",
            "BG_DARK": "#0D0608",
            "BG_MEDIUM": "#1C0C10",
            "BG_LIGHT": "#2A1218",
            "BG_CARD": "#1F0E14",
            "TEXT_WHITE": "#FFEAEA",
            "TEXT_GRAY": "#D7A5A5",
            "TEXT_LIGHT": "#FFF2F2",
            "SUCCESS": "#50C878",
            "WARNING": "#C7A447",
            "ERROR": "#FF3131",
            "INFO": "#FF3131",
            "ACCENT_PURPLE": "#C35555",
            "ACCENT_PINK": "#FF7A7A",
            "ACCENT_CYAN": "#4B0000",
            "ACCENT_LIGHT_BLUE": "#B33D3D",
        },
        "Carbon Fiber": {
            "PRIMARY": "#E11D48",
            "PRIMARY_HOVER": "#BE123C",
            "SECONDARY": "#BDBDBD",
            "SECONDARY_HOVER": "#929292",
            "BG_DARK": "#0D0D0D",
            "BG_MEDIUM": "#141414",
            "BG_LIGHT": "#1F1F1F",
            "BG_CARD": "#171717",
            "TEXT_WHITE": "#FAFAFA",
            "TEXT_GRAY": "#737373",
            "TEXT_LIGHT": "#D4D4D4",
            "SUCCESS": "#22C55E",
            "WARNING": "#F59E0B",
            "ERROR": "#EF4444",
            "INFO": "#3B82F6",
            "ACCENT_PURPLE": "#7C3AED",
            "ACCENT_PINK": "#DB2777",
            "ACCENT_CYAN": "#3B82F6",
            "ACCENT_LIGHT_BLUE": "#BDBDBD",
        },
        "Aurora Borealis": {
            "PRIMARY": "#00F2FE",
            "PRIMARY_HOVER": "#4FACFE",
            "SECONDARY": "#4FACFE",
            "SECONDARY_HOVER": "#3793E5",
            "BG_DARK": "#05070A",
            "BG_MEDIUM": "#0A1018",
            "BG_LIGHT": "#101827",
            "BG_CARD": "#0D1421",
            "TEXT_WHITE": "#F4F9FF",
            "TEXT_GRAY": "#B5C7D8",
            "TEXT_LIGHT": "#D7E8F8",
            "SUCCESS": "#50C878",
            "WARNING": "#E8B46A",
            "ERROR": "#E06C75",
            "INFO": "#4FACFE",
            "ACCENT_PURPLE": "#4FACFE",
            "ACCENT_PINK": "#8BC6FF",
            "ACCENT_CYAN": "#00F2FE",
            "ACCENT_LIGHT_BLUE": "#9BD7FF",
        },
        "Violet Afterburn": {
            "PRIMARY": "#A855F7",
            "PRIMARY_HOVER": "#F97316",
            "SECONDARY": "#F97316",
            "SECONDARY_HOVER": "#E879F9",
            "BG_DARK": "#0F0A15",
            "BG_MEDIUM": "#1B1324",
            "BG_LIGHT": "#251A31",
            "BG_CARD": "#20162B",
            "TEXT_WHITE": "#F9F4FF",
            "TEXT_GRAY": "#CDBEE3",
            "TEXT_LIGHT": "#F9F4FF",
            "SUCCESS": "#22D3A5",
            "WARNING": "#FFCA5A",
            "ERROR": "#FB7185",
            "INFO": "#E879F9",
            "ACCENT_PURPLE": "#E879F9",
            "ACCENT_PINK": "#A855F7",
            "ACCENT_CYAN": "#F97316",
            "ACCENT_LIGHT_BLUE": "#34214A",
            "INPUT_BG": "#20162B",
            "BORDER": "#69418D",
            "SELECTION": "#34214A",
            "DISABLED_BG": "#3A2E49",
            "DISABLED_TEXT": "#9385A7",
        },
    }
    THEME_ALIASES.update(CLASSIC_THEME_ALIASES)
    THEMES.update(CLASSIC_THEMES)
    THEMES.update(SOLID_COLOR_THEMES)
    THEMES['Crimson Meridian'] = {
        'PRIMARY': '#E56A7C', 'PRIMARY_HOVER': '#F28B99',
        'SECONDARY': '#CFAC78', 'SECONDARY_HOVER': '#E3C597',
        'BG_DARK': '#160D12', 'BG_MEDIUM': '#21131B',
        'BG_LIGHT': '#432632', 'BG_CARD': '#2B1822', 'INPUT_BG': '#1A1016',
        'BORDER': '#744453', 'SELECTION': '#602E40',
        'TEXT_WHITE': '#FFF1E9', 'TEXT_LIGHT': '#EEDDD8', 'TEXT_GRAY': '#C5ABA9',
        'DISABLED_BG': '#35232B', 'DISABLED_TEXT': '#9B8489',
        'SUCCESS': '#B9BA90', 'WARNING': '#D8B67E', 'ERROR': '#F18490',
        'INFO': '#D9A5AD', 'ACCENT_PURPLE': '#B88FAD', 'ACCENT_PINK': '#E56A7C',
        'ACCENT_CYAN': '#CFAC78', 'ACCENT_LIGHT_BLUE': '#E3C597',
    }

    HIDDEN_THEMES = {

    }

    THEME_EXTRAS = {
        "Synthwave '84": """
        QMainWindow {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #120B2E, stop:0.55 #2A1D66, stop:1 #FF8C42);
        }
        QFrame#card {
            border: 1px solid #FF4FA3;
        }
        """,
        "Carbon Fiber": """
        QFrame#card {
            border: 1px solid #2A2A2A;
        }
        QPushButton {
            border: 1px solid #2A2A2A;
        }
        QPushButton:hover {
            border: 1px solid #E11D48;
        }
        """,
        "Aurora Borealis": """
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #5FD8F0, stop:0.38 #00F2FE, stop:1 #4FACFE);
            border: 2px solid #1E3A5F;
            border-radius: 10px;
            color: #062036;
            padding: 8px 16px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #DBFBFF, stop:0.34 #74FBFF, stop:1 #89CBFF);
            border: 2px solid #34D399;
        }
        QPushButton[auroraHover="true"] {
            border: 2px solid #34D399;
        }
        QPushButton:pressed {
            padding: 8px 16px;
        }
        QHeaderView::section {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00F2FE, stop:1 #4FACFE);
            color: #062036;
            border: none;
            padding: 6px;
        }
        QProgressBar {
            background-color: #0A1018;
            color: #FFFFFF;
            border: 1px solid #1E2B3E;
            border-radius: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00F2FE, stop:1 #4FACFE);
            border-radius: 8px;
        }
        """,
        "Cipher Green": """
        QFrame#card {
            border: 1px solid #1F3A2A;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 2px solid #2EB872;
        }
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #14532D, stop:1 #166534);
            border: 1px solid #2A6A44;
            border-radius: 10px;
            color: #E5FCE8;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #166534, stop:1 #1B7A41);
            border: 1px solid #4ADE80;
        }
        QProgressBar {
            background-color: #080808;
            color: #E5FCE8;
            border: 1px solid #1F3A2A;
            border-radius: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #22C55E, stop:1 #4ADE80);
            border-radius: 8px;
        }
        """,
        "Cipher Purple": """
        QFrame#card {
            border: 1px solid #2D005C;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 2px solid #BC13FE;
        }
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2D005C, stop:1 #BC13FE);
            border: 1px solid #BC13FE;
            border-radius: 10px;
            color: #F8EEFF;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3B0A76, stop:1 #D24BFF);
            border: 1px solid #E39BFF;
        }
        QProgressBar {
            background-color: #080808;
            color: #F8EEFF;
            border: 1px solid #2D005C;
            border-radius: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #BC13FE, stop:1 #D879FF);
            border-radius: 8px;
        }
        """,
        "Cipher Red": """
        QFrame#card {
            border: 1px solid #4B0000;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 2px solid #FF3131;
        }
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4B0000, stop:1 #FF3131);
            border: 1px solid #FF3131;
            border-radius: 10px;
            color: #FFF2F2;
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #680909, stop:1 #FF5C5C);
            border: 1px solid #FF9393;
        }
        QProgressBar {
            background-color: #080808;
            color: #FFF2F2;
            border: 1px solid #4B0000;
            border-radius: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #FF3131, stop:1 #FF7A7A);
            border-radius: 8px;
        }
        """,
        "Old Library": """
        QFrame#card {
            border: 1px solid #9A825F;
        }
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
            background-color: #C7B58F;
            color: #2C1E12;
            border: 1px solid #9A825F;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 2px solid #BAA070;
        }
        QComboBox QAbstractItemView {
            background-color: #3A281A;
            color: #FFFFFF;
            border: 1px solid #9A825F;
            selection-background-color: #9A825F;
            selection-color: #2C1E12;
            outline: 0;
        }
        QComboBox QAbstractItemView::item {
            color: #FFFFFF;
            min-height: 24px;
            padding: 4px 8px;
        }
        QComboBox QAbstractItemView::item:selected {
            color: #2C1E12;
        }
        QPushButton {
            border: 1px solid #7D6848;
        }
        QPushButton:hover {
            border: 1px solid #BAA070;
        }
        QProgressBar {
            background-color: #3A281A;
            color: #F5ECDD;
            border: 1px solid #9A825F;
            border-radius: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #9A825F, stop:1 #BAA070);
            border-radius: 8px;
        }
        """,
        "Matcha Latte": """
        QFrame#card {
            border: 1px solid #93AB8D;
        }
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
            background-color: #D4D5BE;
            color: #31473A;
            border: 1px solid #93AB8D;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
            border: 2px solid #C9A66B;
        }
        QComboBox QAbstractItemView {
            background-color: #3B5647;
            color: #FFFFFF;
            border: 1px solid #93AB8D;
            selection-background-color: #93AB8D;
            selection-color: #24382A;
            outline: 0;
        }
        QComboBox QAbstractItemView::item {
            color: #FFFFFF;
            min-height: 24px;
            padding: 4px 8px;
        }
        QComboBox QAbstractItemView::item:selected {
            color: #24382A;
        }
        QPushButton {
            border: 1px solid #6F867B;
        }
        QPushButton:hover {
            border: 1px solid #C9A66B;
        }
        QProgressBar {
            background-color: #3B5647;
            color: #F7F3EC;
            border: 1px solid #93AB8D;
            border-radius: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #93AB8D, stop:1 #C9A66B);
            border-radius: 8px;
        }
        """,
    }
    HIDDEN_THEME_EXTRAS = {

    }

    _QSS_TEMPLATE = """
    QMainWindow {{
        background-color: {BG_DARK};
    }}

    QWidget {{
        color: {TEXT_WHITE};
    }}

    QFrame#card {{
        background-color: {BG_CARD};
        border: 1px solid transparent;
        border-radius: 10px;
    }}

    QFrame[themeRole="controlCenter"] {{
        background-color: {CONTROL_CENTER_BG};
        border: 1px solid {CONTROL_CENTER_BORDER};
        border-radius: 12px;
    }}

    QFrame[themeRole="resultCard"] {{
        background-color: {RESULT_CARD_BG};
        border: 1px solid {RESULT_CARD_BORDER};
        border-radius: 12px;
    }}

    QFrame[themeRole="resultCard"][hovered="true"] {{
        background-color: {RESULT_CARD_BG_HOVER};
        border: 1px solid {PRIMARY_HOVER};
    }}

    QFrame[themeRole="historyCard"] {{
        background-color: {HISTORY_CARD_BG};
        border: 1px solid {HISTORY_CARD_BORDER};
        border-radius: 10px;
    }}

    QFrame[themeRole="historyCard"][hovered="true"] {{
        background-color: {RESULT_CARD_BG_HOVER};
        border: 1px solid {PRIMARY_HOVER};
    }}

    QFrame[themeRole="groupCard"] {{
        background-color: {CONTROL_CENTER_BG};
        border: 1px solid {BUTTON_HOVER_BORDER};
        border-radius: 12px;
    }}

    QFrame[themeRole="groupCard"][hovered="true"] {{
        background-color: {RESULT_CARD_BG_HOVER};
        border: 1px solid {PRIMARY_HOVER};
    }}

    QFrame[themeRole="skeletonCard"] {{
        background-color: {SKELETON_BASE};
        border: 1px solid {RESULT_CARD_BORDER};
        border-radius: 12px;
    }}

    QFrame[themeRole="previewOverlay"] {{
        background-color: {PREVIEW_OVERLAY_BG};
        border: 1px solid {PREVIEW_OVERLAY_BORDER};
        border-radius: 10px;
    }}

    QPushButton {{
        background-color: {PRIMARY};
        color: {BUTTON_TEXT};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 8px 16px;
        min-width: 0px;
        min-height: 34px;
        font-size: 13px;
        font-weight: bold;
    }}

    QPushButton:hover:!disabled {{
        background-color: {PRIMARY_HOVER};
        color: {BUTTON_TEXT_HOVER};
        border: 1px solid {BUTTON_HOVER_BORDER};
    }}

    QPushButton:pressed {{
        background-color: {PRIMARY_HOVER};
        color: {BUTTON_TEXT_HOVER};
        border: 1px solid {BUTTON_HOVER_BORDER};
        padding: 8px 16px;
    }}

    QPushButton:disabled {{
        background-color: {DISABLED_BG};
        border: 1px solid {DISABLED_BORDER};
        color: {DISABLED_TEXT};
    }}

    QToolButton {{
        background-color: {INPUT_TINT_BG};
        color: {TOOL_BUTTON_TEXT};
        border: 1px solid {CONTROL_CENTER_BORDER};
        border-radius: 8px;
        padding: 6px 12px;
        min-width: 0px;
        min-height: 28px;
        font-size: 12px;
        font-weight: 600;
    }}

    QToolButton:hover:!disabled {{
        background-color: {BG_LIGHT};
        color: {TOOL_BUTTON_TEXT_HOVER};
        border: 1px solid {BUTTON_HOVER_BORDER};
    }}

    QToolButton:checked {{
        background-color: {PRIMARY};
        color: {PRIMARY_TEXT};
        border: 1px solid {BUTTON_HOVER_BORDER};
    }}

    QToolButton:pressed {{
        background-color: {PRIMARY_HOVER};
        color: {BUTTON_TEXT_HOVER};
        border: 1px solid {BUTTON_HOVER_BORDER};
    }}

    QToolButton:disabled {{
        background-color: {DISABLED_BG};
        color: {DISABLED_TEXT};
        border: 1px solid {DISABLED_BORDER};
    }}

    QToolButton#resultsViewModeButton {{
        min-height: 30px;
        padding: 6px 12px;
    }}

    QToolButton#controlCenterToggleButton {{
        min-width: 28px;
        max-width: 28px;
        min-height: 28px;
        max-height: 28px;
        padding: 0px;
        font-size: 12px;
        font-weight: 700;
        border-radius: 7px;
    }}

    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
        background-color: {INPUT_TINT_BG};
        color: {INPUT_TEXT};
        border: 1px solid {BG_MEDIUM};
        border-radius: 6px;
        padding: 6px;
        font-size: 12px;
    }}

    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{
        border: 1px solid {BUTTON_HOVER_BORDER};
    }}

    QComboBox {{
        combobox-popup: 0;
    }}

    QComboBox QAbstractItemView {{
        background-color: {BG_CARD};
        color: {TEXT_WHITE};
        border: 1px solid {BG_LIGHT};
        selection-background-color: {PRIMARY};
        selection-color: {PRIMARY_TEXT};
        outline: 0;
    }}

    QComboBox QAbstractItemView::item {{
        min-height: 24px;
        padding: 4px 8px;
    }}

    QListWidget::item {{
        border: 1px solid transparent;
        padding: 4px 8px;
    }}

    QListWidget::item:hover {{
        background-color: {BG_LIGHT};
        color: {LIST_ITEM_HOVER_TEXT};
        border: 1px solid transparent;
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border: 1px solid {INPUT_FOCUS_BORDER};
    }}

    QLabel {{
        color: {TEXT_WHITE};
        background-color: transparent;
    }}

    QLabel[themeRole="sectionHeader"] {{
        color: {CONTROL_CENTER_HEADER_TEXT};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        padding-top: 2px;
        padding-bottom: 2px;
    }}

    QLabel[themeRole="paperCode"] {{
        color: {PAPER_CODE_TEXT};
        font-family: "JetBrains Mono", "Roboto Mono", "Menlo", "Consolas", monospace;
        font-weight: 600;
        font-size: 11px;
    }}

    QLabel[themeRole="metadata"] {{
        color: {META_TEXT};
        font-size: 11px;
        font-weight: 400;
    }}

    QCheckBox {{
        color: {TEXT_WHITE};
        spacing: 8px;
        padding: 2px 0px;
        background-color: transparent;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1px solid {CHECKBOX_BORDER};
        border-radius: 4px;
        background-color: {CHECKBOX_BG};
    }}

    QCheckBox::indicator:unchecked {{
        image: none;
    }}

    QCheckBox::indicator:hover {{
        border: 1px solid {CHECKBOX_BORDER_HOVER};
        background-color: {CHECKBOX_BG_HOVER};
    }}

    QCheckBox::indicator:checked {{
        image: url("{CHECKBOX_TICK_ICON}");
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG};
    }}

    QCheckBox::indicator:checked:pressed {{
        image: url("{CHECKBOX_TICK_ICON}");
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG_HOVER};
    }}

    QCheckBox::indicator:checked:hover {{
        image: url("{CHECKBOX_TICK_ICON}");
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG_HOVER};
    }}

    QCheckBox::indicator:checked:disabled {{
        image: url("{CHECKBOX_TICK_ICON}");
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG};
    }}

    QCheckBox::indicator:disabled {{
        border: 1px solid {DISABLED_BORDER};
        background-color: {DISABLED_BG};
    }}

    QRadioButton {{
        color: {TEXT_WHITE};
        spacing: 8px;
        padding: 2px 0px;
        background-color: transparent;
    }}

    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 9px;
        border: 1px solid {CHECKBOX_BORDER};
        background-color: {CHECKBOX_BG};
    }}

    QRadioButton::indicator:hover {{
        border: 1px solid {CHECKBOX_BORDER_HOVER};
        background-color: {CHECKBOX_BG_HOVER};
    }}

    QRadioButton::indicator:checked {{
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG};
    }}

    QRadioButton::indicator:checked:hover,
    QRadioButton::indicator:checked:pressed {{
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG_HOVER};
    }}

    QRadioButton::indicator:checked:disabled {{
        border: 1px solid {CHECKBOX_CHECKED_BORDER};
        background-color: {CHECKBOX_CHECKED_BG};
    }}

    QRadioButton::indicator:disabled {{
        border: 1px solid {DISABLED_BORDER};
        background-color: {DISABLED_BG};
    }}

    QScrollBar:vertical {{
        background: {THIN_SCROLLBAR_BG};
        width: 9px;
        border-radius: 4px;
        margin: 0px;
    }}

    QScrollBar::handle:vertical {{
        background: {THIN_SCROLLBAR_HANDLE};
        border-radius: 4px;
        min-height: 20px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {PRIMARY_HOVER};
    }}

    QScrollBar:horizontal {{
        background: {THIN_SCROLLBAR_BG};
        height: 9px;
        border-radius: 4px;
        margin: 0px;
    }}

    QScrollBar::handle:horizontal {{
        background: {THIN_SCROLLBAR_HANDLE};
        border-radius: 4px;
        min-width: 20px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {PRIMARY_HOVER};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
        height: 0px;
    }}

    QMenu {{
        background-color: {MENU_BG};
        color: {TEXT_WHITE};
        border: 1px solid {MENU_BORDER};
    }}

    QMenu::item {{
        padding: 6px 14px;
        background-color: transparent;
        color: {TEXT_WHITE};
    }}

    QMenu::item:selected {{
        background-color: #F59E0B;
        color: {WARNING_TEXT};
    }}

    QMenu::item:disabled {{
        color: {TEXT_GRAY};
        background-color: {MENU_DISABLED_BG};
    }}

    QMenu::item:disabled:selected {{
        background-color: #F59E0B;
        color: {WARNING_DISABLED_TEXT};
    }}
    """

    _STABLE_LAYOUT_QSS = """
    QFrame#card {
        border-width: 1px;
        border-style: solid;
    }

    QPushButton {
        border-width: 1px;
        border-style: solid;
        padding: 8px 16px;
        min-height: 34px;
        min-width: 0px;
    }

    QPushButton:hover:!disabled {
        border-width: 1px;
        padding: 8px 16px;
        min-height: 34px;
        min-width: 0px;
    }

    QPushButton:pressed {
        border-width: 1px;
        padding: 8px 16px;
        min-height: 34px;
        min-width: 0px;
    }

    QPushButton:disabled {
        border-width: 1px;
        padding: 8px 16px;
        min-height: 34px;
        min-width: 0px;
    }

    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
        border-width: 1px;
        border-style: solid;
    }

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
        border-width: 1px;
    }

    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover {
        border-width: 1px;
    }

    QListWidget::item {
        border-width: 1px;
        border-style: solid;
    }

    QListWidget::item:hover {
        border-width: 1px;
        border-style: solid;
    }

    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border-width: 1px;
        border-style: solid;
    }

    QCheckBox::indicator:hover,
    QCheckBox::indicator:checked,
    QCheckBox::indicator:checked:hover,
    QCheckBox::indicator:disabled {
        border-width: 1px;
    }
    """

    def __init__(self):
        super().__init__()
        self._current_theme = self.DEFAULT_THEME
        self._global_font_family = DEFAULT_FONT_OPTION
        self._custom_themes: Dict[str, Dict[str, Any]] = {}
        self._composed_stylesheet_cache: Dict[tuple[str, str], str] = {}
        self._last_applied_font_family: str = self._global_font_family
        self._theme_revision: int = 0
        self._last_applied_revision: int = -1
        self._load_custom_themes()
        ThemeConfig.register(
            theme_aliases=self.THEME_ALIASES,
            themes=self.THEMES,
            theme_extras=self.THEME_EXTRAS,
        )

    def _invalidate_theme_caches(self) -> None:
        self._composed_stylesheet_cache.clear()

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalized_name(name: str) -> str:
        return str(name or "").strip()

    def _is_builtin_or_alias_name(self, name: str) -> bool:
        needle = self._normalized_name(name).casefold()
        if not needle:
            return False
        for candidate in (*self.THEMES.keys(), *self.HIDDEN_THEMES.keys()):
            if candidate.casefold() == needle:
                return True
        for candidate in self.THEME_ALIASES:
            if candidate.casefold() == needle:
                return True
        return False

    def _resolve_builtin_theme_name(self, name: str) -> Optional[str]:
        candidate = self._normalized_name(name)
        candidate = self.THEME_ALIASES.get(candidate, candidate)
        if candidate in self.THEMES:
            return candidate
        if candidate in self.HIDDEN_THEMES:
            return candidate
        return None

    def _match_custom_theme_name(self, name: str) -> Optional[str]:
        needle = self._normalized_name(name).casefold()
        if not needle:
            return None
        for custom_name in self._custom_themes.keys():
            if custom_name.casefold() == needle:
                return custom_name
        return None

    def _normalize_hex_color(self, color_text: str) -> Optional[str]:
        text = self._normalized_name(color_text)
        if not text:
            return None
        color = QColor(text)
        if not color.isValid():
            return None
        normalized = color.name().upper()
        if self._HEX_COLOR_RE.fullmatch(normalized) is None:
            return None
        return normalized

    def _sanitize_widget_colors(self, widget_colors: Any) -> Dict[str, str]:
        clean: Dict[str, str] = {}
        if not isinstance(widget_colors, dict):
            return clean
        for raw_widget_type, raw_color in widget_colors.items():
            widget_type = self._normalized_name(str(raw_widget_type))
            if widget_type not in self._CUSTOM_WIDGET_TYPES:
                continue
            color_value = self._normalize_hex_color(str(raw_color))
            if color_value:
                clean[widget_type] = color_value
        return clean

    def _coerce_base_theme_name(self, base_theme: str) -> str:
        resolved = self._resolve_builtin_theme_name(base_theme)
        return resolved if resolved else self.DEFAULT_THEME

    def _sanitize_custom_theme_record(self, raw_name: str, raw_entry: Any) -> Optional[Dict[str, Any]]:
        name = self._normalized_name(raw_name)
        if not name or self._is_builtin_or_alias_name(name):
            return None
        if not isinstance(raw_entry, dict):
            return None

        base_theme = self._coerce_base_theme_name(str(raw_entry.get("base_theme", self.DEFAULT_THEME)))
        widget_colors = self._sanitize_widget_colors(raw_entry.get("widget_colors", {}))
        if not widget_colors:
            return None

        updated_at = self._normalized_name(str(raw_entry.get("updated_at", ""))) or self._utc_timestamp()
        return {
            "base_theme": base_theme,
            "widget_colors": widget_colors,
            "updated_at": updated_at,
        }

    def _custom_theme_payload(self) -> Dict[str, Any]:
        themes: Dict[str, Dict[str, Any]] = {}
        for name in sorted(self._custom_themes.keys(), key=str.casefold):
            entry = self._custom_themes[name]
            themes[name] = {
                "base_theme": str(entry.get("base_theme", self.DEFAULT_THEME)),
                "widget_colors": dict(entry.get("widget_colors", {})),
                "updated_at": str(entry.get("updated_at", self._utc_timestamp())),
            }
        return {
            "version": self._CUSTOM_THEMES_VERSION,
            "themes": themes,
        }

    def _write_custom_themes(self) -> bool:
        payload = self._custom_theme_payload()
        path = Path(self.CUSTOM_THEMES_FILE)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, payload)
            return True
        except Exception:
            return False

    def _load_custom_themes(self) -> None:
        path = Path(self.CUSTOM_THEMES_FILE)
        loaded: Dict[str, Dict[str, Any]] = {}
        if not path.exists():
            self._custom_themes = loaded
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._custom_themes = loaded
            return
        if not isinstance(payload, dict):
            self._custom_themes = loaded
            return
        raw_themes = payload.get("themes", {})
        if not isinstance(raw_themes, dict):
            self._custom_themes = loaded
            return

        for raw_name, raw_entry in raw_themes.items():
            name = self._normalized_name(str(raw_name))
            record = self._sanitize_custom_theme_record(name, raw_entry)
            if record is None:
                continue
            existing = None
            for current_name in list(loaded.keys()):
                if current_name.casefold() == name.casefold():
                    existing = current_name
                    break
            if existing:
                loaded.pop(existing, None)
            loaded[name] = record
        self._custom_themes = loaded

    def is_custom_theme(self, name: str) -> bool:
        return self._match_custom_theme_name(name) is not None

    def save_custom_theme(
        self,
        name: str,
        widget_colors: Dict[str, str],
        base_theme: str = "Archive Blue",
    ) -> bool:
        candidate = self._normalized_name(name)
        if not candidate or self._is_builtin_or_alias_name(candidate):
            return False

        sanitized_colors = self._sanitize_widget_colors(widget_colors)
        if not sanitized_colors:
            return False

        canonical_name = self._match_custom_theme_name(candidate) or candidate
        self._custom_themes[canonical_name] = {
            "base_theme": self._coerce_base_theme_name(base_theme),
            "widget_colors": sanitized_colors,
            "updated_at": self._utc_timestamp(),
        }
        if self._write_custom_themes():
            self._theme_revision += 1
            self._invalidate_theme_caches()
            return True

        self._load_custom_themes()
        return False

    def delete_custom_theme(self, name: str) -> bool:
        matched = self._match_custom_theme_name(name)
        if not matched:
            return False
        previous = self._custom_themes.pop(matched, None)
        if previous is None:
            return False
        if self._write_custom_themes():
            self._theme_revision += 1
            self._invalidate_theme_caches()
            return True
        self._custom_themes[matched] = previous
        return False

    def _custom_entry(self, name: str) -> Optional[Dict[str, Any]]:
        matched = self._match_custom_theme_name(name)
        if not matched:
            return None
        entry = self._custom_themes.get(matched)
        if not isinstance(entry, dict):
            return None
        return entry

    def _build_custom_widget_qss(
        self,
        widget_colors: Dict[str, str],
        base_tokens: Dict[str, str],
    ) -> str:
        if not widget_colors:
            return ""

        blocks: List[str] = []
        accent = str(base_tokens.get("ACCENT_CYAN", "#06B6D4"))
        bg_dark = str(base_tokens.get("BG_DARK", "#1A1A2E"))

        for widget_type, bg_color in widget_colors.items():
            selector = str(widget_type)
            text_color = self._contrast_text_for_bg(bg_color)
            border_color = self._mix_hex(bg_color, accent, 0.35)
            hover_border = self._mix_hex(border_color, text_color, 0.2)
            hover_bg = self._mix_hex(bg_color, text_color, 0.1)
            pressed_bg = self._mix_hex(bg_color, text_color, 0.18)

            if selector == "QWidget":
                blocks.append(
                    f"""QWidget {{
    background-color: {bg_color};
}}"""
                )
                continue

            if selector == "QLabel":
                blocks.append(
                    f"""QLabel {{
    color: {bg_color};
}}"""
                )
                continue

            if selector == "QFrame":
                blocks.append(
                    f"""QFrame {{
    background-color: {bg_color};
    border: 1px solid {border_color};
}}
QFrame#card,
QFrame#settingsCard,
QFrame#customThemeCreatorCard,
QFrame[themeRole="searchSidebar"],
QFrame[themeRole="mainResults"] {{
    background-color: {bg_color};
    border: 1px solid {border_color};
}}"""
                )
                continue

            if selector == "QPushButton":
                blocks.append(
                    f"""QPushButton {{
    background-color: {bg_color};
    color: {text_color};
    border: 1px solid {border_color};
}}
QPushButton:hover:!disabled {{
    background-color: {hover_bg};
    border: 1px solid {hover_border};
}}
QPushButton:pressed {{
    background-color: {pressed_bg};
    border: 1px solid {hover_border};
}}
QPushButton:disabled {{
    border: 1px solid {border_color};
}}"""
                )
                continue

            if selector in {"QLineEdit", "QTextEdit", "QPlainTextEdit"}:
                blocks.append(
                    f"""{selector} {{
    background-color: {bg_color};
    color: {text_color};
    border: 1px solid {border_color};
}}
{selector}:focus,
{selector}:hover {{
    border: 1px solid {hover_border};
}}"""
                )
                continue

            if selector == "QComboBox":
                popup_bg = self._mix_hex(bg_color, bg_dark, 0.22)
                popup_text = self._contrast_text_for_bg(popup_bg)
                blocks.append(
                    f"""QComboBox {{
    background-color: {bg_color};
    color: {text_color};
    border: 1px solid {border_color};
}}
QComboBox:focus,
QComboBox:hover {{
    border: 1px solid {hover_border};
}}
QComboBox::drop-down {{
    border-left: 1px solid {border_color};
}}
QComboBox QAbstractItemView {{
    background-color: {popup_bg};
    color: {popup_text};
    border: 1px solid {border_color};
}}
QComboBox QAbstractItemView::item:selected {{
    border: 1px solid {hover_border};
}}"""
                )
                continue

            if selector == "QListWidget":
                blocks.append(
                    f"""QListWidget {{
    background-color: {bg_color};
    color: {text_color};
    border: 1px solid {border_color};
}}
QListWidget::item {{
    border: 1px solid {border_color};
}}
QListWidget::item:hover,
QListWidget::item:selected {{
    border: 1px solid {hover_border};
}}"""
                )
                continue

            if selector == "QCheckBox":
                checked_bg = self._mix_hex(bg_color, base_tokens["PRIMARY"], 0.48)
                checked_bg_hover = self._mix_hex(checked_bg, base_tokens["TEXT_WHITE"], 0.14)
                checked_border = self._mix_hex(hover_border, base_tokens["TEXT_WHITE"], 0.2)
                tick_icon = self._checkbox_tick_icon_uri(checked_bg)
                blocks.append(
                    f"""QCheckBox {{
    background-color: {bg_color};
    color: {text_color};
    border: 1px solid {border_color};
}}
QCheckBox::indicator {{
    background-color: {bg_color};
    border: 1px solid {border_color};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {hover_border};
}}
QCheckBox::indicator:checked {{
    image: url("{tick_icon}");
    border: 1px solid {checked_border};
    background-color: {checked_bg};
}}
QCheckBox::indicator:checked:hover,
QCheckBox::indicator:checked:pressed {{
    image: url("{tick_icon}");
    border: 1px solid {checked_border};
    background-color: {checked_bg_hover};
}}"""
                )
                continue

            blocks.append(
                f"""{selector} {{
    background-color: {bg_color};
    color: {text_color};
    border: 1px solid {border_color};
}}"""
            )

        return "\n".join(blocks)

    def apply_custom_preview(
        self,
        app: QApplication,
        widget_colors: Dict[str, str],
        base_theme: str = "Archive Blue",
    ) -> None:
        resolved_base = self._coerce_base_theme_name(base_theme)
        tokens = dict(self.THEMES[resolved_base])
        preview_colors = self._sanitize_widget_colors(widget_colors)
        base_styles = self.build_stylesheet(resolved_base)
        custom_qss = self._build_custom_widget_qss(preview_colors, tokens)
        if custom_qss:
            base_styles = f"{base_styles}\n{custom_qss}"
        app.setPalette(self._build_palette(tokens))
        app.setStyleSheet(self._compose_stylesheet(base_styles))

    def theme_names(self, *, include_hidden: bool = False) -> List[str]:
        return list(CLASSIC_THEME_NAMES) + ['Archive Blue', 'Coffee Shop', "Synthwave '84", 'Old Library', 'Matcha Latte', 'Carbon Fiber', 'Violet Afterburn', 'Cipher Red', 'Cipher Green', 'Cipher Purple', 'Aurora Borealis', 'Crimson Meridian'] + list(SOLID_COLOR_THEME_NAMES) + list(self._custom_themes)

    def has_theme(self, name: str) -> bool:
        key = str(name or "")
        if self._resolve_builtin_theme_name(key):
            return True
        return self.is_custom_theme(key)

    def _resolve_theme_name(self, name: str) -> str:
        builtin = self._resolve_builtin_theme_name(name)
        if builtin:
            return builtin
        custom = self._match_custom_theme_name(name)
        if custom:
            return custom
        return self.DEFAULT_THEME

    @classmethod
    def _parse_color(cls, color_text: str) -> QColor:
        text = str(color_text or "").strip()
        color = QColor(text)
        if color.isValid():
            return color
        match = cls._RGBA_COLOR_RE.fullmatch(text)
        if not match:
            return QColor("#000000")

        red = max(0, min(255, int(match.group(1))))
        green = max(0, min(255, int(match.group(2))))
        blue = max(0, min(255, int(match.group(3))))
        alpha_token = (match.group(4) or "").strip()
        alpha = 255
        if alpha_token:
            if alpha_token.endswith("%"):
                try:
                    alpha = int(round(255.0 * (float(alpha_token[:-1]) / 100.0)))
                except Exception:
                    alpha = 255
            else:
                try:
                    raw_alpha = float(alpha_token)
                except Exception:
                    raw_alpha = 1.0
                if raw_alpha <= 1.0:
                    alpha = int(round(255.0 * raw_alpha))
                else:
                    alpha = int(round(raw_alpha))
        alpha = max(0, min(255, alpha))
        return QColor(red, green, blue, alpha)

    @staticmethod
    def _mix_hex(start_hex: str, end_hex: str, ratio: float) -> str:
        start = ThemeManager._parse_color(start_hex)
        end = ThemeManager._parse_color(end_hex)
        t = max(0.0, min(1.0, float(ratio)))
        red = int(start.red() + (end.red() - start.red()) * t)
        green = int(start.green() + (end.green() - start.green()) * t)
        blue = int(start.blue() + (end.blue() - start.blue()) * t)
        return QColor(red, green, blue).name().upper()

    @classmethod
    def _opaque_color_qss(cls, color_text: str, fallback_text: str, *, min_alpha: int = 238) -> str:
        color = cls._parse_color(color_text)
        fallback = cls._parse_color(fallback_text)
        alpha = max(0, min(255, int(color.alpha())))
        if alpha < 255:
            blend = float(alpha) / 255.0
            red = int(round((color.red() * blend) + (fallback.red() * (1.0 - blend))))
            green = int(round((color.green() * blend) + (fallback.green() * (1.0 - blend))))
            blue = int(round((color.blue() * blend) + (fallback.blue() * (1.0 - blend))))
            color = QColor(red, green, blue)
        enforced_alpha = max(0, min(255, int(min_alpha)))
        if color.alpha() < enforced_alpha:
            color.setAlpha(enforced_alpha)
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

    @staticmethod
    def _contrast_text_for_bg(bg_hex: str) -> str:
        color = ThemeManager._parse_color(bg_hex)
        luminance = (
            (0.2126 * color.red())
            + (0.7152 * color.green())
            + (0.0722 * color.blue())
        ) / 255.0
        return "#FFFFFF" if luminance < 0.54 else "#111111"

    @staticmethod
    def _srgb_to_linear(channel: int) -> float:
        value = max(0.0, min(255.0, float(channel))) / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    @classmethod
    def _relative_luminance(cls, color_text: str) -> float:
        color = cls._parse_color(color_text)
        red = cls._srgb_to_linear(color.red())
        green = cls._srgb_to_linear(color.green())
        blue = cls._srgb_to_linear(color.blue())
        return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)

    @classmethod
    def _contrast_ratio(cls, fg_text: str, bg_text: str) -> float:
        fg = cls._relative_luminance(fg_text)
        bg = cls._relative_luminance(bg_text)
        lighter = max(fg, bg)
        darker = min(fg, bg)
        return (lighter + 0.05) / (darker + 0.05)

    @classmethod
    def _ensure_text_contrast(cls, text_color: str, bg_color: str, *, min_ratio: float = 4.5) -> str:
        base = cls._parse_color(text_color).name().upper()
        if cls._contrast_ratio(base, bg_color) >= min_ratio:
            return base

        best_color = base
        best_ratio = cls._contrast_ratio(base, bg_color)
        best_shift = 1.0
        for anchor in ("#FFFFFF", "#111111"):
            matched = False
            for step in range(1, 25):
                shift = step / 24.0
                candidate = cls._mix_hex(base, anchor, shift)
                ratio = cls._contrast_ratio(candidate, bg_color)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_color = candidate
                if ratio >= min_ratio:
                    if shift < best_shift:
                        best_shift = shift
                        best_color = candidate
                    matched = True
                    break
            if matched:
                continue

        if cls._contrast_ratio(best_color, bg_color) >= min_ratio:
            return best_color

        # Midtones can have insufficient contrast with both off-black and white.
        # Actual black/white extrema guarantee a readable fallback at the 4.5 target.
        fallback = max(("#000000", "#FFFFFF"), key=lambda color: cls._contrast_ratio(color, bg_color))
        if cls._contrast_ratio(fallback, bg_color) > cls._contrast_ratio(best_color, bg_color):
            return fallback
        return best_color


    @classmethod
    def _checkbox_tick_icon_uri(cls, bg_hex: str) -> str:
        tick_color = cls._contrast_text_for_bg(bg_hex)
        if tick_color == "#111111":
            return cls._CHECKBOX_TICK_DARK_PATH
        return cls._CHECKBOX_TICK_LIGHT_PATH

    @classmethod
    def _dashboard_match_system_accent_enabled(cls) -> bool:
        try:
            from Utils.gui_utils import ConfigManager

            return bool(ConfigManager.get_dashboard_match_system_accent())
        except Exception:
            return False

    @classmethod
    def _system_accent_hex(cls) -> Optional[str]:
        app = QApplication.instance()
        if app is None:
            return None
        palette = app.palette()
        roles: List[QPalette.ColorRole] = []
        accent_role = getattr(QPalette.ColorRole, "Accent", None)
        if accent_role is not None:
            roles.append(accent_role)
        roles.append(QPalette.ColorRole.Highlight)

        for role in roles:
            try:
                color = palette.color(role)
            except Exception:
                continue
            if not color.isValid():
                continue
            if color.alpha() <= 0:
                continue
            return str(color.name()).upper()
        return None

    @classmethod
    def _augment_runtime_tokens(cls, tokens: Dict[str, str]) -> Dict[str, str]:
        runtime = dict(tokens)
        if cls._dashboard_match_system_accent_enabled():
            accent_hex = cls._system_accent_hex()
            if accent_hex:
                runtime["PRIMARY"] = accent_hex
                runtime["PRIMARY_HOVER"] = cls._mix_hex(accent_hex, "#FFFFFF", 0.16)
                runtime["SECONDARY"] = cls._mix_hex(accent_hex, runtime.get("BG_LIGHT", "#0F172A"), 0.22)
                runtime["SECONDARY_HOVER"] = cls._mix_hex(runtime["SECONDARY"], "#FFFFFF", 0.14)
                runtime["ACCENT_CYAN"] = accent_hex
                runtime["ACCENT_LIGHT_BLUE"] = cls._mix_hex(accent_hex, "#FFFFFF", 0.1)

        disabled_bg = str(runtime.get("DISABLED_BG", "")).strip()
        disabled_bg_valid = bool(disabled_bg) and (
            QColor(disabled_bg).isValid() or cls._RGBA_COLOR_RE.fullmatch(disabled_bg) is not None
        )
        if not disabled_bg_valid:
            disabled_bg = cls._mix_hex(runtime["PRIMARY"], runtime["BG_CARD"], 0.72)
        runtime["DISABLED_BG"] = disabled_bg
        runtime["DISABLED_BORDER"] = cls._mix_hex(runtime["BG_MEDIUM"], runtime["BG_DARK"], 0.35)
        runtime["PRIMARY_TEXT"] = cls._contrast_text_for_bg(runtime["PRIMARY"])
        runtime["BUTTON_TEXT"] = cls._contrast_text_for_bg(runtime["PRIMARY"])
        runtime["BUTTON_TEXT_HOVER"] = cls._contrast_text_for_bg(runtime["PRIMARY_HOVER"])

        disabled_text = str(runtime.get("DISABLED_TEXT", "")).strip()
        disabled_text_valid = bool(disabled_text) and (
            QColor(disabled_text).isValid() or cls._RGBA_COLOR_RE.fullmatch(disabled_text) is not None
        )
        if not disabled_text_valid:
            disabled_text = cls._mix_hex(runtime["BUTTON_TEXT"], runtime["TEXT_GRAY"], 0.62)
        runtime["DISABLED_TEXT"] = disabled_text
        # Menu selected rows use a fixed amber chip (#F59E0B), so match text contrast to that surface.
        runtime["WARNING_TEXT"] = cls._contrast_text_for_bg("#F59E0B")
        runtime["WARNING_DISABLED_TEXT"] = cls._mix_hex(runtime["WARNING_TEXT"], runtime["TEXT_GRAY"], 0.55)
        runtime["BUTTON_HOVER_BORDER"] = cls._mix_hex(runtime["PRIMARY_HOVER"], runtime["ACCENT_CYAN"], 0.35)
        runtime["CHECKBOX_BG"] = cls._mix_hex(runtime["BG_LIGHT"], runtime["TEXT_WHITE"], 0.18)
        runtime["CHECKBOX_BG_HOVER"] = cls._mix_hex(runtime["CHECKBOX_BG"], tokens["TEXT_WHITE"], 0.14)
        runtime["CHECKBOX_BORDER"] = cls._mix_hex(runtime["ACCENT_CYAN"], runtime["TEXT_WHITE"], 0.24)
        runtime["CHECKBOX_BORDER_HOVER"] = cls._mix_hex(runtime["CHECKBOX_BORDER"], tokens["TEXT_WHITE"], 0.22)
        runtime["CHECKBOX_CHECKED_BG"] = cls._mix_hex(runtime["PRIMARY"], runtime["ACCENT_CYAN"], 0.2)
        runtime["CHECKBOX_CHECKED_BG_HOVER"] = cls._mix_hex(runtime["CHECKBOX_CHECKED_BG"], tokens["TEXT_WHITE"], 0.14)
        runtime["CHECKBOX_CHECKED_BORDER"] = cls._mix_hex(runtime["PRIMARY_HOVER"], runtime["TEXT_WHITE"], 0.2)
        runtime["CHECKBOX_TICK_ICON"] = cls._checkbox_tick_icon_uri(runtime["CHECKBOX_CHECKED_BG"])
        runtime["CONTROL_CENTER_BG"] = cls._mix_hex(runtime["BG_CARD"], runtime["BG_MEDIUM"], 0.24)
        runtime["CONTROL_CENTER_BORDER"] = cls._mix_hex(runtime["ACCENT_CYAN"], runtime["BG_DARK"], 0.55)
        runtime["CONTROL_CENTER_HEADER_TEXT"] = cls._ensure_text_contrast(
            cls._mix_hex(runtime["TEXT_GRAY"], runtime["TEXT_LIGHT"], 0.38),
            runtime["CONTROL_CENTER_BG"],
            min_ratio=3.2,
        )
        runtime["RESULT_CARD_BG"] = cls._mix_hex(runtime["BG_CARD"], runtime["BG_LIGHT"], 0.08)
        runtime["RESULT_CARD_BG_HOVER"] = cls._mix_hex(runtime["RESULT_CARD_BG"], runtime["TEXT_WHITE"], 0.06)
        runtime["RESULT_CARD_BORDER"] = cls._mix_hex(runtime["BG_LIGHT"], runtime["ACCENT_CYAN"], 0.42)
        runtime["HISTORY_CARD_BG"] = cls._mix_hex(runtime["BG_CARD"], runtime["BG_LIGHT"], 0.14)
        runtime["HISTORY_CARD_BORDER"] = cls._mix_hex(runtime["RESULT_CARD_BORDER"], runtime["TEXT_LIGHT"], 0.22)
        runtime["META_TEXT"] = cls._ensure_text_contrast(
            cls._mix_hex(runtime["TEXT_GRAY"], runtime["TEXT_LIGHT"], 0.36),
            runtime["RESULT_CARD_BG"],
            min_ratio=3.4,
        )
        runtime["PAPER_CODE_TEXT"] = cls._ensure_text_contrast(
            cls._mix_hex(runtime["TEXT_LIGHT"], runtime["ACCENT_CYAN"], 0.2),
            runtime["RESULT_CARD_BG"],
            min_ratio=4.0,
        )
        runtime["SKELETON_BASE"] = cls._mix_hex(runtime["BG_LIGHT"], runtime["BG_CARD"], 0.35)
        runtime["SKELETON_SHIMMER"] = cls._mix_hex(runtime["SKELETON_BASE"], runtime["TEXT_WHITE"], 0.16)
        runtime["PREVIEW_OVERLAY_BG"] = cls._mix_hex(runtime["BG_DARK"], runtime["BG_CARD"], 0.2)
        runtime["PREVIEW_OVERLAY_BORDER"] = cls._mix_hex(runtime["ACCENT_CYAN"], runtime["BG_DARK"], 0.45)
        runtime["THIN_SCROLLBAR_BG"] = cls._mix_hex(runtime["BG_MEDIUM"], runtime["BG_DARK"], 0.4)
        runtime["THIN_SCROLLBAR_HANDLE"] = cls._mix_hex(runtime["PRIMARY"], runtime["ACCENT_CYAN"], 0.35)
        runtime["INPUT_TINT_BG"] = cls._mix_hex(runtime["BG_LIGHT"], runtime["TEXT_WHITE"], 0.08)
        runtime["INPUT_TEXT"] = cls._ensure_text_contrast(runtime["TEXT_LIGHT"], runtime["INPUT_TINT_BG"], min_ratio=4.6)
        runtime["TOOL_BUTTON_TEXT"] = cls._ensure_text_contrast(
            runtime["TEXT_LIGHT"],
            runtime["INPUT_TINT_BG"],
            min_ratio=4.5,
        )
        runtime["TOOL_BUTTON_TEXT_HOVER"] = cls._ensure_text_contrast(
            runtime["TEXT_WHITE"],
            runtime["BG_LIGHT"],
            min_ratio=4.5,
        )
        runtime["LIST_ITEM_HOVER_TEXT"] = cls._ensure_text_contrast(
            runtime["TEXT_WHITE"],
            runtime["BG_LIGHT"],
            min_ratio=4.5,
        )
        runtime["INPUT_FOCUS_BORDER"] = cls._mix_hex(runtime["PRIMARY"], runtime["TEXT_WHITE"], 0.18)
        runtime["DISABLED_TEXT"] = cls._ensure_text_contrast(runtime["DISABLED_TEXT"], runtime["DISABLED_BG"], min_ratio=3.0)
        runtime["WARNING_DISABLED_TEXT"] = cls._ensure_text_contrast(
            runtime["WARNING_DISABLED_TEXT"],
            "#F59E0B",
            min_ratio=3.0,
        )
        runtime["MENU_BG"] = cls._opaque_color_qss(
            runtime.get("BG_CARD", "#121830"),
            runtime.get("BG_DARK", "#0E1220"),
            min_alpha=238,
        )
        runtime["MENU_DISABLED_BG"] = cls._opaque_color_qss(
            runtime.get("BG_LIGHT", "#1D2440"),
            runtime.get("BG_DARK", "#0E1220"),
            min_alpha=238,
        )
        runtime["MENU_BORDER"] = cls._mix_hex(runtime["BG_LIGHT"], runtime["ACCENT_CYAN"], 0.35)
        return runtime

    def get_theme_tokens(self, name: str) -> Dict[str, str]:
        resolved = self._resolve_theme_name(name)
        if resolved in self.THEMES:
            return dict(self.THEMES[resolved])
        if resolved in self.HIDDEN_THEMES:
            return dict(self.HIDDEN_THEMES[resolved])
        entry = self._custom_entry(resolved)
        if isinstance(entry, dict):
            base_theme = self._coerce_base_theme_name(str(entry.get("base_theme", self.DEFAULT_THEME)))
            return dict(self.THEMES[base_theme])
        return dict(self.THEMES[self.DEFAULT_THEME])


    def build_stylesheet(self, name: str) -> str:
        resolved = self._resolve_theme_name(name)
        if resolved in self.THEMES or resolved in self.HIDDEN_THEMES:
            tokens = self._augment_runtime_tokens(self.get_theme_tokens(resolved))
            extra = self.THEME_EXTRAS.get(resolved, "")
            if not extra:
                extra = self.HIDDEN_THEME_EXTRAS.get(resolved, "")
            return "\n".join([self._QSS_TEMPLATE.format(**tokens), extra, self._STABLE_LAYOUT_QSS])

        entry = self._custom_entry(resolved)
        if isinstance(entry, dict):
            base_theme = self._coerce_base_theme_name(str(entry.get("base_theme", self.DEFAULT_THEME)))
            base_stylesheet = self.build_stylesheet(base_theme)
            widget_colors = self._sanitize_widget_colors(entry.get("widget_colors", {}))
            overrides = self._build_custom_widget_qss(widget_colors, dict(self.THEMES[base_theme]))
            if overrides:
                return "\n".join([base_stylesheet, overrides, ""])
            return base_stylesheet

        tokens = self._augment_runtime_tokens(self.get_theme_tokens(self.DEFAULT_THEME))
        extra = self.THEME_EXTRAS.get(self.DEFAULT_THEME, "")
        return "\n".join([self._QSS_TEMPLATE.format(**tokens), extra, self._STABLE_LAYOUT_QSS])

    def _compose_stylesheet(self, base_stylesheet: str) -> str:
        return base_stylesheet

    def set_global_font_family(self, font_name: str) -> None:
        text = str(font_name or "").strip()
        if not text or text.casefold() == DEFAULT_FONT_OPTION.casefold():
            text = DEFAULT_FONT_OPTION
        if text == self._global_font_family:
            return
        self._global_font_family = text

    def global_font_family(self) -> str:
        return str(self._global_font_family or DEFAULT_FONT_OPTION)

    def _build_palette(self, tokens: Dict[str, str]) -> QPalette:
        button_text = self._contrast_text_for_bg(tokens["PRIMARY"])
        highlight_text = self._contrast_text_for_bg(tokens["PRIMARY"])
        input_text = self._contrast_text_for_bg(tokens["BG_LIGHT"])
        placeholder_text = self._mix_hex(input_text, tokens["BG_LIGHT"], 0.52)
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, self._parse_color(tokens["BG_DARK"]))
        palette.setColor(QPalette.ColorRole.WindowText, self._parse_color(tokens["TEXT_WHITE"]))
        palette.setColor(QPalette.ColorRole.Base, self._parse_color(tokens["BG_MEDIUM"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, self._parse_color(tokens["BG_LIGHT"]))
        palette.setColor(QPalette.ColorRole.Text, self._parse_color(tokens["TEXT_WHITE"]))
        palette.setColor(QPalette.ColorRole.PlaceholderText, self._parse_color(placeholder_text))
        palette.setColor(QPalette.ColorRole.Button, self._parse_color(tokens["PRIMARY"]))
        palette.setColor(QPalette.ColorRole.ButtonText, self._parse_color(button_text))
        palette.setColor(QPalette.ColorRole.Highlight, self._parse_color(tokens["PRIMARY"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, self._parse_color(highlight_text))
        return palette

    def apply_theme(self, app: QApplication, name: str) -> str:
        resolved = self._resolve_theme_name(name)
        current_font = str(self._global_font_family or DEFAULT_FONT_OPTION)
        if (
            resolved == self._current_theme
            and current_font == self._last_applied_font_family
            and self._last_applied_revision == self._theme_revision
        ):
            return resolved

        tokens = self.get_theme_tokens(resolved)
        # Publish tokens before Qt restyles widgets and emits palette events.
        from Utils.gui_utils import Colors
        Colors.apply_theme_tokens(tokens)
        self._current_theme = resolved
        app.setPalette(self._build_palette(tokens))
        cache_key = (resolved, 'colors')
        stylesheet = self._composed_stylesheet_cache.get(cache_key)
        if stylesheet is None:
            stylesheet = self._compose_stylesheet(self.build_stylesheet(resolved))
            self._composed_stylesheet_cache[cache_key] = stylesheet
        from UI.appearance_scope import AppearanceScope
        scope = getattr(app, '_pps_appearance_scope', None)
        if scope is None:
            scope = app._pps_appearance_scope = AppearanceScope(app)
        scope.apply(stylesheet)
        self._apply_native_font(app, current_font)

        self._last_applied_font_family = current_font
        self._last_applied_revision = self._theme_revision
        self.theme_changed.emit(resolved)
        if current_font != DEFAULT_FONT_OPTION:
            app._pps_font_controller.apply(current_font, refresh=True)
        return resolved

    def apply_font_override(self, app: QApplication, font_name: str) -> None:
        self.set_global_font_family(font_name)
        current_font = str(self._global_font_family or DEFAULT_FONT_OPTION)
        self._apply_native_font(app, current_font)
        self._last_applied_font_family = current_font
        self._last_applied_revision = self._theme_revision

    def _apply_native_font(self, app, choice):
        from UI.appearance_font import AppearanceFont
        controller = getattr(app, '_pps_font_controller', None)
        if controller is None:
            controller = app._pps_font_controller = AppearanceFont(app)
        controller.apply(choice)

    def current_theme(self) -> str:
        return self._current_theme


_THEME_MANAGER = ThemeManager()


def get_theme_manager() -> ThemeManager:
    return _THEME_MANAGER


class ModernDarkTheme:
    """Compatibility wrapper for previous single-theme interface."""

    PRIMARY = ThemeConfig.THEMES["Archive Blue"]["PRIMARY"]
    PRIMARY_HOVER = ThemeConfig.THEMES["Archive Blue"]["PRIMARY_HOVER"]
    SECONDARY = ThemeConfig.THEMES["Archive Blue"]["SECONDARY"]
    BG_DARK = ThemeConfig.THEMES["Archive Blue"]["BG_DARK"]
    BG_MEDIUM = ThemeConfig.THEMES["Archive Blue"]["BG_MEDIUM"]
    BG_LIGHT = ThemeConfig.THEMES["Archive Blue"]["BG_LIGHT"]
    BG_CARD = ThemeConfig.THEMES["Archive Blue"]["BG_CARD"]
    TEXT_WHITE = ThemeConfig.THEMES["Archive Blue"]["TEXT_WHITE"]
    TEXT_GRAY = ThemeConfig.THEMES["Archive Blue"]["TEXT_GRAY"]
    TEXT_LIGHT = ThemeConfig.THEMES["Archive Blue"]["TEXT_LIGHT"]
    SUCCESS = ThemeConfig.THEMES["Archive Blue"]["SUCCESS"]
    WARNING = ThemeConfig.THEMES["Archive Blue"]["WARNING"]
    ERROR = ThemeConfig.THEMES["Archive Blue"]["ERROR"]
    INFO = ThemeConfig.THEMES["Archive Blue"]["INFO"]
    ACCENT_PURPLE = ThemeConfig.THEMES["Archive Blue"]["ACCENT_PURPLE"]

    @staticmethod
    def apply_to_app(app) -> None:
        get_theme_manager().apply_theme(app, ThemeManager.DEFAULT_THEME)

    @staticmethod
    def get_stylesheet() -> str:
        return get_theme_manager().build_stylesheet(ThemeManager.DEFAULT_THEME)
