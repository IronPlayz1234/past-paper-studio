import inspect

import pytest

pytest.importorskip("PySide6")

import Core.gui_main as gui_main
from Utils.gui_utils import SubjectDatabase


def test_static_subject_name_overrides_dynamic_title_case(monkeypatch):
    monkeypatch.setattr(SubjectDatabase, "DYNAMIC_IGCSE_SUBJECTS", {"0417": "Ict"}, raising=False)

    subjects = SubjectDatabase.get_all_subjects("IGCSE")
    assert subjects["0417"] == "Information and Communication Technology (ICT)"


def test_history_display_uses_canonical_subject_name():
    src = inspect.getsource(gui_main.PastPaperFinderGUI.refresh_history)
    assert "canonical_subject_name = SubjectDatabase.get_subject_name(subject_code)" in src


def test_history_click_uses_canonical_subject_name():
    src = inspect.getsource(gui_main.PastPaperFinderGUI.on_history_clicked)
    assert "canonical_subject_name = SubjectDatabase.get_subject_name(self.subject_code)" in src
