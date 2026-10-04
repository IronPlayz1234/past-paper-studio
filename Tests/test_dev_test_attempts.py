import json
import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import Utils.dev_test_attempts as dev_test_attempts
from Core.gui_main import PastPaperFinderGUI
from Utils.gui_utils import ExamAttemptManager, HistoryManager


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _real_attempt() -> dict:
    return {
        "attempt_key": "real-attempt",
        "paper_code": "0620_w24_qp_41",
        "subject_code": "0620",
        "subject_name": "Chemistry",
        "paper_num": "4",
        "year": "2024",
        "pdf_url": "https://example.com/0620_w24_qp_41.pdf",
        "remaining_seconds": 1234,
        "answers": {"1(a)": {"type": "text", "value": "sample"}},
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }


def _configure_attempt_storage(monkeypatch, tmp_path: Path) -> None:
    attempts_file = tmp_path / "unfinished_exam_attempts.json"
    backup_file = tmp_path / "unfinished_exam_attempts.backup.json"
    assets_root = tmp_path / "attempt_assets"
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPTS_FILE", str(attempts_file))
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPTS_BACKUP_FILE", str(backup_file))
    monkeypatch.setattr(ExamAttemptManager, "ATTEMPT_ASSETS_ROOT", str(assets_root))


def _configure_dev_helper(monkeypatch, tmp_path: Path) -> Path:
    local_pdf = tmp_path / "0620_s22_qp_42.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 dev")
    monkeypatch.setenv(dev_test_attempts.DEV_TEST_ENV, "1")
    monkeypatch.setattr(dev_test_attempts.sys, "frozen", False, raising=False)
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_LOCAL_QP_PATH", str(local_pdf))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_ASSETS_ROOT", str(tmp_path / "dev_assets"))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_SEARCH_CACHE_FILE", str(tmp_path / "paper_search_cache.json"))
    return local_pdf


@pytest.mark.parametrize(
    ("env_value", "frozen_value"),
    [
        ("0", False),
        ("1", True),
    ],
)
def test_dev_test_attempt_is_not_injected_when_explicitly_disabled_or_frozen(
    monkeypatch,
    tmp_path: Path,
    env_value: str,
    frozen_value: bool,
):
    _configure_attempt_storage(monkeypatch, tmp_path)
    ExamAttemptManager.save_attempts([_real_attempt()])

    if env_value:
        monkeypatch.setenv(dev_test_attempts.DEV_TEST_ENV, env_value)
    else:
        monkeypatch.delenv(dev_test_attempts.DEV_TEST_ENV, raising=False)
    monkeypatch.setattr(dev_test_attempts.sys, "frozen", frozen_value, raising=False)
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_ASSETS_ROOT", str(tmp_path / "dev_assets"))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_SEARCH_CACHE_FILE", str(tmp_path / "paper_search_cache.json"))

    attempts = ExamAttemptManager.list_attempts()

    assert [item["attempt_key"] for item in attempts] == ["real-attempt"]


def test_dev_test_attempt_is_injected_by_default_in_source_mode(monkeypatch, tmp_path: Path):
    _configure_attempt_storage(monkeypatch, tmp_path)
    ExamAttemptManager.save_attempts([_real_attempt()])

    local_pdf = tmp_path / "0620_s22_qp_42.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 dev")
    monkeypatch.delenv(dev_test_attempts.DEV_TEST_ENV, raising=False)
    monkeypatch.setattr(dev_test_attempts.sys, "frozen", False, raising=False)
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_LOCAL_QP_PATH", str(local_pdf))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_ASSETS_ROOT", str(tmp_path / "dev_assets"))
    monkeypatch.setattr(dev_test_attempts, "DEV_TEST_SEARCH_CACHE_FILE", str(tmp_path / "paper_search_cache.json"))

    attempts = ExamAttemptManager.list_attempts()

    assert attempts[0]["attempt_key"] == dev_test_attempts.DEV_TEST_ATTEMPT_KEY
    assert attempts[1]["attempt_key"] == "real-attempt"


