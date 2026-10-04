"""Real PDF smoke tests exercising process isolation and responsive Qt waits."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from Core import pdf_service
from Core.background_tasks import run_io, await_future


@pytest.fixture(scope='module')
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    pdf_service.shutdown_pdf_service()


@pytest.fixture
def paper(tmp_path):
    import fitz
    path = tmp_path/'0580_s24_qp_42.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=600,height=800)
        page.insert_text((72,72), 'Question 1 Solve x + 1 = 2. [1]')
        doc.save(path)
    return path


def test_pdf_worker_is_separate_and_gui_timer_keeps_ticking(qt_app, paper):
    ticks=[]; timer=QTimer(); timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start(10)
    try:
        worker_pid=pdf_service._request('call',('os','getpid',(),{}))
        assert worker_pid != os.getpid()
        run_io(time.sleep, .12)
        with pdf_service.open(paper) as doc:
            assert len(doc)==1
            assert 'Solve' in doc[0].get_text()
            pix=doc[0].get_pixmap(matrix=pdf_service.Matrix(30,30),alpha=False)
            assert pix.width*pix.height < 8_020_000
            assert len(pix.samples)==pix.stride*pix.height
        assert len(ticks)>=5
    finally:
        timer.stop()


def test_pdf_gui_and_background_requests_share_one_worker(qt_app, paper):
    def read():
        with pdf_service.open(paper) as doc:
            return doc[0].get_text()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(read) for _ in range(2)]
        with pdf_service.open(paper) as doc:
            assert doc[0].rect.height==800
        assert all('Solve' in await_future(f) for f in futures)


def test_failed_pdf_replacement_preserves_current_document(qt_app, paper, tmp_path, monkeypatch):
    import Core.exam_mode as exam
    errors=[];monkeypatch.setattr(exam,'show_error',lambda *args: errors.append(args))
    viewer=exam.PDFViewer()
    viewer.use_pixmap=True
    try:
        assert viewer.load_pdf(str(paper)) is True
        original=viewer.doc
        assert viewer.load_pdf(str(tmp_path/'missing.pdf')) is False
        broken=tmp_path/'broken.pdf';broken.write_bytes(b'not a PDF')
        assert viewer.load_pdf(str(broken)) is False
        assert viewer.doc is original and viewer.pdf_path==str(paper)
        assert viewer.page_count==1 and errors
        assert 'Solve' in viewer.doc[0].get_text()
    finally:
        viewer.release_resources();viewer.close();viewer.deleteLater()


def test_background_wait_keeps_function_timeout_argument(qt_app):
    assert run_io(lambda timeout: timeout, timeout=2, wait_timeout=5)==2
