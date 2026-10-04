"""Built-in subject scope for the final Alpha release."""

IGCSE_SUBJECTS = {
    "0580": "Mathematics",
    "0607": "International Mathematics",
    "0500": "First Language English",
    "0625": "Physics",
    "0620": "Chemistry",
    "0478": "Computer Science",
    "0455": "Economics",
    "0470": "History",
    "0450": "Business Studies",
    "0417": "Information and Communication Technology (ICT)",
    "0610": "Biology",
}

ALEVEL_SUBJECTS = {
    "9709": "Mathematics",
    "9702": "Physics",
    "9700": "Biology",
    "9701": "Chemistry",
    "9231": "Further Mathematics",
    "9618": "Computer Science",
    "9708": "Economics",
    "9695": "English Literature",
    "9093": "English Language",
    "9609": "Business",
    "9990": "Psychology",
}

SUPPORTED_SUBJECTS = {**IGCSE_SUBJECTS, **ALEVEL_SUBJECTS}
