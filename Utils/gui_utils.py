"""
GUI Utilities Module
Shared utilities and error handling for the Past Paper Studio GUI (PySide6).
"""

import json
from Core.cache_tools import synchronized
import copy
import logging
import os
import shutil
import subprocess
import sys
import hashlib
import inspect
import difflib
import time
import re
import tempfile
import threading
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, List, Optional, Tuple

from Data.igcse_components_registry import (
    component_aliases_for_paper,
    get_rows_by_subject as get_igcse_rows_by_subject,
    get_subject_map as get_igcse_subject_map,
    normalize_paper_number,
)
from Data.alevel_profiles import get_alevel_definition_map
from Data.subject_catalog import IGCSE_SUBJECTS, ALEVEL_SUBJECTS, SUPPORTED_SUBJECTS

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtCore import Qt, QThread, QUrl, Signal, QTimer
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QDialog, QVBoxLayout, QProgressBar
import dotenv

from Core.runtime_paths import resource_path, user_data_path, cache_path, settings_env_path, migrate_legacy_data
from Core.atomic_storage import atomic_write_json, atomic_write_text
from Utils.dev_test_attempts import (
    build_dev_test_attempt,
    is_dev_test_attempt_entry,
    is_dev_test_attempt_key,
    prepend_dev_test_attempt,
)


# ============================================================================
# COLOR SCHEME - Clean and Modern
# ============================================================================

class Colors:
    """Modern color scheme for the GUI"""
    # Primary colors
    PRIMARY = "#3B8ED0"          # Blue
    PRIMARY_HOVER = "#3672B9"    # Darker blue
    SECONDARY = "#2CC985"        # Green
    SECONDARY_HOVER = "#25A876"  # Darker green

    # Background colors
    BG_DARK = "#1A1A2E"          # Dark background
    BG_MEDIUM = "#16213E"        # Medium background
    BG_LIGHT = "#0F3460"         # Lighter background
    BG_CARD = "#1F2937"          # Card background

    # Text colors
    TEXT_WHITE = "#FFFFFF"
    TEXT_GRAY = "#9CA3AF"
    TEXT_LIGHT = "#E5E7EB"

    # Status colors
    SUCCESS = "#10B981"          # Green
    WARNING = "#F59E0B"          # Orange
    ERROR = "#EF4444"            # Red
    INFO = "#3B82F6"             # Blue

    # Accent colors
    ACCENT_PURPLE = "#8B5CF6"
    ACCENT_PINK = "#EC4899"
    ACCENT_CYAN = "#06B6D4"
    ACCENT_LIGHT_BLUE = "#3B8ED0"

    _DEFAULT_THEME_TOKENS = MappingProxyType(
        {
            "PRIMARY": PRIMARY,
            "PRIMARY_HOVER": PRIMARY_HOVER,
            "SECONDARY": SECONDARY,
            "SECONDARY_HOVER": SECONDARY_HOVER,
            "BG_DARK": BG_DARK,
            "BG_MEDIUM": BG_MEDIUM,
            "BG_LIGHT": BG_LIGHT,
            "BG_CARD": BG_CARD,
            "TEXT_WHITE": TEXT_WHITE,
            "TEXT_GRAY": TEXT_GRAY,
            "TEXT_LIGHT": TEXT_LIGHT,
            "SUCCESS": SUCCESS,
            "WARNING": WARNING,
            "ERROR": ERROR,
            "INFO": INFO,
            "ACCENT_PURPLE": ACCENT_PURPLE,
            "ACCENT_PINK": ACCENT_PINK,
            "ACCENT_CYAN": ACCENT_CYAN,
            "ACCENT_LIGHT_BLUE": ACCENT_LIGHT_BLUE,
        }
    )

    @classmethod
    def default_theme_tokens(cls) -> dict[str, str]:
        return dict(cls._DEFAULT_THEME_TOKENS)

    @classmethod
    def apply_theme_tokens(cls, tokens: dict[str, str]) -> None:
        for key, value in (tokens or {}).items():
            if hasattr(cls, key):
                setattr(cls, key, str(value))

    @staticmethod
    def contrast_text_for_bg(bg_hex: str) -> str:
        color = QColor(str(bg_hex or "#000000"))
        luminance = (
            (0.2126 * color.red())
            + (0.7152 * color.green())
            + (0.0722 * color.blue())
        ) / 255.0
        return "#FFFFFF" if luminance < 0.54 else "#111111"


def setup_appearance(app: QApplication) -> None:
    """Apply the global PySide6 theme."""
    from UI.theme import get_theme_manager
    from UI.font_system import discover_available_ui_fonts, sanitize_font_choice
    import random
    from UI.localization import get_locale_manager
    get_locale_manager(app)

    manager = get_theme_manager()
    theme_name = ConfigManager.get_value("ui.theme", "Archive Blue")

    # Check if random theme is enabled
    if ConfigManager.get_random_theme_enabled():
        available_themes = manager.theme_names()
        if available_themes:
            random_theme = random.choice(available_themes)
            theme_name = random_theme
            ConfigManager.set_value("ui.theme", theme_name)

    available_fonts = discover_available_ui_fonts()
    stored_font = ConfigManager.get_ui_font_family()
    selected_font = sanitize_font_choice(stored_font, available_fonts)
    manager.set_global_font_family(selected_font)
    manager.apply_theme(app, str(theme_name or "Archive Blue"))
    if stored_font != selected_font:
        ConfigManager.set_ui_font_family(selected_font)


def _load_canonical_igcse_subjects() -> Dict[str, str]:
    """The shipped Alpha catalog remains authoritative over old scraped caches."""
    return dict(IGCSE_SUBJECTS)


# ============================================================================
# SUBJECT DATABASE - Replicated from CLI for GUI use
# ============================================================================

