"""Closing the GUI must work before and after the lazily imported Exam Mode."""
import sys
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication


@pytest.mark.parametrize('exam_loaded,child_accepts_close', [(False,True),(True,True),(True,False)])
def test_exit_resolves_only_loaded_exam_window_class(monkeypatch, exam_loaded, child_accepts_close):
    from Core.gui_main import PastPaperFinderGUI
    app=QApplication.instance() or QApplication([])
    calls=[]
    class ExamWindow:
        def close(self): calls.append('child');return child_accepts_close
    if exam_loaded:
        monkeypatch.setitem(sys.modules,'Core.exam_mode',SimpleNamespace(ExamModeWindow=ExamWindow))
        windows=[object(),ExamWindow()]
    else:
        monkeypatch.delitem(sys.modules,'Core.exam_mode',raising=False)
        windows=[object()]
    monkeypatch.setattr(QApplication,'topLevelWidgets',staticmethod(lambda:windows))
    gui=SimpleNamespace(_graceful_exit_timer=SimpleNamespace(stop=lambda:None),
                        _orphan_search_threads=[],search_thread=None,
                        _close_loading_dialog=lambda:calls.append('cleanup'),
                        _set_search_busy_state=lambda state:None,
                        _release_search_thread=lambda:None,_clear_quick_look_cache=lambda:None)
    assert PastPaperFinderGUI._finalize_graceful_exit_cleanup(gui) is child_accepts_close
    assert ('cleanup' in calls) is child_accepts_close
    assert ('child' in calls) is exam_loaded
    if not exam_loaded: assert 'Core.exam_mode' not in sys.modules