def test_dev_test_attempt_is_prepended_in_memory_only(monkeypatch, tmp_path: Path):
    _configure_attempt_storage(monkeypatch, tmp_path)
    _configure_dev_helper(monkeypatch, tmp_path)
    ExamAttemptManager.save_attempts([_real_attempt()])

    attempts = ExamAttemptManager.list_attempts()

    assert attempts[0]["attempt_key"] == dev_test_attempts.DEV_TEST_ATTEMPT_KEY
    assert attempts[0]["dev_test_entry"] is True
    assert attempts[1]["attempt_key"] == "real-attempt"

    stored = json.loads(Path(ExamAttemptManager.ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert all(item.get("attempt_key") != dev_test_attempts.DEV_TEST_ATTEMPT_KEY for item in stored)


def test_get_attempt_returns_dev_snapshot(monkeypatch, tmp_path: Path):
    _configure_attempt_storage(monkeypatch, tmp_path)
    local_pdf = _configure_dev_helper(monkeypatch, tmp_path)

    attempt = ExamAttemptManager.get_attempt(dev_test_attempts.DEV_TEST_ATTEMPT_KEY)

    assert isinstance(attempt, dict)
    assert attempt["attempt_key"] == dev_test_attempts.DEV_TEST_ATTEMPT_KEY
    assert attempt["series"] == "MJ"
    assert attempt["pdf_url"] == str(local_pdf.resolve())
    assert attempt["paper_resources"]["mark_scheme"]["url"] == dev_test_attempts.DEV_TEST_REMOTE_MS_URL
    assert attempt["paper_resources"]["grade_threshold"]["url"] == dev_test_attempts.DEV_TEST_REMOTE_GT_URL
    assert attempt["answers"]["1(g)"]["value"] == "Al"
    assert attempt["answers"]["4(c)"]["type"] == "drawing"
    assert Path(attempt["answers"]["4(c)"]["image_path"]).exists()


def test_upsert_dev_attempt_is_noop_and_does_not_write_to_disk(monkeypatch, tmp_path: Path):
    _configure_attempt_storage(monkeypatch, tmp_path)
    _configure_dev_helper(monkeypatch, tmp_path)
    real = _real_attempt()
    ExamAttemptManager.save_attempts([real])

    assert ExamAttemptManager.upsert_attempt(dev_test_attempts.build_dev_test_attempt()) is True

    stored = json.loads(Path(ExamAttemptManager.ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert [item["attempt_key"] for item in stored] == ["real-attempt"]


def test_delete_dev_attempt_is_noop_and_entry_remains_available(monkeypatch, tmp_path: Path):
    _configure_attempt_storage(monkeypatch, tmp_path)
    _configure_dev_helper(monkeypatch, tmp_path)
    real = _real_attempt()
    ExamAttemptManager.save_attempts([real])

    assert ExamAttemptManager.delete_attempt(dev_test_attempts.DEV_TEST_ATTEMPT_KEY) is True

    attempts = ExamAttemptManager.list_attempts()
    assert attempts[0]["attempt_key"] == dev_test_attempts.DEV_TEST_ATTEMPT_KEY
    assert attempts[1]["attempt_key"] == "real-attempt"

    stored = json.loads(Path(ExamAttemptManager.ATTEMPTS_FILE).read_text(encoding="utf-8"))
    assert [item["attempt_key"] for item in stored] == ["real-attempt"]


def test_refresh_history_shows_dev_attempt_before_search_history(monkeypatch, tmp_path: Path):
    _app()
    _configure_attempt_storage(monkeypatch, tmp_path)
    _configure_dev_helper(monkeypatch, tmp_path)
    monkeypatch.setattr(
        HistoryManager,
        "get_history",
        classmethod(
            lambda cls: [
                {
                    "subject_code": "0620",
                    "subject_name": "Chemistry",
                    "series": "MJ",
                    "component": "42",
                    "year": "2022",
                    "timestamp": "2026-03-10 14:35:52",
                }
            ]
        ),
    )

    gui = PastPaperFinderGUI()
    gui.current_level = "IGCSE"
    gui.refresh_history()

    first = gui.history_list.item(0)
    second = gui.history_list.item(1)
    first_payload = first.data(Qt.ItemDataRole.UserRole)
    second_payload = second.data(Qt.ItemDataRole.UserRole)

    assert first_payload["entry_type"] == "resume_attempt"
    assert first_payload["attempt_key"] == dev_test_attempts.DEV_TEST_ATTEMPT_KEY
    assert second_payload["entry_type"] == "search_history"

    first_widget = gui.history_list.itemWidget(first)
    assert first_widget is not None
    labels = [label.text() for label in first_widget.findChildren(type(gui.results_count))]
    assert any("DEV TEST" in text for text in labels)

    gui.close()


def test_continue_saved_exam_attempt_passes_series_and_resources(monkeypatch, tmp_path: Path):
    _app()
    _configure_attempt_storage(monkeypatch, tmp_path)
    _configure_dev_helper(monkeypatch, tmp_path)

    captured: dict = {}

    def _capture_launch(item, resume_snapshot=None, paper_num_override=None, paper_resources=None):
        captured["item"] = dict(item)
        captured["resume_snapshot"] = dict(resume_snapshot or {})
        captured["paper_num_override"] = paper_num_override
        captured["paper_resources"] = dict(paper_resources or {})

    gui = PastPaperFinderGUI()
    monkeypatch.setattr(gui, "launch_exam_mode_for_item", _capture_launch)

    gui.continue_saved_exam_attempt(dev_test_attempts.DEV_TEST_ATTEMPT_KEY)

    assert captured["item"]["series"] == "MJ"
    assert captured["paper_num_override"] == "4"
    assert captured["resume_snapshot"]["attempt_key"] == dev_test_attempts.DEV_TEST_ATTEMPT_KEY
    assert captured["paper_resources"]["mark_scheme"]["url"] == dev_test_attempts.DEV_TEST_REMOTE_MS_URL

    gui.close()