class SubjectDatabase:
    """Database of all supported subjects"""

    IGCSE_SUBJECTS = _load_canonical_igcse_subjects()


    ALEVEL_SUBJECTS = dict(ALEVEL_SUBJECTS)

    # BestExamHelp-backed searchable set used by the GUI search workflow.
    BESTEXAMHELP_IGCSE_CODES = set(IGCSE_SUBJECTS)
    BESTEXAMHELP_ALEVEL_CODES = set(ALEVEL_SUBJECTS)
    PAPA_FALLBACK_CODES = set()
    BESTEXAMHELP_SUPPORTED_CODES = BESTEXAMHELP_IGCSE_CODES | BESTEXAMHELP_ALEVEL_CODES

    # Short form mappings for fuzzy search
    SHORT_FORMS = {'bio': '0610', 'biology': '0610', 'bs': '0450', 'business': '0450', 'business studies': '0450', 'biz': '0450', 'chem': '0620', 'chemistry': '0620', 'cs': '0478', 'comp sci': '0478', 'computer science': '0478', 'compsci': '0478', 'ict': '0417', 'information and communication technology': '0417', 'econ': '0455', 'economics': '0455', 'eco': '0455', 'english': '0500', 'eng': '0500', 'history': '0470', 'hist': '0470', 'math': '0607', 'maths': '0607', 'mathematics': '0607', 'int math': '0607', 'igcse math': '0580', 'core math': '0580', 'intl math': '0607', 'international math': '0607', 'international maths': '0607', 'im': '0607', 'physics': '0625', 'phys': '0625', 'phy': '0625', 'a level bio': '9700', 'a level biology': '9700', 'a level business': '9609', 'a level chem': '9701', 'a level chemistry': '9701', 'a level cs': '9618', 'a level comp sci': '9618', 'a level econ': '9708', 'a level economics': '9708', 'a level maths': '9709', 'a level mathematics': '9709', 'further maths': '9231', 'fm': '9231', 'a level physics': '9702', 'a level psychology': '9990', 'psych': '9990', 'english literature': '9695', 'english language': '9093', 'psychology': '9990'}

    SUBJECT_SOURCE_MAP = {
        code: ["bestexamhelp", "pastpapersco", "gceguide", "dynamicpapers"]
        for code in BESTEXAMHELP_SUPPORTED_CODES
    }

    _SUBJECT_AVAILABILITY_CACHE_FILE = cache_path("source_subject_availability_cache.json")
    _subject_availability_cache_loaded = False
    _subject_availability_cache_dirty = False
    _subject_availability_cache: Dict[str, Dict[str, object]] = {}





    @classmethod
    def _normalize_level(cls, level: Optional[str]) -> str:
        text = str(level or "").strip()
        if text.lower() in {"a level", "as/a level", "as-a level", "alevel"}:
            return "A Level"
        return "IGCSE" if text.lower() == "igcse" else text

    @classmethod
    def _subject_pool(cls, level: Optional[str] = None) -> Dict[str, str]:
        level_text = cls._normalize_level(level)
        if level_text == "IGCSE":
            return dict(cls.IGCSE_SUBJECTS)
        if level_text == "A Level":
            return dict(cls.ALEVEL_SUBJECTS)
        return {**cls.IGCSE_SUBJECTS, **cls.ALEVEL_SUBJECTS} if not level_text else {}

    @classmethod
    @synchronized
    def _load_subject_availability_cache(cls) -> None:
        if cls._subject_availability_cache_loaded:
            return
        cls._subject_availability_cache_loaded = True
        cls._subject_availability_cache_dirty = False
        cls._subject_availability_cache = {}
        try:
            with open(cls._SUBJECT_AVAILABILITY_CACHE_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        entries = payload.get("entries", payload)
        if not isinstance(entries, dict):
            return
        for code, item in entries.items():
            code_text = str(code or "").strip()
            if not code_text:
                continue
            if not isinstance(item, dict):
                continue
            verified = bool(item.get("verified", False))
            sources = [str(source) for source in (item.get("sources", []) or []) if str(source).strip()]
            try:
                checked_at = float(item.get("checked_at", 0.0) or 0.0)
            except Exception:
                checked_at = 0.0
            cls._subject_availability_cache[code_text] = {
                "verified": verified,
                "sources": sorted(set(sources)),
                "checked_at": checked_at if checked_at > 0.0 else 0.0,
            }

    @classmethod
    @synchronized
    def _save_subject_availability_cache(cls) -> None:
        if not cls._subject_availability_cache_loaded or not cls._subject_availability_cache_dirty:
            return
        try:
            atomic_write_json(cls._SUBJECT_AVAILABILITY_CACHE_FILE,
                              {"saved_at": time.time(), "entries": cls._subject_availability_cache})
            cls._subject_availability_cache_dirty = False
        except OSError:
            logging.getLogger(__name__).warning("Could not save subject availability", exc_info=True)

    @classmethod
    @synchronized
    def get_subject_availability(cls, code: object) -> Dict[str, object]:
        subject_code = str(code or "").strip()
        if subject_code not in SUPPORTED_SUBJECTS:
            return {
                "verified": False,
                "sources": [],
                "checked_at": 0.0,
            }
        cls._load_subject_availability_cache()
        if subject_code and subject_code in cls._subject_availability_cache:
            item = cls._subject_availability_cache[subject_code]
            return {
                "verified": bool(item.get("verified", False)),
                "sources": list(item.get("sources", []) or []),
                "checked_at": float(item.get("checked_at", 0.0) or 0.0),
            }
        default_sources = list(cls.SUBJECT_SOURCE_MAP.get(subject_code, []) or [])
        return {
            "verified": bool(subject_code and default_sources),
            "sources": default_sources,
            "checked_at": 0.0,
        }

    @classmethod
    @synchronized
    def record_subject_availability(
        cls,
        code: object,
        *,
        sources: Optional[List[str]] = None,
        verified: bool = False,
        checked_at: Optional[float] = None,
    ) -> None:
        subject_code = str(code or "").strip()
        if not subject_code:
            return
        cls._load_subject_availability_cache()
        source_list = [str(source) for source in (sources or []) if str(source).strip()]
        stamp = float(checked_at if checked_at is not None else time.time())
        cls._subject_availability_cache[subject_code] = {
            "verified": bool(verified),
            "sources": sorted(set(source_list)),
            "checked_at": stamp if stamp > 0.0 else time.time(),
        }
        cls._subject_availability_cache_dirty = True
        cls._save_subject_availability_cache()

    @staticmethod
    def _normalize_query(text: str) -> str:
        value = str(text or "").strip().lower()
        value = re.sub(r"\s+", " ", value)
        return value

    @classmethod
    def get_all_subjects(cls, level: Optional[str] = None):
        return cls._subject_pool(level)

    @classmethod
    def get_searchable_subjects(cls, level: Optional[str] = None) -> Dict[str, str]:
        return cls._subject_pool(level)

    @classmethod
    def is_searchable_subject(cls, code: object) -> bool:
        subject_code = str(code or "").strip()
        if not subject_code:
            return False
        if subject_code not in SUPPORTED_SUBJECTS:
            return False
        all_subjects = cls._subject_pool(None)
        return subject_code in all_subjects

    @classmethod
    def requires_papa_fallback(cls, code: object) -> bool:
        subject_code = str(code or "").strip()
        return bool(subject_code and subject_code in cls.PAPA_FALLBACK_CODES)

    @classmethod
    def find_subject_code(cls, user_input, level: Optional[str] = None):
        user_input = cls._normalize_query(user_input)
        if not user_input:
            return None

        if user_input.isdigit() and len(user_input) == 4:
            if user_input not in SUPPORTED_SUBJECTS:
                return None
            if cls.is_searchable_subject(user_input):
                level_name = cls._normalize_level(level)
                if not level_name or cls.get_exam_level(user_input) == level_name:
                    return user_input

        level_name = cls._normalize_level(level)
        all_subjects = cls.get_all_subjects(level)

        if user_input in cls.SHORT_FORMS:
            code_match = cls.SHORT_FORMS[user_input]
            if code_match not in SUPPORTED_SUBJECTS:
                return None
            if cls.is_searchable_subject(code_match) and (not level_name or cls.get_exam_level(code_match) == level_name):
                return code_match

        if user_input.upper() in all_subjects:
            return user_input.upper()

        exact_name_matches: List[str] = []
        contains_name_matches: List[str] = []
        for code, name in all_subjects.items():
            code_text = str(code).strip()
            if not code_text:
                continue
            name_text = cls._normalize_query(name)
            if user_input == name_text:
                exact_name_matches.append(code_text)
            elif user_input in name_text:
                contains_name_matches.append(code_text)

        level_text = level_name
        if level_text == "IGCSE":
            static_codes = set(cls.IGCSE_SUBJECTS.keys())
        elif level_text == "A Level":
            static_codes = set(cls.ALEVEL_SUBJECTS.keys())
        else:
            static_codes = (
                set(cls.IGCSE_SUBJECTS.keys())
                | set(cls.ALEVEL_SUBJECTS.keys())
            )

        def _choose_preferred(codes: List[str]) -> Optional[str]:
            if not codes:
                return None
            unique_codes = sorted(set(codes))
            ranked = sorted(
                unique_codes,
                key=lambda code: (
                    -int(cls.is_searchable_subject(code)),
                    -int(code in static_codes),
                    code,
                ),
            )
            return ranked[0] if ranked else None

        direct_match = _choose_preferred(exact_name_matches)
        if direct_match:
            return direct_match
        contains_match = _choose_preferred(contains_name_matches)
        if contains_match:
            return contains_match

        scored: List[Tuple[float, int, int, str]] = []
        for code, name in all_subjects.items():
            code_text = str(code).strip().lower()
            name_text = cls._normalize_query(name)
            variants = [code_text, name_text, f"{name_text} {code_text}".strip()]
            score = max(difflib.SequenceMatcher(None, user_input, variant).ratio() for variant in variants)
            if user_input in name_text:
                score = max(score, 0.93)
            if user_input == code_text:
                score = 1.0
            code_id = str(code)
            scored.append(
                (
                    score,
                    1 if cls.is_searchable_subject(code_id) else 0,
                    1 if code_id in static_codes else 0,
                    code_id,
                )
            )

        # Prefer searchable + curated static codes over dynamic-only additions when scores tie.
        scored.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
        if scored and scored[0][0] >= 0.66:
            return scored[0][3]

        return None

    @classmethod
    def get_series_availability(cls, code: object) -> Dict[str, object]:
        """Return series enablement hints for the current subject selection."""
        subject_code = str(code or "").strip()
        default_tooltip = "Data Check: Series availability may vary by syllabus year/zone."
        out: Dict[str, object] = {
            "MJ": True,
            "ON": True,
            "FM": True,
            "tooltip": default_tooltip,
            "reason": "default",
        }
        if not subject_code:
            return out
        if subject_code not in SUPPORTED_SUBJECTS:
            return {
                "MJ": False,
                "ON": False,
                "FM": False,
                "tooltip": "This subject code has been removed from the searchable catalog.",
                "reason": "removed_subject",
            }

        # Explicitly allow FM for known India-zone subjects.
        if subject_code in {"0580", "0607"}:
            return {
                "MJ": True,
                "ON": True,
                "FM": True,
                "tooltip": "FM is available for this subject in specific zones (for example India zone).",
                "reason": "fm_zone_enabled",
            }

        subject_name = str(cls.get_subject_name(subject_code) or "").strip().lower()
        if "uk syllabus" in subject_name or "(uk)" in subject_name or subject_name.endswith(" uk"):
            return {
                "MJ": True,
                "ON": True,
                "FM": False,
                "tooltip": "FM disabled: this subject appears to use a UK-focused syllabus route.",
                "reason": "uk_syllabus",
            }

        return out

    @classmethod
    def get_subject_name(cls, code):
        all_subjects = cls.get_all_subjects()
        return all_subjects.get(code, code)

    @classmethod
    def get_exam_level(cls, code):
        code = str(code or "").strip()
        if code in cls.ALEVEL_SUBJECTS:
            return "A Level"
        return "IGCSE" if code in cls.IGCSE_SUBJECTS else ""

    @classmethod
    def get_bestexamhelp_track(cls, code: object) -> str:
        level = cls.get_exam_level(code)
        return {"A Level": "cambridge-international-a-level", "IGCSE": "cambridge-igcse"}.get(level, "")


# ============================================================================
# COMPONENTS DATABASE - For validation
# ============================================================================

class ComponentsDatabase:
    """Database of valid components per subject"""

    _ALEVEL_COMPONENTS = {
        "9700": [11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43, 51, 52, 53],
        "9701": [11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43, 51, 52, 53],
        "9702": [11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43, 51, 52, 53],
        "9709": [11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43, 51, 52, 53, 61, 62, 63],
        "9231": [11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43],
        "9990": [11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42, 43],
    }

    COMPONENTS: Dict[str, List[str]] = {}

    @staticmethod
    def _sort_component_key(value: str) -> Tuple[int, str]:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits.isdigit():
            return (int(digits), str(value))
        return (999, str(value))

    @classmethod
    def refresh_component_map(cls) -> None:
        igcse_components: Dict[str, List[str]] = {}
        try:
            rows_by_subject = get_igcse_rows_by_subject()
        except Exception:
            rows_by_subject = {}

        for code, rows in rows_by_subject.items():
            allowed: set[str] = set()
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                paper = normalize_paper_number(
                    row.get("paper_number"),
                    component_label=str(row.get("component_label", "")),
                )
                if not paper:
                    continue
                for alias in component_aliases_for_paper(paper, include_legacy_variants=True):
                    allowed.add(str(alias))
            if allowed:
                igcse_components[str(code)] = sorted(allowed, key=cls._sort_component_key)

        try:
            alevel_map = get_alevel_definition_map()
        except Exception:
            alevel_map = {}
        alevel_components: Dict[str, List[str]] = {}
        for code, papers in alevel_map.items():
            allowed: set[str] = set()
            for paper in (papers or {}).keys():
                paper_text = str(paper or "").strip()
                if not paper_text:
                    continue
                for alias in component_aliases_for_paper(paper_text, include_legacy_variants=True):
                    allowed.add(str(alias))
            if allowed:
                alevel_components[str(code)] = sorted(allowed, key=cls._sort_component_key)

        # Safety fallback for older code paths if curated A Level metadata is unavailable.
        if not alevel_components:
            alevel_components = {
                str(code): sorted({str(v) for v in values}, key=cls._sort_component_key)
                for code, values in cls._ALEVEL_COMPONENTS.items()
            }
        cls.COMPONENTS = {**igcse_components, **alevel_components}

    @classmethod
    def _component_candidates(cls, component: object) -> List[str]:
        raw = str(component or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())[:2]
        if not raw and not digits:
            return []

        out: List[str] = []
        seen: set[str] = set()

        def _add(value: object) -> None:
            text = str(value or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            out.append(text)

        _add(raw)
        _add(digits)

        paper = normalize_paper_number(digits)
        if paper:
            for alias in component_aliases_for_paper(paper, include_legacy_variants=True):
                _add(alias)

        return out

    @classmethod
    def validate_component(cls, subject_code, component):
        code = str(subject_code or "").strip()
        if code not in SUPPORTED_SUBJECTS:
            return False
        candidates = cls._component_candidates(component)
        if not candidates:
            return False

        allowed = set(cls.COMPONENTS.get(code, []))
        if allowed:
            return any(candidate in allowed for candidate in candidates)

        try:
            comp_int = int("".join(ch for ch in str(component or "") if ch.isdigit()))
        except Exception:
            return False
        return 1 <= comp_int <= 99

    @classmethod
    def validate_components(cls, subject_code, components):
        valid_comps = []
        invalid_comps = []

        for comp in components:
            value = str(comp).strip()
            if cls.validate_component(subject_code, value):
                valid_comps.append(value)
            else:
                invalid_comps.append(value)

        return valid_comps, invalid_comps


ComponentsDatabase.refresh_component_map()


# ============================================================================
# HISTORY MANAGEMENT
# ============================================================================

class HistoryManager:
    """Manage search history"""

    HISTORY_FILE = user_data_path("paper_search_history.json")

    @classmethod
    @synchronized
    def load_history(cls):
        migrate_legacy_data()
        try:
            with open(cls.HISTORY_FILE, encoding="utf-8") as handle:
                rows = json.load(handle)
        except (OSError, ValueError):
            return []
        if not isinstance(rows, list):
            return []
        required = ("subject_code", "series", "component", "year")
        return [{**row, **{key: str(row[key]) for key in required},
                 "subject_name": str(row.get("subject_name", row["subject_code"]))}
                for row in rows if isinstance(row, dict)
                and all(isinstance(row.get(key), (str, int)) and str(row[key]).strip() for key in required)][:10]

    @classmethod
    @synchronized
    def save_history(cls, history):
        try:
            atomic_write_json(cls.HISTORY_FILE, history)
            return True
        except (OSError, TypeError, ValueError):
            logging.getLogger(__name__).exception("Could not save search history")
            return False

    @classmethod
    @synchronized
    def add_to_history(cls, subject_code, subject_name, series, component, year):
        history = cls.load_history()

        for item in history:
            if (item['subject_code'] == subject_code and
                item['series'] == series and
                item['component'] == str(component) and
                item['year'] == str(year)):
                return

        entry = {
            'subject_code': subject_code,
            'subject_name': subject_name,
            'series': series,
            'component': str(component),
            'year': str(year),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        history.insert(0, entry)
        history = history[:10]

        cls.save_history(history)

    @classmethod
    def get_history(cls):
        return cls.load_history()

    @classmethod
    @synchronized
    def delete_history_entry(cls, entry: Dict[str, Any]) -> bool:
        target = dict(entry or {})
        subject_code = str(target.get("subject_code", "")).strip()
        series = str(target.get("series", "")).strip()
        component = str(target.get("component", "")).strip()
        year = str(target.get("year", "")).strip()
        timestamp = str(target.get("timestamp", "")).strip()
        if not (subject_code and series and component and year):
            return False

        history = cls.load_history()
        filtered: List[Dict[str, Any]] = []
        removed = False
        for item in history:
            if removed:
                filtered.append(item)
                continue
            if not isinstance(item, dict):
                filtered.append(item)
                continue
            same_signature = (
                str(item.get("subject_code", "")).strip() == subject_code
                and str(item.get("series", "")).strip() == series
                and str(item.get("component", "")).strip() == component
                and str(item.get("year", "")).strip() == year
            )
            if not same_signature:
                filtered.append(item)
                continue
            if timestamp and str(item.get("timestamp", "")).strip() != timestamp:
                filtered.append(item)
                continue
            removed = True
        if not removed:
            return False
        return bool(cls.save_history(filtered))


class ExamAttemptManager:
    """Persist unfinished exam attempts for resume/continue flow."""

    ATTEMPTS_FILE = user_data_path("unfinished_exam_attempts.json")
    ATTEMPTS_BACKUP_FILE = user_data_path("unfinished_exam_attempts.backup.json")
    ATTEMPT_ASSETS_ROOT = user_data_path("attempt_assets")
    _FILE_LOCK = threading.RLock()
    REQUIRED_KEYS = (
        "attempt_key",
        "paper_code",
        "subject_code",
        "subject_name",
        "paper_num",
        "year",
        "pdf_url",
        "remaining_seconds",
        "answers",
        "saved_at",
    )

    @classmethod
    def get_attempt_assets_dir(cls, attempt_key: str) -> str:
        key = str(attempt_key or "").strip()
        if not key:
            return cls.ATTEMPT_ASSETS_ROOT
        safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", key)
        return os.path.join(cls.ATTEMPT_ASSETS_ROOT, safe_key)

    @classmethod
    def clear_attempt_assets(cls, attempt_key: str) -> None:
        target = cls.get_attempt_assets_dir(attempt_key)
        if not target:
            return
        try:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass

    @classmethod
    def _load_attempts_from_path(cls, path: str) -> List[Dict[str, Any]]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            return []
        return []

    @classmethod
    def build_attempt_key(cls, subject_code: str, paper_num: str, year: str, pdf_url: str) -> str:
        raw = "|".join(
            [
                str(subject_code or "").strip(),
                str(paper_num or "").strip(),
                str(year or "").strip(),
                str(pdf_url or "").strip(),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @classmethod
    def load_attempts(cls) -> List[Dict[str, Any]]:
        with cls._FILE_LOCK:
            primary = cls._load_attempts_from_path(cls.ATTEMPTS_FILE)
            if primary:
                return primary
            backup = cls._load_attempts_from_path(cls.ATTEMPTS_BACKUP_FILE)
            if backup:
                cls.save_attempts(backup)
                return backup
            return []

    @classmethod
    def save_attempts(cls, attempts: List[Dict[str, Any]]) -> bool:
        attempts_dir = os.path.dirname(cls.ATTEMPTS_FILE)
        if attempts_dir:
            try:
                os.makedirs(attempts_dir, exist_ok=True)
            except Exception:
                return False

        payload = [dict(item) for item in (attempts or []) if isinstance(item, dict)]
        tmp_path = ""
        try:
            with cls._FILE_LOCK:
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    delete=False,
                    dir=(attempts_dir or "."),
                    prefix="unfinished_attempts_",
                    suffix=".tmp",
                )
                tmp_path = tmp.name
                try:
                    json.dump(payload, tmp, indent=2)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                finally:
                    tmp.close()

                if os.path.exists(cls.ATTEMPTS_FILE):
                    try:
                        shutil.copy2(cls.ATTEMPTS_FILE, cls.ATTEMPTS_BACKUP_FILE)
                    except Exception:
                        pass

                os.replace(tmp_path, cls.ATTEMPTS_FILE)

                try:
                    shutil.copy2(cls.ATTEMPTS_FILE, cls.ATTEMPTS_BACKUP_FILE)
                except Exception:
                    pass
                tmp_path = ""
                return True
        except Exception:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False

    @classmethod
    def _is_valid_entry(cls, item: Dict[str, Any]) -> bool:
        for key in cls.REQUIRED_KEYS:
            if key not in item:
                return False
        try:
            remaining = int(item.get("remaining_seconds", 0))
        except Exception:
            return False
        workspace = item.get("workspace") or {}
        practice = isinstance(workspace, dict) and workspace.get("mode") == "practice"
        if remaining <= 0 and not practice:
            return False
        if not str(item.get("attempt_key", "")).strip():
            return False
        if not str(item.get("subject_code", "")).strip():
            return False
        if not str(item.get("paper_num", "")).strip():
            return False
        if not str(item.get("year", "")).strip():
            return False
        if not str(item.get("pdf_url", "")).strip():
            return False
        if not isinstance(item.get("answers"), dict):
            return False
        return True

    @classmethod
    @synchronized
    def list_attempts(cls) -> List[Dict[str, Any]]:
        raw = cls.load_attempts()
        cleaned: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            if is_dev_test_attempt_entry(item):
                continue
            attempt_key = str(item.get("attempt_key", "")).strip()
            if not attempt_key or attempt_key in seen:
                continue
            if not cls._is_valid_entry(item):
                continue
            cleaned.append(dict(item))
            seen.add(attempt_key)

        cleaned.sort(key=lambda item: str(item.get("saved_at", "")), reverse=True)
        # Filtering the resume list must not erase older snapshots or their flags.
        # Non-resumable records can still be inspected through study history.
        return prepend_dev_test_attempt(cleaned)

    @classmethod
    def get_attempt(cls, attempt_key: str) -> Optional[Dict[str, Any]]:
        key = str(attempt_key or "").strip()
        if not key:
            return None
        if is_dev_test_attempt_key(key):
            return build_dev_test_attempt()
        for item in cls.list_attempts():
            if str(item.get("attempt_key", "")).strip() == key:
                return dict(item)
        return None

    @classmethod
    @synchronized
    def upsert_attempt(cls, entry: Dict[str, Any]) -> bool:
        if not isinstance(entry, dict):
            return False
        item = dict(entry)
        if is_dev_test_attempt_entry(item):
            return True
        if not cls._is_valid_entry(item):
            return False

        key = str(item.get("attempt_key", "")).strip()
        attempts = [
            row
            for row in cls.load_attempts()
            if (not is_dev_test_attempt_entry(row)) and str(row.get("attempt_key", "")).strip() != key
        ]
        attempts.insert(0, item)
        return cls.save_attempts(attempts)

    @classmethod
    @synchronized
    def delete_attempt(cls, attempt_key: str) -> bool:
        key = str(attempt_key or "").strip()
        if not key:
            return False
        if is_dev_test_attempt_key(key):
            return True
        attempts = [item for item in cls.load_attempts() if not is_dev_test_attempt_entry(item)]
        filtered = [item for item in attempts if str(item.get("attempt_key", "")).strip() != key]
        if len(filtered) == len(attempts):
            return False
        ok = cls.save_attempts(filtered)
        if ok:
            cls.clear_attempt_assets(key)
        return ok


# ============================================================================
# CONFIG MANAGEMENT
# ============================================================================

class ConfigManager:
    """Manage application configuration"""

    CONFIG_FILE = user_data_path("past_paper_finder_config.json")
    _CACHE = None
    _CACHE_SIGNATURE = None
    _CONFIG_LOCK = threading.RLock()

    @classmethod
    def _merge_with_defaults(cls, defaults, loaded):
        if isinstance(defaults, dict):
            loaded_map = loaded if isinstance(loaded, dict) else {}
            merged: Dict[str, Any] = {}
            for key, value in defaults.items():
                merged[key] = cls._merge_with_defaults(value, loaded_map.get(key))
            for key, value in loaded_map.items():
                if key not in merged:
                    merged[key] = value
            return merged
        return loaded if loaded is not None else defaults

    @classmethod
    def load_config(cls):
        migrate_legacy_data()
        with cls._CONFIG_LOCK:
            try:
                stat = os.stat(cls.CONFIG_FILE)
                signature = (str(cls.CONFIG_FILE), stat.st_mtime_ns, stat.st_size)
            except OSError:
                signature = (str(cls.CONFIG_FILE), None, None)
            if cls._CACHE is not None and signature == cls._CACHE_SIGNATURE:
                return copy.deepcopy(cls._CACHE)
            loaded = {}
            try:
                with open(cls.CONFIG_FILE, encoding="utf-8") as handle:
                    value = json.load(handle)
                if isinstance(value, dict):
                    loaded = value
            except (OSError, ValueError):
                pass
            ui = loaded.get("ui")
            if isinstance(ui, dict):
                ui.pop("lite_mode", None)
                ui.pop("ocr", None)
                ui.pop("animations_enabled", None)
                ui.pop("theme_animations", None)
            merged = cls._merge_with_defaults(cls.get_default_config(), loaded)
            level = SubjectDatabase._normalize_level(merged.get("default_level"))
            merged["default_level"] = level if level in {"IGCSE", "A Level"} else "IGCSE"
            from UI.theme import get_theme_manager
            merged["ui"]["theme"] = get_theme_manager()._resolve_theme_name(merged["ui"].get("theme", "Archive Blue"))
            cls._CACHE, cls._CACHE_SIGNATURE = copy.deepcopy(merged), signature
            return merged

    @classmethod
    def get_default_config(cls):
        return {
            'default_level': 'IGCSE',
            'default_series': 'MJ',
            'default_include_gt': True,
            'auto_open_browser': True,
            'auto_download': False,
            'search': {
                'fast_first_target_ms': 2500,
                'max_total_ms': 10000,
                'enable_background_enrichment': True,
                'stop_on_first_source_hit': True,
                'cancel_resets_results': True,
                'logging': {
                    'enabled': True,
                    'level': 'INFO',
                },
            },
                'ui': {
                    'theme': 'Archive Blue',
                    'font_family': 'Default',
                    'language': 'en_US',
                    'random_theme_enabled': False,
                    'show_startup_animation': True,
                    'full_screen_on_startup': True,
                    'custom_theme_creator_enabled': False,
                    'sound_enabled': True,
                    'exam': {
                        'answer_panel_position': 'bottom',
                    },
                    'dashboard': {
                        'sidebar_collapsed': False,
                        'results_view': 'list',
                        'match_system_accent': False,
                        'onboarding_completed': False,
                        'command_palette_recents': [],
                        'favorites': [],
                        'saved_presets': [],
                        'ui_density': 'comfortable',
                        'typography_scale': 'md',
                    },
                },
            }

    @classmethod
    def save_config(cls, config):
        with cls._CONFIG_LOCK:
            try:
                atomic_write_json(cls.CONFIG_FILE, config)
                stat = os.stat(cls.CONFIG_FILE)
                cls._CACHE = copy.deepcopy(config)
                cls._CACHE_SIGNATURE = (str(cls.CONFIG_FILE), stat.st_mtime_ns, stat.st_size)
                return True
            except (OSError, TypeError, ValueError):
                logging.getLogger(__name__).exception("Could not save application settings")
                return False

    @classmethod
    def get_value(cls, key, default=None):
        config = cls.load_config()
        keys = key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    @classmethod
    def set_value(cls, key, value):
        with cls._CONFIG_LOCK:
            config = cls.load_config()
            keys = key.split(".")
            current = config

            for k in keys[:-1]:
                if not isinstance(current.get(k), dict):
                    current[k] = {}
                current = current[k]

            current[keys[-1]] = value
            if not cls.save_config(config):
                raise OSError("Could not save settings. Check the application data folder permissions.")

    @classmethod
    def get_search_config(cls) -> Dict[str, Any]:
        search_cfg = cls.get_value("search", {})
        if not isinstance(search_cfg, dict):
            search_cfg = {}
        logging_cfg = search_cfg.get("logging", {})
        if not isinstance(logging_cfg, dict):
            logging_cfg = {}
        return {
            "fast_first_target_ms": int(search_cfg.get("fast_first_target_ms", 2500) or 2500),
            "max_total_ms": int(search_cfg.get("max_total_ms", 10000) or 10000),
            "enable_background_enrichment": bool(search_cfg.get("enable_background_enrichment", True)),
            "stop_on_first_source_hit": bool(search_cfg.get("stop_on_first_source_hit", True)),
            "cancel_resets_results": bool(search_cfg.get("cancel_resets_results", True)),
            "logging": {
                "enabled": bool(logging_cfg.get("enabled", True)),
                "level": str(logging_cfg.get("level", "INFO") or "INFO"),
            },
        }

    @classmethod
    def get_ui_font_family(cls) -> str:
        font_name = cls.get_value("ui.font_family", "Default")
        text = str(font_name or "").strip()
        return text or "Default"

    @classmethod
    def set_ui_font_family(cls, font_name: str) -> None:
        text = str(font_name or "").strip() or "Default"
        cls.set_value("ui.font_family", text)

    @classmethod
    def get_dashboard_sidebar_collapsed(cls) -> bool:
        return bool(cls.get_value("ui.dashboard.sidebar_collapsed", False))

    @classmethod
    def set_dashboard_sidebar_collapsed(cls, collapsed: bool) -> None:
        cls.set_value("ui.dashboard.sidebar_collapsed", bool(collapsed))

    @classmethod
    def get_dashboard_results_view(cls) -> str:
        mode = str(cls.get_value("ui.dashboard.results_view", "list") or "list").strip().lower()
        return mode if mode in {"list", "grid"} else "list"

    @classmethod
    def set_dashboard_results_view(cls, mode: str) -> None:
        normalized = str(mode or "").strip().lower()
        cls.set_value("ui.dashboard.results_view", normalized if normalized in {"list", "grid"} else "list")

    @classmethod
    def get_dashboard_match_system_accent(cls) -> bool:
        return bool(cls.get_value("ui.dashboard.match_system_accent", False))

    @classmethod
    def set_dashboard_match_system_accent(cls, enabled: bool) -> None:
        cls.set_value("ui.dashboard.match_system_accent", bool(enabled))

    @classmethod
    def get_dashboard_onboarding_completed(cls) -> bool:
        return bool(cls.get_value("ui.dashboard.onboarding_completed", False))

    @classmethod
    def set_dashboard_onboarding_completed(cls, completed: bool) -> None:
        cls.set_value("ui.dashboard.onboarding_completed", bool(completed))

    @classmethod
    def get_random_theme_enabled(cls) -> bool:
        return bool(cls.get_value("ui.random_theme_enabled", False))

    @classmethod
    def set_random_theme_enabled(cls, enabled: bool) -> None:
        cls.set_value("ui.random_theme_enabled", bool(enabled))

    @classmethod
    def get_command_palette_recents(cls) -> List[str]:
        value = cls.get_value("ui.dashboard.command_palette_recents", [])
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def push_command_palette_recent(cls, command_id: str, max_items: int = 12) -> None:
        item = str(command_id or "").strip()
        if not item:
            return
        recents = [entry for entry in cls.get_command_palette_recents() if entry != item]
        recents.insert(0, item)
        cls.set_value("ui.dashboard.command_palette_recents", recents[: max(1, int(max_items))])

    @classmethod
    def get_dashboard_favorites(cls) -> List[Dict[str, Any]]:
        value = cls.get_value("ui.dashboard.favorites", [])
        if not isinstance(value, list):
            return []
        favorites: List[Dict[str, Any]] = []
        for row in value:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "")).strip()
            payload = row.get("payload")
            if label and isinstance(payload, dict):
                favorites.append({"label": label, "payload": dict(payload)})
        return favorites

    @classmethod
    def set_dashboard_favorites(cls, favorites: List[Dict[str, Any]]) -> None:
        sanitized: List[Dict[str, Any]] = []
        for row in favorites or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "")).strip()
            payload = row.get("payload")
            if not label or not isinstance(payload, dict):
                continue
            sanitized.append({"label": label, "payload": dict(payload)})
        cls.set_value("ui.dashboard.favorites", sanitized[:40])

    @classmethod
    def get_dashboard_saved_presets(cls) -> List[Dict[str, Any]]:
        value = cls.get_value("ui.dashboard.saved_presets", [])
        if not isinstance(value, list):
            return []
        presets: List[Dict[str, Any]] = []
        for row in value:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            filters = row.get("filters")
            if name and isinstance(filters, dict):
                presets.append({"name": name, "filters": dict(filters)})
        return presets

    @classmethod
    def set_dashboard_saved_presets(cls, presets: List[Dict[str, Any]]) -> None:
        sanitized: List[Dict[str, Any]] = []
        for row in presets or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            filters = row.get("filters")
            if not name or not isinstance(filters, dict):
                continue
            sanitized.append({"name": name, "filters": dict(filters)})
        cls.set_value("ui.dashboard.saved_presets", sanitized[:60])

    @classmethod
    def get_dashboard_ui_density(cls) -> str:
        density = str(cls.get_value("ui.dashboard.ui_density", "comfortable") or "comfortable").strip().lower()
        return density if density in {"compact", "comfortable", "spacious"} else "comfortable"

    @classmethod
    def set_dashboard_ui_density(cls, density: str) -> None:
        normalized = str(density or "").strip().lower()
        cls.set_value("ui.dashboard.ui_density", normalized if normalized in {"compact", "comfortable", "spacious"} else "comfortable")

    @classmethod
    def get_dashboard_typography_scale(cls) -> str:
        scale = str(cls.get_value("ui.dashboard.typography_scale", "md") or "md").strip().lower()
        return scale if scale in {"sm", "md", "lg"} else "md"

    @classmethod
    def set_dashboard_typography_scale(cls, scale: str) -> None:
        normalized = str(scale or "").strip().lower()
        cls.set_value("ui.dashboard.typography_scale", normalized if normalized in {"sm", "md", "lg"} else "md")

    @classmethod
    def get_exam_answer_panel_position(cls) -> str:
        raw = str(cls.get_value("ui.exam.answer_panel_position", "bottom") or "bottom").strip().lower()
        return raw if raw in {"left", "right", "bottom"} else "bottom"

    @classmethod
    def set_exam_answer_panel_position(cls, position: str) -> None:
        normalized = str(position or "").strip().lower()
        cls.set_value(
            "ui.exam.answer_panel_position",
            normalized if normalized in {"left", "right", "bottom"} else "bottom",
        )

    @classmethod
    def _resolve_theme_name(cls, theme_name: str) -> str:
        from UI.theme import get_theme_manager

        manager = get_theme_manager()
        try:
            return str(manager._resolve_theme_name(theme_name))  # type: ignore[attr-defined]
        except Exception:
            candidate = str(theme_name or "")
            aliases = getattr(manager, "THEME_ALIASES", {})
            if isinstance(aliases, dict):
                candidate = str(aliases.get(candidate, candidate))
            return candidate or "Default"





    @classmethod
    def get_sound_enabled(cls) -> bool:
        return bool(cls.get_value("ui.sound_enabled", True))

    @classmethod
    def set_sound_enabled(cls, enabled: bool) -> None:
        cls.set_value("ui.sound_enabled", bool(enabled))

    @classmethod
    def is_lite_mode_enabled(cls) -> bool:
        # Legacy API retained for compatibility; Lite Mode has been removed.
        return False

    @classmethod
    def set_lite_mode_enabled(cls, enabled: bool) -> None:
        config = cls.load_config()
        ui_cfg = config.setdefault("ui", {})
        if not isinstance(ui_cfg, dict):
            ui_cfg = {}
            config["ui"] = ui_cfg
        _ = bool(enabled)
        ui_cfg.pop("lite_mode", None)
        cls.save_config(config)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_range(input_str, *, minimum=0, maximum=2099, max_items=100):
    """Parse a bounded set of integers, rejecting the complete query on any error."""
    if not str(input_str or "").strip():
        return []
    text = str(input_str).strip()
    if len(text) > 1024:
        return []
    text = text.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"}))
    text = re.sub(r"[–—−‑]", "-", text)
    text = re.sub(r"[;|/]", ",", text)
    values = []
    seen = set()
    for part in text.split(","):
        match = re.fullmatch(r"\s*(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*", part)
        if not match:
            return []
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if not (minimum <= start <= maximum and minimum <= end <= maximum):
            return []
        if abs(end - start) + 1 > max_items:
            return []
        for number in range(start, end + (1 if end >= start else -1), 1 if end >= start else -1):
            if number not in seen:
                values.append(str(number))
                seen.add(number)
                if len(values) > max_items:
                    return []
    return values


