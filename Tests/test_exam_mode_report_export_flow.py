import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from Core.exam_mode import ExamModeWindow


def test_export_grading_report_into_folder_creates_timestamped_directory(tmp_path: Path):
    report = tmp_path / "grading_report.md"
    report.write_text("# report\n", encoding="utf-8")

    parent = tmp_path / "exports"
    parent.mkdir(parents=True, exist_ok=True)

    window = ExamModeWindow.__new__(ExamModeWindow)
    window.pdf_url = ""
    window.local_pdf_path = ""
    window.paper_number_raw = "21"
    window.paper_num = 2
    window.subject_code = "0620"
    window._autograde_submitted_at = datetime(2026, 3, 5, 10, 30, 0)

    target = ExamModeWindow._export_grading_report_into_folder(window, str(report), str(parent))

    assert target is not None
    target_path = Path(target)
    assert target_path.exists()
    assert target_path.read_text(encoding="utf-8") == "# report\n"
    folder_name = target_path.parent.name
    assert folder_name.startswith("Grading report")
    assert "0620" in folder_name
