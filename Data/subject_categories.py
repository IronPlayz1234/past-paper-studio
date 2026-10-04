"""Presentation categories for supported syllabus codes; catalog stays authoritative."""

CATEGORY_CODES = {
    "Sciences": frozenset({"0610", "0620", "0625", "9700", "9701", "9702"}),
    "Mathematics": frozenset({"0580", "0607", "9709", "9231"}),
    "Languages": frozenset({"0500", "9093", "9695"}),
    "Humanities": frozenset({"0470", "0455", "0450", "9708", "9609", "9990"}),
    "Computing / Technology": frozenset({"0478", "0417", "9618"}),
}
CATEGORY_ORDER = (*CATEGORY_CODES, "Other")


def subject_category(code):
    return next(
        (category for category, codes in CATEGORY_CODES.items() if str(code) in codes),
        "Other",
    )
