from Core.gui_main import PastPaperFinderGUI


def test_probe_attempt_summary_includes_model_attempts_and_reason():
    summary = PastPaperFinderGUI._format_probe_attempt_summary(
        attempt_counts={
            "meta-llama/llama-4-scout-17b-16e-instruct": 2,
            "meta-llama/llama-4-maverick-17b-128e-instruct": 1,
        },
        model_errors={
            "meta-llama/llama-4-scout-17b-16e-instruct": "Groq reported model unavailable for this API key.",
            "meta-llama/llama-4-maverick-17b-128e-instruct": "Groq reported model unavailable for this API key.",
        },
    )

    assert "meta-llama/llama-4-scout-17b-16e-instruct (attempts: 2)" in summary
    assert "meta-llama/llama-4-maverick-17b-128e-instruct (attempts: 1)" in summary
    assert "Groq reported model unavailable" in summary


def test_probe_attempt_summary_falls_back_when_no_attempts():
    summary = PastPaperFinderGUI._format_probe_attempt_summary({}, {})
    assert summary == "AI has not linked successfully."
