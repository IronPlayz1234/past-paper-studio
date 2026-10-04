"""Developer-only resumable exam attempt helpers for fixed AI grading tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from Core.runtime_paths import resource_path
from Data.exam_data import get_exam_duration

DEV_TEST_ENV = "PAST_PAPER_FINDER_DEV_TEST_CHEM_0620_S22_42"
DEV_TEST_ATTEMPT_KEY = "dev-test::chem_0620_mj_2022_42"
DEV_TEST_ID = "chem_0620_mj_2022_42"
DEV_TEST_LOCAL_QP_PATH = "/Users/sandeeptripathy/Desktop/Chemistry 0620_s22_qp_42 2026-03-11/0620_s22_qp_42.pdf"
DEV_TEST_SEARCH_CACHE_FILE = resource_path("Data", "paper_search_cache.json")
DEV_TEST_ASSETS_ROOT = resource_path("Data", "dev_test_attempt_assets")
DEV_TEST_REMOTE_QP_URL = (
    "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0620_s22_qp_42.pdf"
)
DEV_TEST_REMOTE_MS_URL = (
    "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0620_s22_ms_42.pdf"
)
DEV_TEST_REMOTE_GT_URL = (
    "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/0620_s22_gt.pdf"
)
DEV_TEST_SAVED_AT = "2026-03-14T00:00:00"

_QUESTION_IDS: List[str] = [
    "1(a)", "1(b)", "1(c)", "1(d)", "1(e)", "1(f)", "1(g)", "1(h)",
    "2(a)(i)", "2(a)(ii)", "2(b)(i)", "2(b)(ii)", "2(c)(i)", "2(c)(ii)", "2(c)(iii)", "2(c)(iv)",
    "2(d)(i)", "2(d)(ii)", "2(d)(iii)", "2(d)(iv)",
    "3(a)(i)", "3(a)(ii)", "3(a)(iii)", "3(b)(i)", "3(b)(ii)", "3(c)(i)", "3(c)(ii)", "3(d)",
    "4(a)", "4(b)", "4(c)", "4(d)", "4(e)",
    "5(a)", "5(b)", "5(c)(i)", "5(c)(ii)", "5(c)(iii)", "5(d)(i)", "5(d)(ii)", "5(e)(i)", "5(e)(ii)", "5(e)(iii)",
    "6(a)(i)", "6(a)(ii)", "6(a)(iii)", "6(b)", "6(c)(i)", "6(c)(ii)",
]

_QUESTION_MARKS: Dict[str, float] = {
    "1(a)": 1.0,
    "1(b)": 1.0,
    "1(c)": 1.0,
    "1(d)": 1.0,
    "1(e)": 1.0,
    "1(f)": 1.0,
    "1(g)": 1.0,
    "1(h)": 1.0,
    "2(a)(i)": 2.0,
    "2(a)(ii)": 1.0,
    "2(b)(i)": 1.0,
    "2(b)(ii)": 1.0,
    "2(c)(i)": 1.0,
    "2(c)(ii)": 2.0,
    "2(c)(iii)": 2.0,
    "2(c)(iv)": 3.0,
    "2(d)(i)": 1.0,
    "2(d)(ii)": 1.0,
    "2(d)(iii)": 1.0,
    "2(d)(iv)": 5.0,
    "3(a)(i)": 2.0,
    "3(a)(ii)": 1.0,
    "3(a)(iii)": 3.0,
    "3(b)(i)": 2.0,
    "3(b)(ii)": 2.0,
    "3(c)(i)": 1.0,
    "3(c)(ii)": 1.0,
    "3(d)": 2.0,
    "4(a)": 1.0,
    "4(b)": 3.0,
    "4(c)": 3.0,
    "4(d)": 3.0,
    "4(e)": 3.0,
    "5(a)": 1.0,
    "5(b)": 3.0,
    "5(c)(i)": 1.0,
    "5(c)(ii)": 1.0,
    "5(c)(iii)": 2.0,
    "5(d)(i)": 3.0,
    "5(d)(ii)": 1.0,
    "5(e)(i)": 1.0,
    "5(e)(ii)": 1.0,
    "5(e)(iii)": 1.0,
    "6(a)(i)": 1.0,
    "6(a)(ii)": 2.0,
    "6(a)(iii)": 1.0,
    "6(b)": 1.0,
    "6(c)(i)": 3.0,
    "6(c)(ii)": 1.0,
}

_TEXT_ANSWERS: Dict[str, str] = {
    "1(a)": "Mg",
    "1(b)": "Ar",
    "1(c)": "Cl",
    "1(d)": "Si",
    "1(e)": "P",
    "1(f)": "Na",
    "1(g)": "Al",
    "1(h)": "Cl",
    "2(a)(i)": "Ca + 2H2O -> Ca(OH)2 + H2",
    "2(a)(ii)": "calcium oxide",
    "2(b)(i)": "pH 13",
    "2(b)(ii)": "OH-",
    "2(c)(i)": "carbon dioxide",
    "2(c)(ii)": "a solution that cannot dissolve any more solute at that temperature",
    "2(c)(iii)": "add excess calcium hydroxide to water and filter",
    "2(c)(iv)": "test: sodium hydroxide\nobservations: white precipitate forms",
    "2(d)(i)": "burette",
    "2(d)(ii)": "neutralisation",
    "2(d)(iii)": "indicator",
    "2(d)(iv)": (
        "moles of HCl = 0.0500 x 20.0 / 1000 = 0.00100 mol\n"
        "moles of Ca(OH)2 = 0.00100 / 2 = 0.000500 mol\n"
        "concentration of Ca(OH)2 = 0.000500 x 1000 / 25.0 = 0.0200 mol/dm3\n"
        "Mr of Ca(OH)2 = 74\n"
        "concentration in g/dm3 = 74 x 0.0200 = 1.50 g/dm3"
    ),
    "3(a)(i)": "atoms of the same element with different numbers of neutrons",
    "3(a)(ii)": "55",
    "3(b)(i)": "hydrated copper(II) sulfate: blue\nhydrated cobalt(II) chloride: pink",
    "3(b)(ii)": "act as catalysts; variable oxidation states",
    "3(c)(i)": "because they have mobile electrons",
    "3(c)(ii)": "malleable",
    "3(d)": "higher density; better conductivity",
    "4(a)": "pale yellow gas",
    "4(b)": "molecular formula = S2F10",
    "4(e)": "LiCl has strong ionic bonds, but NCl3 has weak intermolecular forces between molecules",
    "5(a)": "fermentation",
    "5(b)": "name: complete combustion\nequation: C2H5OH + 3O2 -> 2CO2 + 3H2O",
    "5(c)(i)": "ethene",
    "5(c)(ii)": "addition",
    "5(c)(iii)": "steam, catalyst and 200C",
    "5(d)(i)": "hydrogen, catalyst, high temperature",
    "5(d)(ii)": "CnH2n+2",
    "5(e)(i)": "potassium manganate(VII)",
    "5(e)(ii)": "carboxylic acids",
    "6(a)(i)": "3",
    "6(a)(ii)": (
        "one monomer is a dioic acid with two carboxylic acid groups\n"
        "the other monomer is a diol with two hydroxyl groups"
    ),
    "6(a)(iii)": "polyester",
    "6(b)": "one",
    "6(c)(ii)": "cracking",
}

_TABLE_ANSWERS: Dict[str, Dict[str, Any]] = {
    "3(a)(iii)": {
        "type": "table",
        "cells": {
            "1,0": "24",
            "1,1": "28",
            "1,2": "24",
        },
        "value": "Table response:\nR2C1=24; R2C2=28; R2C3=24",
    }
}

_DRAWING_NOTES: Dict[str, str] = {
    "4(c)": "",
    "4(d)": "",
    "5(e)(iii)": "",
    "6(c)(i)": "name: but-2-ene",
}


def is_dev_test_attempt_enabled() -> bool:
    if bool(getattr(sys, "frozen", False)):
        return False
    raw = str(os.environ.get(DEV_TEST_ENV, "") or "").strip().lower()
    if raw in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    if raw in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    return True


def is_dev_test_attempt_key(attempt_key: Any) -> bool:
    return str(attempt_key or "").strip() == DEV_TEST_ATTEMPT_KEY


def is_dev_test_attempt_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if is_dev_test_attempt_key(entry.get("attempt_key")):
        return True
    if bool(entry.get("dev_test_entry")) and str(entry.get("dev_test_id", "")).strip() == DEV_TEST_ID:
        return True
    return False


def prepend_dev_test_attempt(attempts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered = [dict(item) for item in (attempts or []) if isinstance(item, dict) and not is_dev_test_attempt_entry(item)]
    if not is_dev_test_attempt_enabled():
        return filtered
    attempt = build_dev_test_attempt()
    if not attempt:
        return filtered
    return [attempt, *filtered]


def build_dev_test_attempt() -> Optional[Dict[str, Any]]:
    if not is_dev_test_attempt_enabled():
        return None

    pdf_url, local_pdf_path = _resolve_question_paper_locator()
    paper_resources = _build_dev_test_paper_resources(pdf_url=pdf_url, local_pdf_path=local_pdf_path)
    drawing_paths = _ensure_dev_test_drawing_assets()
    answers = _build_seed_answers(drawing_paths)

    try:
        duration_minutes = int(get_exam_duration("0620", "4", "2022"))
    except Exception:
        duration_minutes = 75

    remaining_seconds = max(30, duration_minutes * 60)

    return {
        "attempt_key": DEV_TEST_ATTEMPT_KEY,
        "dev_test_entry": True,
        "dev_test_id": DEV_TEST_ID,
        "paper_code": "0620_s22_qp_42",
        "subject_code": "0620",
        "subject_name": "Chemistry (DEV TEST)",
        "paper_num": "4",
        "year": "2022",
        "series": "MJ",
        "pdf_url": pdf_url,
        "local_pdf_path": local_pdf_path,
        "paper_resources": paper_resources,
        "remaining_seconds": remaining_seconds,
        "answers": answers,
        "question_ids": list(_QUESTION_IDS),
        "question_marks": dict(_QUESTION_MARKS),
        "total_marks": float(sum(_QUESTION_MARKS.values())),
        "optional_selection": {},
        "notes_text": "",
        "first_saved_at": DEV_TEST_SAVED_AT,
        "saved_at": DEV_TEST_SAVED_AT,
        "is_listening": False,
        "listening_audio_position_ms": 0,
        "listening_audio_timestamp": "",
        "listening_audio_source": "",
    }


def _resolve_question_paper_locator() -> tuple[str, str]:
    local_candidate = Path(str(DEV_TEST_LOCAL_QP_PATH or "")).expanduser()
    if local_candidate.exists():
        resolved = str(local_candidate.resolve())
        return resolved, resolved

    cached = _read_cached_question_paper_url()
    if cached:
        return cached, ""
    return DEV_TEST_REMOTE_QP_URL, ""


def _read_cached_question_paper_url() -> str:
    group = _read_cached_group()
    if not isinstance(group, dict):
        return ""
    primary_docs = group.get("primary_docs", {})
    if not isinstance(primary_docs, dict):
        return ""
    qp = primary_docs.get("QP", {})
    if not isinstance(qp, dict):
        return ""
    for key in ("direct_url", "download_url", "url", "open_url"):
        value = str(qp.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _read_cached_group() -> Optional[Dict[str, Any]]:
    cache_path = Path(str(DEV_TEST_SEARCH_CACHE_FILE or ""))
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return None

    for entry in entries.values():
        groups = entry.get("groups", []) if isinstance(entry, dict) else []
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            if (
                str(group.get("subject_code", "")).strip() == "0620"
                and str(group.get("session", "")).strip().upper() == "MJ"
                and str(group.get("year", "")).strip() == "2022"
                and str(group.get("component", "")).strip() == "42"
            ):
                return dict(group)
    return None


def _build_dev_test_paper_resources(*, pdf_url: str, local_pdf_path: str) -> Dict[str, Dict[str, str]]:
    cached_group = _read_cached_group()
    primary_docs = cached_group.get("primary_docs", {}) if isinstance(cached_group, dict) else {}

    def _resource_payload(raw: Any, *, fallback_kind: str, fallback_filename: str, fallback_url: str) -> Dict[str, str]:
        payload = dict(raw) if isinstance(raw, dict) else {}
        resolved_url = ""
        for key in ("direct_url", "download_url", "url", "open_url"):
            candidate = str(payload.get(key, "") or "").strip()
            if candidate:
                resolved_url = candidate
                break
        if not resolved_url:
            resolved_url = str(fallback_url or "").strip()
        return {
            "kind": str(payload.get("kind", "") or fallback_kind),
            "filename": str(payload.get("filename", "") or fallback_filename),
            "url": resolved_url,
            "direct_url": str(payload.get("direct_url", "") or resolved_url),
            "open_url": str(payload.get("open_url", "") or resolved_url),
            "download_url": str(payload.get("download_url", "") or resolved_url),
            "extension": str(payload.get("extension", "") or "pdf"),
            "resource_family": str(payload.get("resource_family", "") or ""),
        }

    question_url = str(local_pdf_path or pdf_url or "").strip()
    question_payload = _resource_payload(
        primary_docs.get("QP", {}),
        fallback_kind="QP",
        fallback_filename="0620_s22_qp_42",
        fallback_url=question_url,
    )
    if question_url:
        question_payload["url"] = question_url
        question_payload["direct_url"] = question_url
        question_payload["open_url"] = question_url
        question_payload["download_url"] = question_url

    return {
        "question": question_payload,
        "mark_scheme": _resource_payload(
            primary_docs.get("MS", {}),
            fallback_kind="MS",
            fallback_filename="0620_s22_ms_42",
            fallback_url=DEV_TEST_REMOTE_MS_URL,
        ),
        "grade_threshold": _resource_payload(
            primary_docs.get("GT", {}),
            fallback_kind="GT",
            fallback_filename="0620_s22_gt",
            fallback_url=DEV_TEST_REMOTE_GT_URL,
        ),
    }


def _build_seed_answers(drawing_paths: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    answers: Dict[str, Dict[str, Any]] = {}
    for qid, text in _TEXT_ANSWERS.items():
        answers[qid] = {
            "type": "text",
            "value": str(text),
        }
    for qid, payload in _TABLE_ANSWERS.items():
        answers[qid] = dict(payload)
    for qid, path in drawing_paths.items():
        answers[qid] = {
            "type": "drawing",
            "image_path": str(path or ""),
            "notes": str(_DRAWING_NOTES.get(qid, "") or ""),
        }
    return answers


def _ensure_dev_test_drawing_assets() -> Dict[str, str]:
    asset_dir = Path(str(DEV_TEST_ASSETS_ROOT or "")).expanduser() / DEV_TEST_ID
    asset_dir.mkdir(parents=True, exist_ok=True)

    out = {
        "4(c)": str((asset_dir / "4c_ncl3_dot_cross.png").resolve()),
        "4(d)": str((asset_dir / "4d_licl_dot_cross.png").resolve()),
        "5(e)(iii)": str((asset_dir / "5eiii_ch3cooh_displayed.png").resolve()),
        "6(c)(i)": str((asset_dir / "6ci_but2ene_displayed.png").resolve()),
    }

    if not Path(out["4(c)"]).exists():
        _draw_ncl3_dot_cross(Path(out["4(c)"]))
    if not Path(out["4(d)"]).exists():
        _draw_licl_dot_cross(Path(out["4(d)"]))
    if not Path(out["5(e)(iii)"]).exists():
        _draw_ch3cooh_displayed(Path(out["5(e)(iii)"]))
    if not Path(out["6(c)(i)"]).exists():
        _draw_but2ene_displayed(Path(out["6(c)(i)"]))
    return out


def _new_canvas(width: int = 1400, height: int = 1000) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), "white")
    return image, ImageDraw.Draw(image)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int = 34, *, bold: bool = False) -> None:
    draw.text(xy, text, fill="black", font=_font(size, bold=bold))


def _draw_dot(draw: ImageDraw.ImageDraw, x: int, y: int, radius: int = 7) -> None:
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="black", outline="black")


def _draw_cross(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 12, width: int = 3) -> None:
    draw.line((x - size, y - size, x + size, y + size), fill="black", width=width)
    draw.line((x - size, y + size, x + size, y - size), fill="black", width=width)


def _electron_pair(draw: ImageDraw.ImageDraw, x: int, y: int, kind: str, *, vertical: bool = False) -> None:
    if kind == "dotdot":
        if vertical:
            _draw_dot(draw, x, y - 14)
            _draw_dot(draw, x, y + 14)
        else:
            _draw_dot(draw, x - 14, y)
            _draw_dot(draw, x + 14, y)
        return
    if kind == "xx":
        if vertical:
            _draw_cross(draw, x, y - 14)
            _draw_cross(draw, x, y + 14)
        else:
            _draw_cross(draw, x - 14, y)
            _draw_cross(draw, x + 14, y)
        return
    if kind == "dotx":
        if vertical:
            _draw_dot(draw, x, y - 14)
            _draw_cross(draw, x, y + 14)
        else:
            _draw_dot(draw, x - 14, y)
            _draw_cross(draw, x + 14, y)


def _draw_ncl3_dot_cross(path: Path) -> None:
    image, draw = _new_canvas()
    _draw_text(draw, (80, 60), "Q4(c) DEV TEST - NCl3 dot-and-cross", 38, bold=True)

    positions = {
        "N": (700, 420),
        "Cl_left": (360, 650),
        "Cl_right": (1040, 650),
        "Cl_top": (700, 170),
    }
    n_x, n_y = positions["N"]
    for key in ("Cl_left", "Cl_right", "Cl_top"):
        cl_x, cl_y = positions[key]
        draw.line((n_x, n_y, cl_x, cl_y), fill="black", width=5)

    _draw_text(draw, (680, 395), "N", 54, bold=True)
    _draw_text(draw, (320, 625), "Cl", 52, bold=True)
    _draw_text(draw, (1000, 625), "Cl", 52, bold=True)
    _draw_text(draw, (665, 145), "Cl", 52, bold=True)

    _electron_pair(draw, 690, 315, "dotdot")
    _electron_pair(draw, 520, 540, "dotx")
    _electron_pair(draw, 880, 540, "dotx")
    _electron_pair(draw, 700, 300, "dotx", vertical=True)

    for x, y in [(300, 610), (300, 680), (410, 735)]:
        _electron_pair(draw, x, y, "xx")
    for x, y in [(1090, 610), (1090, 680), (980, 735)]:
        _electron_pair(draw, x, y, "xx")
    for x, y in [(610, 110), (790, 110), (700, 85)]:
        _electron_pair(draw, x, y, "xx")

    _save_image(image, path)


def _draw_licl_dot_cross(path: Path) -> None:
    image, draw = _new_canvas()
    _draw_text(draw, (80, 60), "Q4(d) DEV TEST - LiCl ionic dot-and-cross", 38, bold=True)

    draw.rectangle((210, 250, 470, 740), outline="black", width=5)
    draw.rectangle((790, 210, 1190, 780), outline="black", width=5)
    _draw_text(draw, (305, 430), "Li", 56, bold=True)
    _draw_text(draw, (1115, 220), "+", 54, bold=True)
    _draw_text(draw, (955, 430), "Cl", 56, bold=True)
    _draw_text(draw, (1120, 730), "-", 58, bold=True)

    _draw_cross(draw, 295, 350, 12)
    _draw_cross(draw, 385, 350, 12)

    cl_pairs = [
        (900, 300, "dotdot"),
        (1080, 300, "dotdot"),
        (900, 690, "dotdot"),
        (1080, 690, "dotdot"),
        (860, 500, "dotdot", True),
        (1130, 500, "dotx", True),
    ]
    for pair in cl_pairs:
        vertical = len(pair) > 3 and bool(pair[3])
        _electron_pair(draw, pair[0], pair[1], pair[2], vertical=vertical)

    _save_image(image, path)


def _draw_ch3cooh_displayed(path: Path) -> None:
    image, draw = _new_canvas()
    _draw_text(draw, (80, 60), "Q5(e)(iii) DEV TEST - displayed formula for ethanoic acid", 36, bold=True)

    _draw_text(draw, (180, 420), "H", 40, bold=True)
    _draw_text(draw, (280, 420), "C", 48, bold=True)
    _draw_text(draw, (430, 420), "C", 48, bold=True)
    _draw_text(draw, (590, 360), "O", 48, bold=True)
    _draw_text(draw, (590, 500), "O", 48, bold=True)
    _draw_text(draw, (760, 500), "H", 40, bold=True)
    _draw_text(draw, (280, 260), "H", 40, bold=True)
    _draw_text(draw, (280, 580), "H", 40, bold=True)

    draw.line((230, 435, 275, 435), fill="black", width=4)
    draw.line((330, 435, 420, 435), fill="black", width=4)
    draw.line((475, 418, 565, 382), fill="black", width=4)
    draw.line((480, 440, 570, 404), fill="black", width=4)
    draw.line((475, 450, 565, 515), fill="black", width=4)
    draw.line((635, 520, 735, 520), fill="black", width=4)
    draw.line((305, 400, 305, 300), fill="black", width=4)
    draw.line((305, 468, 305, 560), fill="black", width=4)

    _save_image(image, path)


def _draw_but2ene_displayed(path: Path) -> None:
    image, draw = _new_canvas()
    _draw_text(draw, (80, 60), "Q6(c)(i) DEV TEST - displayed formula for but-2-ene", 36, bold=True)

    carbon_points = [(240, 500), (470, 500), (700, 500), (930, 500)]
    for x, y in carbon_points:
        _draw_text(draw, (x - 20, y - 30), "C", 48, bold=True)

    # Main chain with middle double bond.
    draw.line((285, 520, 445, 520), fill="black", width=4)
    draw.line((515, 510, 655, 510), fill="black", width=4)
    draw.line((515, 530, 655, 530), fill="black", width=4)
    draw.line((745, 520, 905, 520), fill="black", width=4)

    hydrogen_labels = [
        ((150, 500), (210, 520)),
        ((240, 330), (240, 470)),
        ((240, 670), (240, 560)),
        ((470, 330), (470, 470)),
        ((700, 670), (700, 560)),
        ((930, 330), (930, 470)),
        ((930, 670), (930, 560)),
        ((1030, 500), (970, 520)),
    ]
    for (hx, hy), (tx, ty) in hydrogen_labels:
        _draw_text(draw, (hx - 10, hy - 20), "H", 38, bold=True)
        draw.line((tx, ty, hx, hy), fill="black", width=4)

    _save_image(image, path)