def series_to_code(series):
    mapping = {
        'MJ': 's',
        'ON': 'w',
        'FM': 'm',
        'SP': 'y',
    }
    return mapping.get(series.upper(), 's')


def get_subject_folder(code):
    """Map subject code to bestexamhelp.com folder name"""
    folders = {'0417': 'information-and-communication-technology-0417', '0580': 'mathematics-0580', '0607': 'international-mathematics-0607', '0620': 'chemistry-0620', '9700': 'biology-9700', '9609': 'business-9609', '9701': 'chemistry-9701', '9618': 'computer-science-9618', '9708': 'economics-9708', '9709': 'mathematics-9709', '9231': 'mathematics-further-9231', '9702': 'physics-9702', '9990': 'psychology-9990', '0500': 'english-first-language-0500', '9695': 'literature-in-english-9695', '9093': 'english-language-9093'}

    text_code = str(code or "").strip()
    if text_code in folders:
        return folders[text_code]

    subject_name = SubjectDatabase.get_subject_name(text_code)
    if subject_name and subject_name != text_code:
        slug = str(subject_name).lower()
        slug = re.sub(r"\bcambridge\b", " ", slug)
        slug = re.sub(r"\bigcse\b", " ", slug)
        slug = re.sub(r"\bo\s*level\b", " ", slug)
        slug = re.sub(r"\bas\/?a\s*level\b", " ", slug)
        slug = slug.replace("&", " and ")
        slug = re.sub(r"\([^)]*\)", " ", slug)
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        if slug:
            return f"{slug}-{text_code}"
    return text_code


