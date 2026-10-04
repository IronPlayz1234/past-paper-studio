"""Subject-aware grading profile definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class SubjectGradingProfile:
    key: str
    title: str
    system_prompt: str
    rubric_axes: List[str] = field(default_factory=list)
    normalization_rules: List[str] = field(default_factory=list)
    strictness_rules: List[str] = field(default_factory=list)
    units_policy: str = "normal"


DEFAULT_PROFILE = SubjectGradingProfile(
    key="default",
    title="General Cambridge",
    system_prompt=(
        "You are a Cambridge examiner. Grade fairly, award method marks where relevant, "
        "and keep marks within the provided maximum."
    ),
    rubric_axes=["accuracy", "completeness", "reasoning"],
    normalization_rules=["accept equivalent forms when mathematically or semantically equivalent"],
    strictness_rules=["do not exceed max marks", "do not invent mark scheme points"],
    units_policy="subject-dependent",
)


PROFILES: Dict[str, SubjectGradingProfile] = {
    "mathematics": SubjectGradingProfile(
        key="mathematics",
        title="Cambridge Mathematics",
        system_prompt=(
            "You are a Cambridge Mathematics examiner. Award method marks and accuracy marks separately, "
            "accept mathematically equivalent forms, and handle fraction/decimal/percentage equivalence."
        ),
        rubric_axes=["method", "accuracy", "presentation"],
        normalization_rules=["0.5 == 1/2 == 50%", "accept equivalent algebraic rearrangements"],
        strictness_rules=["keep tolerance narrow unless question implies rounding", "respect required units"],
        units_policy="required-if-question-requests-units",
    ),
    "chemistry": SubjectGradingProfile(
        key="chemistry",
        title="Cambridge Chemistry",
        system_prompt=(
            "You are a Cambridge Chemistry examiner. Prioritize key scientific terms, correct formulae, "
            "balanced equations, and explicit mark-point matching."
        ),
        rubric_axes=["scientific_accuracy", "terminology", "method"],
        normalization_rules=["accept H2O and H₂O equivalently", "accept common names where mark scheme allows"],
        strictness_rules=["balanced equations must be chemically valid"],
        units_policy="required-for-quantitative-answers",
    ),
    "biology": SubjectGradingProfile(
        key="biology",
        title="Cambridge Biology",
        system_prompt=(
            "You are a Cambridge Biology examiner. Award marks for key biological concepts and logical process "
            "descriptions, with leniency for minor spelling when meaning is clear."
        ),
        rubric_axes=["concepts", "process_accuracy", "terminology"],
        normalization_rules=["minor spelling errors may be acceptable if unambiguous"],
        strictness_rules=["require core biological terms for definitions"],
        units_policy="required-for-quantitative-answers",
    ),
    "physics": SubjectGradingProfile(
        key="physics",
        title="Cambridge Physics",
        system_prompt=(
            "You are a Cambridge Physics examiner. Mark using method + final answer logic, and enforce units "
            "for numerical answers unless explicitly not required."
        ),
        rubric_axes=["method", "physics_principle", "units"],
        normalization_rules=["accept equivalent formula rearrangements"],
        strictness_rules=["units are critical for final-mark award"],
        units_policy="strict",
    ),
    "ict": SubjectGradingProfile(
        key="ict",
        title="Cambridge ICT",
        system_prompt=(
            "You are a Cambridge ICT examiner. Credit technically correct terms and accepted equivalents "
            "(e.g., acronym and expanded form)."
        ),
        rubric_axes=["technical_accuracy", "terminology", "clarity"],
        normalization_rules=["RAM == Random Access Memory if context is correct"],
        strictness_rules=["deduct for conceptually wrong technical claims"],
        units_policy="normal",
    ),
    "english_reading": SubjectGradingProfile(
        key="english_reading",
        title="Cambridge English Reading",
        system_prompt=(
            "You are a Cambridge First Language English examiner for reading tasks. Reward evidence use, "
            "inference quality, and depth of explanation."
        ),
        rubric_axes=["content_points", "evidence", "analysis"],
        normalization_rules=["accept valid paraphrase where mark scheme allows"],
        strictness_rules=["require support for analytical claims"],
        units_policy="n/a",
    ),
    "english_writing": SubjectGradingProfile(
        key="english_writing",
        title="Cambridge English Writing",
        system_prompt=(
            "You are a Cambridge First Language English examiner for writing tasks. Assess content/structure, "
            "style/register, and language control according to Cambridge-style bands."
        ),
        rubric_axes=["content_structure", "style_register", "language_accuracy"],
        normalization_rules=["reward coherent ideas even if minor technical errors exist"],
        strictness_rules=["do not over-credit off-task writing"],
        units_policy="n/a",
    ),
}


SUBJECT_CODE_TO_PROFILE = {
    "0580": "mathematics",
    "0607": "mathematics",
    "9709": "mathematics",
    "9231": "mathematics",
    "9701": "chemistry",
    "9700": "biology",
    "9702": "physics",
    "9618": "ict",
    "0620": "chemistry",
    "0610": "biology",
    "0625": "physics",
    "0417": "ict",
    "0500": "english_reading",
}


# Registry-driven coverage; paper routing still decides whether a component is gradable.
from dataclasses import replace as _profile_variant
from Data.subjects_structure import list_supported_subjects as _supported_subjects

for key, title, axes in (
    ("history", "History", ["evidence", "source_evaluation", "argument"]),
    ("economics", "Economics", ["knowledge", "analysis", "evaluation"]),
    ("business", "Business Studies", ["knowledge", "application", "evaluation"]),
    ("computer_science", "Computer Science", ["algorithm_accuracy", "reasoning", "technical_accuracy"]),
    ("english_literature", "Literature", ["textual_evidence", "interpretation", "analysis"]),
    ("language", "Languages", ["communication", "accuracy", "task_fulfilment"]),
    ("general_rubric", "Subject Rubric", ["knowledge", "application", "evaluation"]),
):
    PROFILES[key] = _profile_variant(DEFAULT_PROFILE, key=key, title="Cambridge " + title,
        system_prompt=f"Apply the supplied {title} mark scheme and assessment objectives. Never invent a rubric when one is missing.",
        rubric_axes=axes)
PROFILES["further_mathematics"] = _profile_variant(PROFILES["mathematics"], key="further_mathematics", title="Cambridge Further Mathematics")
PROFILES["statistics"] = _profile_variant(PROFILES["mathematics"], key="statistics", title="Cambridge Statistics")

def _profile_for_name(name):
    low = name.casefold()
    for word, key in (("further math", "further_mathematics"), ("statistics", "statistics"),
        ("mathemat", "mathematics"), ("chemistry", "chemistry"), ("biology", "biology"),
        ("physics", "physics"), ("computer", "computer_science"), ("computing", "computer_science"),
        ("communication technology", "ict"), ("information technology", "ict"), ("ict", "ict"),
        ("literature", "english_literature"), ("english", "english_reading"),
        ("history", "history"),
        ("economics", "economics"), ("business", "business"),
        ("language", "language")):
        if word in low:
            return key
    return "general_rubric"

for _code, _name in _supported_subjects().items():
    SUBJECT_CODE_TO_PROFILE[_code] = _profile_for_name(_name)
SUBJECT_CODE_TO_PROFILE.update({"9231": "further_mathematics", "9618": "computer_science",
    "9093": "english_reading", "9695": "english_literature"})


def get_subject_profile_key(
    subject_code: str,
    paper_number: str = "",
    fallback_key: str = "default",
) -> str:
    code = str(subject_code or "").strip()
    pn = str(paper_number or "").strip()

    if code == "0500":
        # Reading vs writing split by component.
        if pn.lstrip("0").startswith("2"):
            return "english_writing"
        return "english_reading"

    return SUBJECT_CODE_TO_PROFILE.get(code, fallback_key)


def get_subject_grading_profile(subject_code: str, paper_number: str = "") -> SubjectGradingProfile:
    key = get_subject_profile_key(subject_code, paper_number)
    return PROFILES.get(key, DEFAULT_PROFILE)


def render_profile_block(profile: SubjectGradingProfile) -> str:
    lines: List[str] = []
    lines.append(f"Profile: {profile.title}")
    if profile.rubric_axes:
        lines.append("Rubric axes: " + ", ".join(profile.rubric_axes))
    if profile.normalization_rules:
        lines.append("Normalization rules:")
        for rule in profile.normalization_rules:
            lines.append(f"- {rule}")
    if profile.strictness_rules:
        lines.append("Strictness rules:")
        for rule in profile.strictness_rules:
            lines.append(f"- {rule}")
    lines.append(f"Grading Style: {profile.system_prompt}")
    lines.append("OCR notes: Flag unclear symbols or missing text for review; do not invent unreadable content.")
    lines.append(f"Units policy: {profile.units_policy}")
    return "\n".join(lines)
