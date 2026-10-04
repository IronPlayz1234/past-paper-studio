"""Choice-group resolver for Cambridge-style optional question structures."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Sequence

from Utils.question_id_mapper import normalize_question_id_canonical as normalize_question_id

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

_OPTIONAL_HINTS = (
    "answer one",
    "choose one",
    "choose any one",
    "either",
    "one of the following",
    "select one",
    "write about one",
)


def _instruction_has_choice_signal(instruction_text: str, question_texts: Dict[str, str]) -> bool:
    low = str(instruction_text or "").lower()
    patterns = (
        r"\beither\s+question\b",
        r"\banswer\s+(?:one|two|three|four|five|six|\d+)\s+question(?:s)?\s+from\b",
        r"\bchoose\s+(?:one|two|three|four|five|six|\d+)\b",
        r"\bchoice\s+of\b",
        r"\bone\s+question\s+from\s+each\s+section\b",
        r"\bcompulsory\s+question\b",
        r"\bsection\s+[a-z]\b",
    )
    if any(re.search(pattern, low) for pattern in patterns):
        return True

    for raw_text in (question_texts or {}).values():
        question_low = str(raw_text or "").lower()
        if any(hint in question_low for hint in _OPTIONAL_HINTS):
            return True
    return False


@dataclass(slots=True)
class ChoiceGroup:
    key: str
    members: List[str]
    min_required: int = 1
    max_allowed: int = 1
    section: str = ""
    label: str = ""


@dataclass(slots=True)
class ChoiceStructure:
    question_ids: List[str]
    groups: List[ChoiceGroup] = field(default_factory=list)
    compulsory_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ChoiceResolution:
    active_question_ids: List[str]
    skipped_question_ids: List[str]
    manual_review_required_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence: float = 0.0


def _dedupe_ids(ids: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in ids:
        qid = normalize_question_id(str(raw or ""))
        if not qid or qid in seen:
            continue
        seen.add(qid)
        out.append(qid)
    return out


def _word_to_int(raw: str) -> int:
    token = str(raw or "").strip().lower()
    if token.isdigit():
        return int(token)
    return int(_NUMBER_WORDS.get(token, 0) or 0)


def _extract_sections(question_texts: Dict[str, str]) -> Dict[str, str]:
    section_by_qid: Dict[str, str] = {}
    for raw_qid, raw_text in (question_texts or {}).items():
        qid = normalize_question_id(str(raw_qid or ""))
        if not qid:
            continue
        text = str(raw_text or "")
        match = re.search(r"\bsection\s+([a-z])\b", text, flags=re.IGNORECASE)
        if match:
            section_by_qid[qid] = match.group(1).upper()
    return section_by_qid


def _group_optional_by_signature(question_ids: Sequence[str], question_texts: Dict[str, str]) -> List[ChoiceGroup]:
    grouped: Dict[str, List[str]] = {}
    for qid in question_ids:
        text = str(question_texts.get(qid, "") or "")
        low = text.lower()
        if not any(h in low for h in _OPTIONAL_HINTS):
            continue
        signature = re.sub(r"\s+", " ", low.strip())
        signature = re.sub(r"question\s*\d+[a-zivx()\.]*", "question", signature)
        signature = re.sub(r"\b\d+[a-zivx()\.]*\b", "", signature)
        signature = re.sub(r"[^a-z\s]", " ", signature)
        signature = re.sub(r"\s+", " ", signature).strip()[:140]
        grouped.setdefault(signature, [])
        if qid not in grouped[signature]:
            grouped[signature].append(qid)

    out: List[ChoiceGroup] = []
    for members in grouped.values():
        members = _dedupe_ids(members)
        if len(members) < 2:
            continue
        key = "|".join(members)
        out.append(ChoiceGroup(key=key, members=members, min_required=1, max_allowed=1, label="heuristic_optional"))
    return out


def parse_choice_structure(
    instruction_text: str,
    question_ids: List[str],
    question_texts: Dict[str, str],
) -> ChoiceStructure:
    ordered_ids = _dedupe_ids(question_ids or [])
    text = str(instruction_text or "")
    low = text.lower()
    warnings: List[str] = []
    groups: List[ChoiceGroup] = []
    compulsory_ids: List[str] = []
    confidence = 0.0

    if not ordered_ids:
        return ChoiceStructure(question_ids=[], groups=[], compulsory_ids=[], confidence=1.0, warnings=[])

    if re.search(r"\ball\s+questions?\s+(?:are\s+)?compulsory\b", low):
        return ChoiceStructure(
            question_ids=ordered_ids,
            groups=[],
            compulsory_ids=list(ordered_ids),
            confidence=0.98,
            warnings=[],
        )

    explicit_either = re.findall(
        r"\beither\s+question\s*([0-9]+[a-zivx]*)\s+or\s+question\s*([0-9]+[a-zivx]*)",
        low,
    )
    for left, right in explicit_either:
        members = _dedupe_ids([left, right])
        if len(members) == 2:
            groups.append(
                ChoiceGroup(
                    key="|".join(members),
                    members=members,
                    min_required=1,
                    max_allowed=1,
                    label="either_or",
                )
            )
            confidence = max(confidence, 0.92)

    comp_q_match = re.search(r"\bcompulsory\s+question\s*([0-9]+[a-zivx]*)\b", low)
    if comp_q_match:
        comp_qid = normalize_question_id(comp_q_match.group(1))
        if comp_qid and comp_qid in ordered_ids:
            compulsory_ids.append(comp_qid)
            confidence = max(confidence, 0.9)

    section_by_qid = _extract_sections(question_texts)

    each_section_match = re.search(r"answer\s+one\s+question\s+from\s+each\s+section", low)
    if each_section_match and section_by_qid:
        sections: Dict[str, List[str]] = {}
        for qid in ordered_ids:
            section = section_by_qid.get(qid, "")
            if section:
                sections.setdefault(section, []).append(qid)
        for section, members in sections.items():
            dedup_members = _dedupe_ids(members)
            if len(dedup_members) >= 2:
                groups.append(
                    ChoiceGroup(
                        key=f"section_{section}|" + "|".join(dedup_members),
                        members=dedup_members,
                        min_required=1,
                        max_allowed=1,
                        section=section,
                        label="one_from_each_section",
                    )
                )
        confidence = max(confidence, 0.86)

    choice_match = re.search(
        r"answer\s+(one|two|three|four|five|six|\d+)\s+question(?:s)?\s+from\s+(?:a\s+)?choice\s+of\s+(one|two|three|four|five|six|\d+)",
        low,
    )
    if choice_match:
        required = _word_to_int(choice_match.group(1))
        pool_size = _word_to_int(choice_match.group(2))
        if required > 0:
            members = _group_optional_by_signature(ordered_ids, question_texts)
            if members:
                primary = list(members[0].members)
            else:
                primary = list(ordered_ids)
            if pool_size > 0 and len(primary) > pool_size:
                primary = primary[:pool_size]
            if len(primary) >= max(required, 2):
                groups.append(
                    ChoiceGroup(
                        key="global_choice|" + "|".join(primary),
                        members=primary,
                        min_required=required,
                        max_allowed=required,
                        label="global_choice_quota",
                    )
                )
                confidence = max(confidence, 0.84)

    section_quota_matches = re.findall(
        r"(?:answer|and)\s+(one|two|three|four|five|six|\d+)\s+question(?:s)?\s+from\s+section\s+([a-z])",
        low,
    )
    for count_token, section_token in section_quota_matches:
        required = _word_to_int(count_token)
        section = str(section_token or "").upper()
        members = [qid for qid in ordered_ids if section_by_qid.get(qid, "") == section]
        members = _dedupe_ids(members)
        if required > 0 and len(members) >= max(required, 2):
            groups.append(
                ChoiceGroup(
                    key=f"section_{section}_quota|" + "|".join(members),
                    members=members,
                    min_required=required,
                    max_allowed=required,
                    section=section,
                    label="section_quota",
                )
            )
            confidence = max(confidence, 0.9)

    if not groups:
        fallback_groups = _group_optional_by_signature(ordered_ids, question_texts)
        if fallback_groups:
            groups.extend(fallback_groups)
            confidence = max(confidence, 0.58)

    deduped_groups: List[ChoiceGroup] = []
    seen_signatures: set[tuple[str, ...]] = set()
    for group in groups:
        members = _dedupe_ids(group.members)
        if len(members) < 2:
            continue
        signature = tuple(members)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        deduped_groups.append(
            ChoiceGroup(
                key=group.key,
                members=members,
                min_required=max(0, int(group.min_required)),
                max_allowed=max(0, int(group.max_allowed)),
                section=group.section,
                label=group.label,
            )
        )

    if not deduped_groups and not compulsory_ids and _instruction_has_choice_signal(text, question_texts):
        warnings.append("choice_structure_not_detected")

    return ChoiceStructure(
        question_ids=ordered_ids,
        groups=deduped_groups,
        compulsory_ids=_dedupe_ids(compulsory_ids),
        confidence=float(confidence),
        warnings=warnings,
    )


def _has_answer(value: object) -> bool:
    return bool(str(value or "").strip())


def resolve_choice_selection(
    structure: ChoiceStructure,
    answers: Dict[str, str],
    question_marks: Dict[str, float],
    explicit_selection: Dict[str, List[str]],
) -> ChoiceResolution:
    ordered_ids = _dedupe_ids(getattr(structure, "question_ids", []) or [])
    active: set[str] = set(ordered_ids)
    skipped: set[str] = set()
    manual_review: set[str] = set()
    warnings: List[str] = list(getattr(structure, "warnings", []) or [])

    if not ordered_ids:
        return ChoiceResolution(active_question_ids=[], skipped_question_ids=[], manual_review_required_ids=[], warnings=warnings, confidence=1.0)

    normalized_answers = {normalize_question_id(k): v for k, v in (answers or {}).items()}
    explicit = explicit_selection if isinstance(explicit_selection, dict) else {}

    def _resolve_explicit_for_group(members: List[str]) -> List[str]:
        member_set = set(members)
        selected: List[str] = []
        for raw_key, raw_values in explicit.items():
            key_members = {
                normalize_question_id(part)
                for part in str(raw_key or "").split("|")
                if normalize_question_id(part)
            }
            if not key_members:
                continue
            if key_members == member_set or key_members.intersection(member_set):
                if isinstance(raw_values, (list, tuple, set)):
                    for value in raw_values:
                        qid = normalize_question_id(str(value or ""))
                        if qid in member_set and qid not in selected:
                            selected.append(qid)
        return selected

    for group in getattr(structure, "groups", []) or []:
        members = [qid for qid in _dedupe_ids(group.members) if qid in active]
        if len(members) < 2:
            continue

        selected = _resolve_explicit_for_group(members)
        if not selected:
            selected = [qid for qid in members if _has_answer(normalized_answers.get(qid, ""))]

        max_allowed = max(0, int(group.max_allowed or group.min_required or 1))
        min_required = max(0, int(group.min_required or 0))

        if max_allowed <= 0:
            max_allowed = max(1, min_required)

        if len(selected) > max_allowed:
            overflow = selected[max_allowed:]
            manual_review.update(overflow)
            warnings.append(f"over_selected:{group.key}")
            selected = selected[:max_allowed]

        if len(selected) < min_required:
            remaining = [qid for qid in members if qid not in selected]
            fill_needed = min_required - len(selected)
            auto_fill = remaining[:fill_needed]
            if auto_fill:
                warnings.append(f"under_selected_autofill:{group.key}")
            selected.extend(auto_fill)

        selected_set = set(selected)
        for qid in members:
            if qid not in selected_set:
                skipped.add(qid)
                if qid in active:
                    active.remove(qid)

    for qid in _dedupe_ids(getattr(structure, "compulsory_ids", []) or []):
        if qid in ordered_ids:
            active.add(qid)
            if qid in skipped:
                skipped.remove(qid)

    ordered_active = [qid for qid in ordered_ids if qid in active]
    ordered_skipped = [qid for qid in ordered_ids if qid in skipped]
    ordered_manual = [qid for qid in ordered_ids if qid in manual_review]

    return ChoiceResolution(
        active_question_ids=ordered_active,
        skipped_question_ids=ordered_skipped,
        manual_review_required_ids=ordered_manual,
        warnings=list(dict.fromkeys(warnings)),
        confidence=float(getattr(structure, "confidence", 0.0) or 0.0),
    )