# ============================================================================
# DIALOGS AND THREADS
# ============================================================================


def show_error(parent, title, message):
    QMessageBox.critical(parent, title, message)


def show_info(parent, title, message):
    QMessageBox.information(parent, title, message)


def reveal_file_in_folder(path: str) -> bool:
    """Reveal a file in its containing folder where supported."""
    target = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not target or not os.path.exists(target):
        return False

    if sys.platform == "darwin":
        try:
            proc = subprocess.run(["open", "-R", target], check=False, capture_output=True)
            if proc.returncode == 0:
                return True
        except Exception:
            pass

    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["explorer", f"/select,{os.path.normpath(target)}"],
                check=False,
                capture_output=True,
            )
            if proc.returncode == 0:
                return True
        except Exception:
            pass

    directory = target if os.path.isdir(target) else os.path.dirname(target)
    if not directory:
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(directory)))


def show_download_complete_dialog(parent, title: str, file_path: str, message_prefix: str = "Saved to:") -> None:
    """Show a completion dialog with OK and Show in Folder actions."""
    resolved_path = os.path.abspath(os.path.expanduser(str(file_path or "").strip()))
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Information)
    dialog.setWindowTitle(str(title))
    dialog.setText(f"{message_prefix} {resolved_path}")
    show_in_folder_btn = dialog.addButton("Show in Folder", QMessageBox.ButtonRole.ActionRole)
    dialog.addButton(QMessageBox.StandardButton.Ok)
    dialog.exec()

    if dialog.clickedButton() is show_in_folder_btn:
        if not reveal_file_in_folder(resolved_path):
            QMessageBox.warning(
                parent,
                "Show in Folder Failed",
                f"Could not open folder for:\n{resolved_path}",
            )


