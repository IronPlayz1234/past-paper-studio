"""Periodic table page detection utilities for chemistry PDFs."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

try:
    from Core import pdf_service as fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None


_ELEMENT_SYMBOLS = {
    "h", "he", "li", "be", "b", "c", "n", "o", "f", "ne", "na", "mg", "al", "si", "p", "s", "cl",
    "ar", "k", "ca", "sc", "ti", "v", "cr", "mn", "fe", "co", "ni", "cu", "zn", "ga", "ge", "as", "se",
    "br", "kr", "rb", "sr", "y", "zr", "nb", "mo", "tc", "ru", "rh", "pd", "ag", "cd", "in", "sn", "sb",
    "te", "i", "xe", "cs", "ba", "la", "ce", "pr", "nd", "pm", "sm", "eu", "gd", "tb", "dy", "ho", "er",
    "tm", "yb", "lu", "hf", "ta", "w", "re", "os", "ir", "pt", "au", "hg", "tl", "pb", "bi", "po", "at",
    "rn", "fr", "ra", "ac", "th", "pa", "u", "np", "pu", "am", "cm", "bk", "cf", "es", "fm", "md", "no",
    "lr", "rf", "db", "sg", "bh", "hs", "mt", "ds", "rg", "cn", "nh", "fl", "mc", "lv", "ts", "og",
}


def _page_score(text: str) -> float:
    low = (text or "").lower()
    if not low.strip():
        return 0.0

    score = 0.0
    if "periodic table" in low:
        score += 12.0

    cue_weights = {
        "atomic number": 3.0,
        "relative atomic mass": 3.5,
        "atomic mass": 2.0,
        "group": 1.0,
        "period": 1.0,
        "symbol": 1.0,
        "element": 1.0,
        "proton number": 2.0,
    }
    for cue, weight in cue_weights.items():
        if cue in low:
            score += weight

    tokens = re.findall(r"\b[a-z]{1,2}\b", low)
    sym_hits = sum(1 for t in tokens if t in _ELEMENT_SYMBOLS)
    score += min(sym_hits, 50) * 0.15

    # Long pages with table-like symbol density are stronger candidates.
    if sym_hits >= 20:
        score += 3.0

    return score


def find_periodic_table_page(pdf_path: str, threshold: float = 10.0, cancel_check=None) -> Optional[int]:
    """Return 1-based page number of likely periodic table page if detected."""
    if not fitz or not pdf_path:
        return None

    best_page: Optional[int] = None
    best_score = 0.0

    doc = fitz.open(pdf_path)
    try:
        for idx in range(len(doc)):
            if cancel_check is not None and cancel_check():
                return None
            page_text = doc[idx].get_text("text")
            score = _page_score(page_text)
            if score > best_score:
                best_score = score
                best_page = idx + 1
    finally:
        doc.close()

    if best_page is None:
        return None
    if best_score < threshold:
        return None
    return best_page


def build_page_snippets(pdf_path: str, max_chars: int = 90) -> List[Tuple[int, str]]:
    """Build (page_number, snippet) list for manual page selection fallback."""
    snippets: List[Tuple[int, str]] = []
    if not fitz or not pdf_path:
        return snippets

    doc = fitz.open(pdf_path)
    try:
        for idx in range(len(doc)):
            text = doc[idx].get_text("text")
            compact = re.sub(r"\s+", " ", text or "").strip()
            if not compact:
                compact = "(no extractable text)"
            snippet = compact[:max_chars]
            snippets.append((idx + 1, snippet))
    finally:
        doc.close()

    return snippets
