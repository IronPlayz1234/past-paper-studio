"""Launch-path regressions: cancellation, progress disposal and resize reentrancy."""
import time
import threading
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QProgressDialog
from Core.background_tasks import run_io
from Core import pdf_service
from Tests.test_exam_rendering_stability import wait_for

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def pump(app, milliseconds=80):
    loop=QEventLoop();QTimer.singleShot(milliseconds,loop.quit);loop.exec()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_successful_download_wait_does_not_cancel_or_reopen_disposed_dialog(app):
    parent=QWidget();parent.show()
    cancelled=threading.Event()
    try:
        assert run_io(lambda:(time.sleep(.25),42)[1],cancel=cancelled.set)==42
        assert not cancelled.is_set()
        pump(app)
        assert not [w for w in app.topLevelWidgets() if isinstance(w,QProgressDialog) and w.isVisible()]
    finally:
        parent.close();parent.deleteLater()


def test_user_cancel_stays_responsive_and_does_not_reopen_after_completion(app):
    parent=QWidget();parent.show()
    cancelled=threading.Event()
    def cancel_visible_dialog():
        for widget in app.topLevelWidgets():
            if isinstance(widget,QProgressDialog) and widget.isVisible():
                # Closing via the window button follows Qt's real cancellation path.
                widget.close()
    def work():
        while not cancelled.wait(.01):
            pass
        time.sleep(.05)
        return 'cancelled'
    QTimer.singleShot(300,cancel_visible_dialog)
    try:
        assert run_io(work,cancel=cancelled.set,wait_timeout=2)=='cancelled'
        assert cancelled.is_set()
        pump(app)
        assert not [w for w in app.topLevelWidgets() if isinstance(w,QProgressDialog) and w.isVisible()]
    finally:
        parent.close();parent.deleteLater()


def test_pdf_page_geometry_does_not_enter_nested_loading_loop(app,tmp_path,monkeypatch):
    import fitz
    paper=tmp_path/'0620_s24_qp_11.pdf'
    with fitz.open() as native:
        native.new_page(width=600,height=800);native.save(paper)
    with pdf_service.open(paper) as doc:
        monkeypatch.setattr(pdf_service,'_request',lambda *a:pytest.fail('geometry triggered another loading loop'))
        for _ in range(20):
            assert doc[0].rect.width==600
            assert doc[0].rect.height==800


def test_full_exam_window_opens_and_survives_resizes(app,tmp_path,monkeypatch):
    import fitz
    import Core.exam_mode as exam
    import Core.gui_main as gui
    paper=tmp_path/'0620_s24_qp_11.pdf'
    with fitz.open() as native:
        page=native.new_page(width=600,height=800)
        page.insert_text((72,72),'Chemistry Paper 1. Time allowed: 45 minutes.')
        native.save(paper)
    monkeypatch.setattr(gui.PastPaperFinderGUI,'_show_groq_startup_warning_if_needed',lambda self:None)
    monkeypatch.setattr(exam.ExamModeWindow,'_show_groq_startup_warning_if_needed',lambda self:None)
    monkeypatch.setattr(exam.ExamModeWindow,'_prefetch_mark_scheme_in_background',lambda self:None)
    dashboard=gui.PastPaperFinderGUI();dashboard.show()
    errors=[];monkeypatch.setattr(exam,'show_error',lambda *a:errors.append(a))
    window=None
    try:
        window=exam.launch_exam_mode(dashboard,'0620','Chemistry','1','2024',pdf_url=str(paper),session_mode='practice')
        for width in (1100,1200,1300):
            window.resize(width,800);pump(app)
        assert window.isVisible() and not dashboard.isVisible() and not dashboard.isEnabled()
        assert window.pdf_viewer.page_count==1
        assert not errors
    finally:
        if window:
            window._allow_resume_autosave=False
            window.graceful_exit();pump(app,250)
        wait_for(app,lambda:dashboard.isVisible() and dashboard.isEnabled())
        dashboard._graceful_exit_finalizing=True;dashboard.close();dashboard.deleteLater();pump(app,250)


def test_dashboard_launch_with_download_keeps_exam_open(app,tmp_path,monkeypatch):
    import fitz
    import Core.exam_mode as exam
    import Core.gui_main as gui
    from Core import download_service
    paper=tmp_path/'0620_s24_qp_11.pdf'
    with fitz.open() as native:
        page=native.new_page(width=600,height=800)
        page.insert_text((72,72),'Chemistry Paper 1. Time allowed: 45 minutes.')
        native.save(paper)
    data=paper.read_bytes()
    class Response:
        status_code=200
        headers={'Content-Type':'application/pdf','Content-Length':str(len(data))}
        def iter_content(self,chunk_size):
            time.sleep(.25)  # Exercise the visible cancel-enabled progress dialog.
            yield data
        def close(self):
            pass
    monkeypatch.setattr(download_service.requests,'get',lambda *a,**kw:Response())
    monkeypatch.setattr(gui.PastPaperFinderGUI,'_show_groq_startup_warning_if_needed',lambda self:None)
    monkeypatch.setattr(exam.ExamModeWindow,'_show_groq_startup_warning_if_needed',lambda self:None)
    monkeypatch.setattr(exam.ExamModeWindow,'_prefetch_mark_scheme_in_background',lambda self:None)
    monkeypatch.setattr(gui.PastPaperFinderGUI,'_should_gate_exam_mode_preflight',lambda *a:False)
    errors=[]
    monkeypatch.setattr(gui,'show_error',lambda *a:errors.append(a))
    monkeypatch.setattr(exam,'show_error',lambda *a:errors.append(a))
    dashboard=gui.PastPaperFinderGUI();dashboard.show()
    try:
        dashboard._launch_exam_mode_for_item_impl({'subject_code':'0620','subject':'Chemistry','component':'11','year':'2024','series':'MJ','direct_url':'https://example.test/0620_s24_qp_11.pdf'},session_mode_override='practice')
        pump(app,350)
        windows=[w for w in app.topLevelWidgets() if isinstance(w,exam.ExamModeWindow)]
        assert len(windows)==1 and windows[0].isVisible() and not dashboard.isVisible() and not dashboard.isEnabled()
        assert windows[0].pdf_viewer.page_count==1 and not errors
        assert not [w for w in app.topLevelWidgets() if isinstance(w,QProgressDialog) and w.isVisible()]
    finally:
        for window in app.topLevelWidgets():
            if isinstance(window,exam.ExamModeWindow):
                window._allow_resume_autosave=False
                window.graceful_exit()
        pump(app,350)
        wait_for(app,lambda:dashboard.isVisible() and dashboard.isEnabled())
        dashboard._graceful_exit_finalizing=True;dashboard.close();dashboard.deleteLater();pump(app,250)


def test_deleted_progress_dialog_does_not_leak_busy_scope(app):
    from Core.background_tasks import gui_work_pending
    from shiboken6 import isValid
    deleted = []
    def dispose_dialog():
        for dialog in app.topLevelWidgets():
            if isinstance(dialog, QProgressDialog):
                deleted.append(dialog)
                dialog.deleteLater()
    QTimer.singleShot(60, dispose_dialog)
    assert run_io(lambda: (time.sleep(.15), 42)[1]) == 42
    pump(app)
    assert deleted and all(not isValid(dialog) for dialog in deleted)
    assert not gui_work_pending()