def show_warning(parent, title, message):
    QMessageBox.warning(parent, title, message)


def show_toast(parent, message: str, *, timeout_ms: int = 2200) -> None:
    text = str(message or "").strip()
    if not text:
        return
    box = QMessageBox(parent)
    box.setWindowTitle("Notice")
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.NoButton)
    box.setModal(False)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    box.show()
    QTimer.singleShot(max(300, int(timeout_ms)), box.close)


class LoadingDialog(QDialog):
    """A loading dialog with progress indicator"""
    cancelled = Signal()

    def __init__(self, parent, title="Searching...", message="Please wait..."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(320, 160)
        self._suppress_cancel_signal = False
        self._cancel_signal_emitted = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel("⏳")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 28px;")

        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate

        layout.addWidget(icon_label)
        layout.addWidget(self.message_label)
        layout.addWidget(self.progress)

    def update_message(self, message):
        self.message_label.setText(message)
        self.message_label.update()

    def suppress_cancel_signal(self) -> None:
        self._suppress_cancel_signal = True

    def _emit_cancelled_once(self) -> None:
        if self._suppress_cancel_signal or self._cancel_signal_emitted:
            return
        self._cancel_signal_emitted = True
        try:
            self.cancelled.emit()
        except Exception:
            pass

    def reject(self) -> None:
        self._emit_cancelled_once()
        super().reject()

    def closeEvent(self, event) -> None:
        self._emit_cancelled_once()
        super().closeEvent(event)


class SearchThread(QThread):
    """Thread for performing searches without blocking UI"""

    results_ready = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    progress_update = Signal(str, object)
    partial_results = Signal(object, bool)

    def __init__(self, search_function, parent=None):
        super().__init__(parent)
        self.search_function = search_function

    def request_cancel(self) -> None:
        self.requestInterruption()

    def _build_search_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        try:
            signature = inspect.signature(self.search_function)
        except Exception:
            return kwargs
        parameters = signature.parameters
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
        if "progress_callback" in parameters or accepts_kwargs:
            kwargs["progress_callback"] = self._emit_progress_update
        if "partial_callback" in parameters or accepts_kwargs:
            kwargs["partial_callback"] = self._emit_partial_results
        if "cancel_check" in parameters or accepts_kwargs:
            kwargs["cancel_check"] = self.isInterruptionRequested
        return kwargs

    def _emit_progress_update(self, message: str, metrics: Optional[Dict[str, object]] = None) -> None:
        if self.isInterruptionRequested():
            return
        payload = dict(metrics or {})
        self.progress_update.emit(str(message or ""), payload)

    def _emit_partial_results(self, groups: object, is_final: bool = False) -> None:
        if self.isInterruptionRequested():
            return
        self.partial_results.emit(groups, bool(is_final))

    def run(self):
        if self.isInterruptionRequested():
            self.cancelled.emit()
            return
        try:
            kwargs = self._build_search_kwargs()
            results = self.search_function(**kwargs)
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.results_ready.emit(results)
        except Exception as e:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.error.emit(str(e))


# ============================================================================
# AI SETTINGS HELPERS
# ============================================================================

def get_env_path() -> str:
    migrate_legacy_data()
    return settings_env_path()


_GROQ_API_KEY_ENV = "GROQ_API_KEY"
_GROQ_TEXT_MODEL_ENV = "GROQ_TEXT_MODEL"
_GROQ_VISION_MODEL_ENV = "GROQ_VISION_MODEL"
_GROQ_STARTUP_WARNING_SHOWN_SESSION = False


def _upsert_env_line(lines: list[str], key: str, value: str) -> list[str]:
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    return lines


def _normalize_env_value(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and (
        (text.startswith('"') and text.endswith('"'))
        or (text.startswith("'") and text.endswith("'"))
    ):
        text = text[1:-1].strip()
    return text


def _clear_legacy_ai_env_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            cleaned.append(line)
            continue
        key = stripped.split("=", 1)[0]
        if key == "AI_PROVIDER" or key.startswith("OLLAMA_"):
            continue
        cleaned.append(line)
    return cleaned


def load_groq_api_key(default: str = "") -> str:
    dotenv.load_dotenv(get_env_path(), override=True)
    return _normalize_env_value(os.environ.get(_GROQ_API_KEY_ENV, default) or default)


def load_groq_text_model(default: str = "meta-llama/llama-4-scout-17b-16e-instruct") -> str:
    dotenv.load_dotenv(get_env_path(), override=True)
    value = _normalize_env_value(os.environ.get(_GROQ_TEXT_MODEL_ENV, default) or default)
    return value or str(default or "").strip()


def load_groq_vision_model(default: str = "meta-llama/llama-4-scout-17b-16e-instruct") -> str:
    dotenv.load_dotenv(get_env_path(), override=True)
    value = _normalize_env_value(os.environ.get(_GROQ_VISION_MODEL_ENV, default) or default)
    return value or str(default or "").strip()


def save_groq_settings(
    api_key: Optional[str] = None,
    text_model: Optional[str] = None,
    vision_model: Optional[str] = None,
) -> bool:
    env_path = get_env_path()
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    lines = _clear_legacy_ai_env_lines(lines)

    resolved_key = _normalize_env_value(api_key or load_groq_api_key())
    resolved_text_model = _normalize_env_value(text_model or load_groq_text_model())
    resolved_vision_model = _normalize_env_value(vision_model or load_groq_vision_model())

    if not resolved_text_model:
        resolved_text_model = "meta-llama/llama-4-scout-17b-16e-instruct"
    if not resolved_vision_model:
        resolved_vision_model = "meta-llama/llama-4-scout-17b-16e-instruct"

    lines = _upsert_env_line(lines, _GROQ_API_KEY_ENV, resolved_key)
    lines = _upsert_env_line(lines, _GROQ_TEXT_MODEL_ENV, resolved_text_model)
    lines = _upsert_env_line(lines, _GROQ_VISION_MODEL_ENV, resolved_vision_model)

    atomic_write_text(env_path, "".join(lines), private=True)

    os.environ[_GROQ_API_KEY_ENV] = resolved_key
    os.environ[_GROQ_TEXT_MODEL_ENV] = resolved_text_model
    os.environ[_GROQ_VISION_MODEL_ENV] = resolved_vision_model
    for key in list(os.environ.keys()):
        if key == "AI_PROVIDER" or key.startswith("OLLAMA_"):
            os.environ.pop(key, None)
    return True


def load_ai_provider() -> str:
    """Backward-compatible shim for legacy callers."""
    return "groq"


def load_ai_api_key(provider: Optional[str] = None) -> Optional[str]:
    """Backward-compatible shim for callers expecting an API-key getter."""
    _ = provider
    value = load_groq_api_key()
    return value or None


def save_ai_api_key(provider: str, api_key: str, model: Optional[str] = None) -> bool:
    """Backward-compatible shim for callers saving AI keys/models."""
    _ = provider
    return save_groq_settings(api_key=api_key, text_model=model)


def load_openai_api_key() -> Optional[str]:
    """Backward-compatible alias now routed to Groq key storage."""
    value = load_groq_api_key()
    return value or None


def save_openai_api_key(api_key: str, model: Optional[str] = None) -> bool:
    """Backward-compatible alias now routed to Groq settings."""
    return save_groq_settings(api_key=api_key, text_model=model)


def is_groq_configured() -> bool:
    return bool(str(load_groq_api_key() or "").strip())


def groq_missing_consequence_text() -> str:
    return "AI-dependent grading/preflight will be unavailable; Manual Grading only."


def groq_missing_warning_message(*, detailed: bool = False) -> str:
    base = (
        "GROQ_API_KEY is not configured.\n\n"
        f"{groq_missing_consequence_text()}"
    )
    if not detailed:
        return base
    return (
        f"{base}\n\n"
        "Open Settings -> AI Configuration and add your Groq API key."
    )


def should_show_groq_startup_warning() -> bool:
    global _GROQ_STARTUP_WARNING_SHOWN_SESSION
    if _GROQ_STARTUP_WARNING_SHOWN_SESSION:
        return False
    if is_groq_configured():
        return False
    _GROQ_STARTUP_WARNING_SHOWN_SESSION = True
    return True
