"""Subject guidance supplements (and never replaces) the supplied mark scheme."""
from dataclasses import dataclass
from Grading.subject_grading_profiles import get_subject_profile_key, get_subject_grading_profile

@dataclass(frozen=True)
class SubjectPromptContext:
    applies: bool
    subject_key: str
    system_addendum: str
    user_addendum: str

_GUIDANCE = {
    'mathematics': 'METHOD MARKS (M): Credit valid working only as allowed by the scheme; apply accuracy and follow-through dependencies.',
    'chemistry': 'CHEMICAL FORMULAE: Verify formulae are chemically correct. Check balancing, charges, units and state symbols when required.',
    'biology': 'BIOLOGICAL TERMINOLOGY: Require unambiguous concepts; accept equivalent wording allowed by the scheme.',
    'physics': 'UNITS: Require units when the scheme requires them. For circuit diagrams, a resistor drawn as a capacitor is wrong. Only permit error carried forward when the mark scheme allows "ecf".',
    'english_reading': 'READING COMPREHENSION: Credit evidence, inference and explanation according to the supplied rubric.',
    'english_writing': 'READING COMPREHENSION and writing: Apply the task-specific content, structure, register and accuracy bands.',
    'english_literature': 'READING COMPREHENSION: Credit supported interpretation and textual analysis.',
    'history': 'SOURCE QUESTIONS: Evaluate provenance, evidence and limitations where requested; apply the supplied level descriptors.',
    'economics': 'Business Studies / Economics. DEFINITIONS: Require precise business/economics definitions. Apply contextual analysis and evaluation bands.',
    'business': 'Business Studies / Economics. DEFINITIONS: Require precise business/economics definitions. Apply contextual analysis and evaluation bands.',
    'computer_science': 'PSEUDOCODE / FLOWCHARTS: Credit correct algorithms and logic; require syntax conventions only when the scheme specifies them.',
}

def get_subject_prompt_context(subject_code, paper_type=''):
    key = get_subject_profile_key(subject_code, paper_type)
    profile = get_subject_grading_profile(subject_code, paper_type)
    family = 'mathematics' if key in {'further_mathematics', 'statistics'} else key
    if key == 'default':
        return SubjectPromptContext(False, key, '', '')
    paper = str(paper_type).strip().lstrip('0')[:1]
    guidance = _GUIDANCE.get(family, profile.system_prompt)
    guidance += f' Paper {paper or "unspecified"}. The supplied mark scheme overrides all general guidance.'
    user = 'Subject-specific marking guidance: ' + guidance
    if family == 'mathematics':
        user += '\nMathematics marking focus: method, accuracy and permitted follow-through.'
    if paper == '6' and family in {'biology','chemistry','physics'}:
        guidance += ' Alternative to Practical: check experimental method, controls, observations and tables/graphs.'
        user += '\nPaper 6 focus: practical method, measurements, tables/graphs and evaluation.'
    return SubjectPromptContext(True, key, guidance, user)
