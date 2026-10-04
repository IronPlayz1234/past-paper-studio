"""Question ID parsing, normalization, mapping, and answer-key expansion utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from typing import Any, Dict, List, Optional


ROMAN_NUMERALS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
ROMAN_SET = set(ROMAN_NUMERALS)


@dataclass
class QuestionIDParts:
    """Parsed question identifier parts."""

    raw: str
    main: Optional[int] = None
    part: Optional[str] = None
    subpart: Optional[str] = None
    canonical: str = ""
    valid: bool = False


@dataclass
class QuestionNode:
    """Hierarchy node for a question identifier."""

    canonical_id: str
    display_id: str
    main: Optional[int]
    part: Optional[str] = None
    subpart: Optional[str] = None
    page: Optional[int] = None
    text: str = ""


@dataclass
class QuestionLeaf(QuestionNode):
    """Leaf answerable question node used by the UI/grading pipeline."""

    parent_id: Optional[str] = None
    level: int = 0
    response_type: str = "text"  # text | drawing
    requires_manual_review: bool = False
    manual_review_reason: str = ""
    section_type: str = "written"
    table_spec: Optional[Dict[str, Any]] = None
    drawing_reference_path: Optional[str | Dict[str, Any]] = None


@dataclass
class MappingEntry:
    """Mapping of one extracted question ID to one answer-key ID."""

    extracted_id: str
    answer_key_id: Optional[str]
    strategy: str
    confidence: float
    notes: str = ""


@dataclass
class MappingReport:
    """Diagnostic mapping report."""

    entries: Dict[str, MappingEntry] = field(default_factory=dict)
    reverse_mapping: Dict[str, List[str]] = field(default_factory=dict)
    unmatched_extracted: List[str] = field(default_factory=list)
    unused_answer_keys: List[str] = field(default_factory=list)
    coverage: float = 0.0
    average_confidence: float = 0.0
    structure_analysis: Dict[str, object] = field(default_factory=dict)


def _clean_raw_id(raw: str) -> str:
    text = (raw or "").strip().lower()
    text = text.replace("\u00a0", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"^(question|q)\s*", "", text)
    text = re.sub(r"[\.:_\-]+", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _split_rest(rest: str) -> tuple[Optional[str], Optional[str], bool]:
    """Split post-main token into part/subpart.

    Returns: (part, subpart, valid)
    """
    if not rest:
        return None, None, True

    # Remove wrappers that survive malformed inputs, e.g. "(a)(ii)" -> "aii"
    compact = rest.replace("(", "").replace(")", "")
    if not compact:
        return None, None, True

    # Roman-only forms: 1i, 1ii, 1(i)
    if compact in ROMAN_SET:
        return None, compact, True

    if compact[0].isalpha():
        part = compact[0]
        remainder = compact[1:]

        # Canonical part letters are usually alphabetical a-z
        if not part.isalpha():
            return None, None, False

        if not remainder:
            return part, None, True

        # Standard nested roman subpart
        if remainder in ROMAN_SET:
            return part, remainder, True

        # Graceful fallback: unknown suffix treated as subpart token
        if remainder.isalpha():
            return part, remainder, True

    return None, None, False


def canonical_id(parts: QuestionIDParts) -> str:
    if not parts.valid or parts.main is None:
        return ""

    if parts.part and parts.subpart:
        return f"{parts.main}({parts.part})({parts.subpart})"
    if parts.part:
        return f"{parts.main}({parts.part})"
    if parts.subpart:
        return f"{parts.main}({parts.subpart})"
    return f"{parts.main}"


def parse_question_id(raw: str) -> QuestionIDParts:
    """Parse many ID variants into canonical hierarchical parts."""
    raw_text = raw or ""
    cleaned = _clean_raw_id(raw_text)
    if not cleaned:
        return QuestionIDParts(raw=raw_text)

    match = re.match(r"^(\d{1,3})(.*)$", cleaned)
    if not match:
        return QuestionIDParts(raw=raw_text)

    main = int(match.group(1))
    rest = match.group(2)
    part, subpart, ok = _split_rest(rest)
    parsed = QuestionIDParts(raw=raw_text, main=main, part=part, subpart=subpart, valid=ok)
    parsed.canonical = canonical_id(parsed)
    return parsed


def normalize_question_id_canonical(raw: str) -> str:
    parts = parse_question_id(raw)
    if parts.valid and parts.canonical:
        return parts.canonical

    fallback = re.sub(r"\W+", "", (raw or "").strip().lower())
    return fallback


def format_question_display(raw: str) -> str:
    parts = parse_question_id(raw)
    if not parts.valid or parts.main is None:
        return (raw or "").strip()

    return canonical_id(parts)


def _simplify(raw: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (raw or "").strip().lower())


def _parent_id(qid: str) -> Optional[str]:
    parts = parse_question_id(qid)
    if not parts.valid or parts.main is None:
        return None
    if parts.part and parts.subpart:
        return f"{parts.main}({parts.part})"
    return None


def _main_of(qid: str) -> Optional[int]:
    parts = parse_question_id(qid)
    return parts.main if parts.valid else None


class QuestionIDMapper:
    """Generate resilient mappings between extracted IDs and answer-key IDs."""

    STRATEGY_CONFIDENCE = {
        "manual_override": 1.0,
        "direct": 1.0,
        "parent": 0.92,
        "simplified": 0.85,
        "sequence": 0.65,
        "fuzzy": 0.55,
        "unmatched": 0.0,
    }

    def analyze_structure(self, extracted_ids: List[str], answer_key_ids: List[str]) -> Dict[str, object]:
        extracted = [normalize_question_id_canonical(x) for x in extracted_ids if normalize_question_id_canonical(x)]
        answer = [normalize_question_id_canonical(x) for x in answer_key_ids if normalize_question_id_canonical(x)]

        def stats(ids: List[str]) -> Dict[str, int]:
            mains = set()
            parts = 0
            subparts = 0
            for qid in ids:
                parsed = parse_question_id(qid)
                if parsed.main is not None:
                    mains.add(parsed.main)
                if parsed.part:
                    parts += 1
                if parsed.subpart:
                    subparts += 1
            return {
                "count": len(ids),
                "main_questions": len(mains),
                "part_entries": parts,
                "subpart_entries": subparts,
            }

        extracted_stats = stats(extracted)
        answer_stats = stats(answer)

        key_mode = "flat"
        if answer_stats["part_entries"] > 0:
            key_mode = "hierarchical"
        if answer_stats["subpart_entries"] > 0:
            key_mode = "granular"

        overlap = len(set(extracted).intersection(set(answer)))

        return {
            "extracted": extracted_stats,
            "answer_key": answer_stats,
            "answer_key_mode": key_mode,
            "exact_overlap": overlap,
        }

    def generate_mapping(
        self,
        extracted_ids: List[str],
        answer_key_ids: List[str],
        question_order: Optional[List[str]] = None,
        manual_overrides: Optional[Dict[str, str]] = None,
    ) -> MappingReport:
        manual_overrides = manual_overrides or {}

        extracted = [normalize_question_id_canonical(x) for x in extracted_ids if normalize_question_id_canonical(x)]
        answer_keys = [normalize_question_id_canonical(x) for x in answer_key_ids if normalize_question_id_canonical(x)]

        order = [normalize_question_id_canonical(x) for x in (question_order or extracted)]
        order = [x for x in order if x in extracted]
        if not order:
            order = extracted

        answer_set = set(answer_keys)
        simplified_map: Dict[str, List[str]] = {}
        for aid in answer_keys:
            simplified_map.setdefault(_simplify(aid), []).append(aid)

        entries: Dict[str, MappingEntry] = {}

        # 0) Manual overrides
        for ex in order:
            override_raw = manual_overrides.get(ex) or manual_overrides.get(format_question_display(ex))
            if not override_raw:
                continue
            override = normalize_question_id_canonical(override_raw)
            if override and override in answer_set:
                entries[ex] = MappingEntry(
                    extracted_id=ex,
                    answer_key_id=override,
                    strategy="manual_override",
                    confidence=self.STRATEGY_CONFIDENCE["manual_override"],
                    notes="User override",
                )

        # 1) Direct
        for ex in order:
            if ex in entries:
                continue
            if ex in answer_set:
                entries[ex] = MappingEntry(
                    extracted_id=ex,
                    answer_key_id=ex,
                    strategy="direct",
                    confidence=self.STRATEGY_CONFIDENCE["direct"],
                )

        # 2) Parent fallback
        for ex in order:
            if ex in entries:
                continue
            parent = _parent_id(ex)
            if parent and parent in answer_set:
                entries[ex] = MappingEntry(
                    extracted_id=ex,
                    answer_key_id=parent,
                    strategy="parent",
                    confidence=self.STRATEGY_CONFIDENCE["parent"],
                )

        # 3) Simplified
        for ex in order:
            if ex in entries:
                continue
            candidates = simplified_map.get(_simplify(ex), [])
            if len(candidates) == 1:
                entries[ex] = MappingEntry(
                    extracted_id=ex,
                    answer_key_id=candidates[0],
                    strategy="simplified",
                    confidence=self.STRATEGY_CONFIDENCE["simplified"],
                )

        # 4) Sequence-aware within same main question
        unmapped = [ex for ex in order if ex not in entries]
        if unmapped:
            by_main_ex: Dict[Optional[int], List[str]] = {}
            by_main_ans: Dict[Optional[int], List[str]] = {}
            for ex in unmapped:
                by_main_ex.setdefault(_main_of(ex), []).append(ex)
            for aid in answer_keys:
                by_main_ans.setdefault(_main_of(aid), []).append(aid)

            for main, ex_list in by_main_ex.items():
                if main is None:
                    continue
                cand = [aid for aid in by_main_ans.get(main, [])]
                if not cand:
                    continue
                for idx, ex in enumerate(ex_list):
                    if ex in entries:
                        continue
                    if idx < len(cand):
                        entries[ex] = MappingEntry(
                            extracted_id=ex,
                            answer_key_id=cand[idx],
                            strategy="sequence",
                            confidence=self.STRATEGY_CONFIDENCE["sequence"],
                        )

        # 5) Fuzzy last resort
        for ex in order:
            if ex in entries:
                continue
            best = None
            best_score = 0.0
            for aid in answer_keys:
                score = SequenceMatcher(None, _simplify(ex), _simplify(aid)).ratio()
                if score > best_score:
                    best = aid
                    best_score = score
            if best and best_score >= 0.85:
                entries[ex] = MappingEntry(
                    extracted_id=ex,
                    answer_key_id=best,
                    strategy="fuzzy",
                    confidence=self.STRATEGY_CONFIDENCE["fuzzy"],
                    notes=f"similarity={best_score:.2f}",
                )
            else:
                entries[ex] = MappingEntry(
                    extracted_id=ex,
                    answer_key_id=None,
                    strategy="unmatched",
                    confidence=self.STRATEGY_CONFIDENCE["unmatched"],
                )

        return self.validate_mapping(entries, answer_keys, extracted, self.analyze_structure(extracted, answer_keys))

    def validate_mapping(
        self,
        entries: Dict[str, MappingEntry],
        answer_key_ids: List[str],
        extracted_ids: List[str],
        structure_analysis: Optional[Dict[str, object]] = None,
    ) -> MappingReport:
        reverse: Dict[str, List[str]] = {}
        unmatched: List[str] = []
        for ex in extracted_ids:
            ent = entries.get(ex)
            if not ent or not ent.answer_key_id:
                unmatched.append(ex)
                continue
            reverse.setdefault(ent.answer_key_id, []).append(ex)

        used = set(reverse.keys())
        unused = [aid for aid in answer_key_ids if aid not in used]

        coverage = 0.0
        avg_conf = 0.0
        if extracted_ids:
            coverage = (len(extracted_ids) - len(unmatched)) / len(extracted_ids)
            avg_conf = sum(entries[q].confidence for q in extracted_ids if q in entries) / len(extracted_ids)

        return MappingReport(
            entries=entries,
            reverse_mapping=reverse,
            unmatched_extracted=unmatched,
            unused_answer_keys=unused,
            coverage=coverage,
            average_confidence=avg_conf,
            structure_analysis=structure_analysis or {},
        )

    def expand_answer_key(
        self,
        answer_key: Dict[str, Dict[str, object]],
        mapping: MappingReport,
        question_marks: Optional[Dict[str, float]] = None,
        policy: str = "hybrid_split",
    ) -> Dict[str, Dict[str, object]]:
        """Expand parent-level answer keys to extracted leaf-level IDs.

        Policy supported:
        - hybrid_split: use direct child marks if present; otherwise split parent marks
          across mapped children while preserving parent total marks.
        - strict_leaf: only trust exact leaf rows; unresolved leafs stay unresolved.
        """
        question_marks = question_marks or {}
        normalized_key: Dict[str, Dict[str, object]] = {}
        for key_id, info in (answer_key or {}).items():
            norm = normalize_question_id_canonical(key_id)
            if norm:
                normalized_key[norm] = dict(info or {})

        if policy == "strict_leaf":
            expanded: Dict[str, Dict[str, object]] = {}
            for extracted_id, entry in mapping.entries.items():
                mapped_id = normalize_question_id_canonical(entry.answer_key_id or "")
                info = dict(normalized_key.get(mapped_id, {}) or {}) if mapped_id else {}
                trusted_mapping = entry.strategy in {"manual_override", "direct", "simplified"}
                exact_leaf_row = bool(mapped_id and mapped_id in normalized_key and trusted_mapping)

                answer_text = str(info.get("mark_scheme_text", info.get("answer", "")) or "").strip()
                if not exact_leaf_row or not answer_text or answer_text == "[See Mark Scheme]":
                    answer_text = "[See Mark Scheme]"

                try:
                    row_marks = float(info.get("marks", 0.0) or 0.0)
                except Exception:
                    row_marks = 0.0
                try:
                    hint_marks = float(question_marks.get(extracted_id, 0.0) or 0.0)
                except Exception:
                    hint_marks = 0.0

                if row_marks > 0:
                    marks_value = row_marks
                    max_marks_source = str(info.get("max_marks_source", "mark_scheme_row") or "mark_scheme_row")
                elif hint_marks > 0:
                    marks_value = hint_marks
                    max_marks_source = "question_paper_hint"
                else:
                    marks_value = 0.0
                    max_marks_source = "unresolved"

                manual_review_reason = ""
                if not exact_leaf_row:
                    manual_review_reason = "No exact leaf mark-scheme block was matched safely."
                elif answer_text == "[See Mark Scheme]":
                    manual_review_reason = "Exact leaf mark-scheme text could not be extracted safely."
                elif marks_value <= 0:
                    manual_review_reason = "Exact leaf maximum marks could not be sourced safely."

                expanded[extracted_id] = {
                    "question_id": extracted_id,
                    "answer": answer_text,
                    "mark_scheme_text": answer_text,
                    "marks": float(marks_value),
                    "parent_id": None,
                    "mapping_strategy": entry.strategy,
                    "mapping_confidence": entry.confidence,
                    "mapping_source": "answer_key_direct" if exact_leaf_row else "unresolved_placeholder",
                    "source_answer_id": mapped_id if mapped_id and mapped_id != extracted_id else None,
                    "max_marks_source": max_marks_source,
                    "mark_scheme_source": "mark_scheme_pdf" if answer_text != "[See Mark Scheme]" else "unresolved",
                    "fallback_used": bool(manual_review_reason or max_marks_source != "mark_scheme_row"),
                    "manual_review_required": bool(manual_review_reason),
                    "manual_review_reason": manual_review_reason,
                }
            return expanded

        expanded: Dict[str, Dict[str, object]] = {}

        for parent_id, children in mapping.reverse_mapping.items():
            parent_info = normalized_key.get(parent_id, {})
            parent_answer = parent_info.get("answer", "[See Mark Scheme]")
            parent_marks = float(parent_info.get("marks", question_marks.get(parent_id, 1.0) or 1.0))

            # Direct children that already have explicit entries in key should keep them.
            direct_children = [cid for cid in children if cid in normalized_key]
            pending_children = [cid for cid in children if cid not in normalized_key]

            assigned_total = 0.0
            for cid in direct_children:
                child_info = dict(normalized_key[cid])
                marks = float(child_info.get("marks", question_marks.get(cid, 1.0) or 1.0))
                assigned_total += marks
                entry = mapping.entries.get(cid)
                child_info.update(
                    {
                        "marks": marks,
                        "parent_id": parent_id if parent_id != cid else None,
                        "mapping_strategy": entry.strategy if entry else "direct",
                        "mapping_confidence": entry.confidence if entry else 1.0,
                        "mapping_source": "answer_key_direct",
                    }
                )
                expanded[cid] = child_info

            if pending_children:
                remaining = max(parent_marks - assigned_total, 0.0)
                if remaining <= 0 and policy == "hybrid_split":
                    remaining = parent_marks

                weights = []
                for cid in pending_children:
                    w = float(question_marks.get(cid, 1.0) or 1.0)
                    if w <= 0:
                        w = 1.0
                    weights.append(w)
                total_weight = sum(weights) or float(len(pending_children))

                running = 0.0
                for idx, cid in enumerate(pending_children):
                    if idx == len(pending_children) - 1:
                        marks = max(remaining - running, 0.0)
                    else:
                        marks = round((remaining * weights[idx]) / total_weight, 3)
                        running += marks

                    entry = mapping.entries.get(cid)
                    expanded[cid] = {
                        "answer": parent_answer,
                        "marks": marks,
                        "parent_id": parent_id if parent_id != cid else None,
                        "mapping_strategy": entry.strategy if entry else "parent",
                        "mapping_confidence": entry.confidence if entry else 0.92,
                        "mapping_source": "answer_key_expanded",
                        "source_answer_id": parent_id,
                    }

        # Unmatched extracted IDs still get placeholder entries for downstream grading robustness.
        for cid in mapping.unmatched_extracted:
            if cid in expanded:
                continue
            entry = mapping.entries.get(cid)
            expanded[cid] = {
                "answer": "[See Mark Scheme]",
                "marks": float(question_marks.get(cid, 1.0) or 1.0),
                "parent_id": None,
                "mapping_strategy": entry.strategy if entry else "unmatched",
                "mapping_confidence": entry.confidence if entry else 0.0,
                "mapping_source": "unmatched_placeholder",
            }

        return expanded
