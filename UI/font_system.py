from __future__ import annotations

import platform
from typing import List

from PySide6.QtGui import QFontDatabase

DEFAULT_FONT_OPTION = "Default"

OS_BUCKET_MACOS = "macos"
OS_BUCKET_WINDOWS = "windows"
OS_BUCKET_OTHER = "other"

MACOS_ELITE_FONTS: List[str] = [
    "SF Pro",
    "Helvetica Neue",
    "Avenir Next",
    "Menlo",
    "Optima",
    "Palatino",
    "Monaco",
]

WINDOWS_ELITE_FONTS: List[str] = [
    "Segoe UI",
    "Verdana",
    "Consolas",
    "Tahoma",
    "Trebuchet MS",
    "Impact",
    "Lucida Console",
]

CROSS_PLATFORM_FONTS: List[str] = [
    "Arial",
    "Courier New",
    "Georgia",
    "Times New Roman",
]

BONUS_FONTS: List[str] = ["Inter", "Geist", "JetBrains Mono"]


def detect_os_bucket(system_name: str | None = None) -> str:
    system = str(system_name or platform.system() or "").strip().casefold()
    if system in {"darwin", "mac", "macos"}:
        return OS_BUCKET_MACOS
    if system in {"windows", "win32", "win64"}:
        return OS_BUCKET_WINDOWS
    return OS_BUCKET_OTHER


def installed_font_families() -> list[str]:
    try:
        families = list(QFontDatabase.families())
    except Exception:
        try:
            families = list(QFontDatabase.families())  # type: ignore[misc]
        except Exception:
            return []
    return [str(family).strip() for family in families if str(family).strip()]


def _normalize_token(text: str) -> str:
    return " ".join(str(text or "").strip().casefold().split())


def _match_installed_family(target: str, installed: list[str]) -> str | None:
    wanted = _normalize_token(target)
    if not wanted:
        return None

    for family in installed:
        if _normalize_token(family) == wanted:
            return family

    for family in installed:
        current = _normalize_token(family)
        if current.startswith(wanted) or wanted.startswith(current):
            return family

    for family in installed:
        current = _normalize_token(family)
        if wanted in current or current in wanted:
            return family
    return None


def discover_available_ui_fonts(system_name: str | None = None) -> list[str]:
    bucket = detect_os_bucket(system_name)
    if bucket == OS_BUCKET_MACOS:
        ordered_candidates = MACOS_ELITE_FONTS + BONUS_FONTS + CROSS_PLATFORM_FONTS
    elif bucket == OS_BUCKET_WINDOWS:
        ordered_candidates = WINDOWS_ELITE_FONTS + BONUS_FONTS + CROSS_PLATFORM_FONTS
    else:
        ordered_candidates = BONUS_FONTS + CROSS_PLATFORM_FONTS

    installed = installed_font_families()
    resolved: list[str] = []
    seen: set[str] = set()
    for candidate in ordered_candidates:
        matched = _match_installed_family(candidate, installed)
        if not matched:
            continue
        key = matched.casefold()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(matched)
    return resolved


def sanitize_font_choice(choice: str, available: list[str]) -> str:
    selected = str(choice or "").strip()
    if not selected:
        return DEFAULT_FONT_OPTION
    if selected.casefold() == DEFAULT_FONT_OPTION.casefold():
        return DEFAULT_FONT_OPTION

    names = [str(name).strip() for name in available if str(name).strip()]
    for name in names:
        if name.casefold() == selected.casefold():
            return name

    matched = _match_installed_family(selected, names)
    if matched:
        return matched
    return DEFAULT_FONT_OPTION


def build_global_font_qss(font_name: str) -> str:
    name = str(font_name or "").strip()
    if not name or name.casefold() == DEFAULT_FONT_OPTION.casefold():
        return ""
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    return f"* {{ font-family: '{escaped}'; }}"
