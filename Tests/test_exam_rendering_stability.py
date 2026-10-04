"""Real Qt/PDF regression coverage for rendering and independent tool transforms."""
import time
from pathlib import Path
import pytest
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from Core import pdf_service
import Core.exam_mode as exam
from UI.document_protractor import DocumentProtractor
from UI.drawing_document import PROJECT_KEY, decode_project


@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    pdf_service.shutdown_pdf_service()


def pump(app, seconds=.08):
    stop = time.monotonic()+seconds
    while time.monotonic()<stop:
        app.processEvents()
        time.sleep(.003)


def wait_for(app, predicate, seconds=5):
    stop = time.monotonic()+seconds
    while not predicate() and time.monotonic()<stop:
        pump(app,.02)
    assert predicate()


@pytest.fixture
def paper(tmp_path):
    import fitz
    path = tmp_path/'0620_s24_qp_42.pdf'
    with fitz.open() as document:
        for i in range(4):
            page = document.new_page(width=600,height=800)
            page.insert_text((50,60),f'Chemistry question {i+1}: Ca(OH)2 + H2. Explain the diagram.',fontsize=11)
            page.insert_text((50,90),'Small equations and diagram labels must remain readable.',fontsize=5)
            page.draw_rect(fitz.Rect(100,130,220,250))
        document.save(path)
    return path


@pytest.fixture
def viewer(app,paper,monkeypatch):
    errors=[]
    monkeypatch.setattr(exam,'show_error',lambda *args:errors.append(args))
    value=exam.PDFViewer();value.resize(900,640);value.show()
    assert value.load_pdf(str(paper))
    yield value
    value.release_resources();value.close();value.deleteLater();pump(app)
    assert not errors


@pytest.fixture
def window(app,paper,monkeypatch):
    errors=[]
    monkeypatch.setattr(exam,'show_error',lambda *args:errors.append(args))
    monkeypatch.setattr(exam.ExamModeWindow,'_show_groq_startup_warning_if_needed',lambda self:None)
    monkeypatch.setattr(exam.ExamModeWindow,'_prefetch_mark_scheme_in_background',lambda self:None)
    def structure(self):
        ids=['1a','1b','2a']
        self.question_items=self._build_items_from_ids(ids)
        self.question_texts={q:'Explain the diagram.' for q in ids}
        for i,item in enumerate(self.question_items):
            item.page=i+1
        item=self.question_items[-1];item.response_type='drawing'
        item.drawing_reference_path=dict(pdf_path=str(paper),page_index=2,clip=[0,0,600,800])
        return ids,{q:2.0 for q in ids}
    monkeypatch.setattr(exam.ExamModeWindow,'_build_ai_question_structure',structure)
    value=exam.ExamModeWindow(None,'0620','Chemistry','42','2024',series='MJ',
        pdf_url=str(paper),manual_grading_only=True,session_mode='practice')
    value.resize(1440,900);value.show();pump(app,.2)
    yield value
    value._allow_resume_autosave=False;value._stop_autosave_timers();value.graceful_exit();pump(app,.2)
    assert not errors


@pytest.mark.parametrize('width',[800,1050,1440,1920])
def test_timer_and_pause_button_do_not_shift(window,app,width):
    window.resize(width,900);pump(app)
    timer_x=window.timer_label.mapTo(window,QPoint(0,0)).x()
    button_rect=window.pause_btn.geometry()
    for _ in range(2):
        window.toggle_pause();pump(app)
        assert window.timer_label.mapTo(window,QPoint(0,0)).x()==timer_x
        assert window.pause_btn.geometry()==button_rect
    timer_center=timer_x+window.timer_label.width()/2
    assert abs(timer_center-window._studio_workspace.header.width()/2)<=15


def test_tools_keep_screen_size_and_position_at_all_zooms(viewer,app):
    tool=DocumentProtractor(viewer);tool.show();tool.move(45,60);tool.angle=37
    viewer._document_protractor=tool
    viewer.set_movable_ruler_enabled(True)
    geometry=tool.geometry();length=viewer._ruler_state.length_px
    for zoom in (.59, .95, 1.5, 2.49, 4.0, .25):
        viewer._apply_zoom_factor(zoom)
        assert tool.geometry()==geometry and tool.angle==37
        assert viewer._ruler_state.length_px==length
        assert viewer._ruler_state.pixels_per_mm==pytest.approx(72/25.4*zoom)
    wait_for(app,lambda:viewer._sharp_zoom==.25)


def test_rapid_zoom_is_bounded_and_finishes_at_newest_request(viewer,app):
    for _ in range(15):
        for zoom in (.95,.59,2.49,10,.25,1.5):
            viewer._apply_zoom_factor(zoom)
    wait_for(app,lambda:viewer._sharp_zoom==1.5 and viewer._sharp_revision==viewer._render_revision)
    assert viewer.zoom_factor==1.5
    assert viewer.image_label.width()==900
    assert viewer._sharp_pixmap.width()*viewer._sharp_pixmap.height()<=12_020_000
    assert viewer._render_cache_bytes<=48*1024*1024


def test_stale_render_cannot_commit_after_zoom_returns_to_same_value(viewer,app,monkeypatch):
    original=pdf_service.Page.get_pixmap
    viewer._render_cache.clear();viewer._render_cache_bytes=0
    captured=[]
    def render(page,**kwargs):
        result=original(page,**kwargs)
        if not captured:
            captured.append(True)
            viewer._apply_zoom_factor(.59)
            viewer._apply_zoom_factor(1.5)
        return result
    monkeypatch.setattr(pdf_service.Page,'get_pixmap',render)
    prior_revision=viewer._sharp_revision
    viewer.zoom_factor=1.5;viewer._render_pixmap_page()
    assert viewer._sharp_revision==prior_revision
    wait_for(app,lambda:viewer._sharp_zoom==1.5 and viewer._sharp_revision==viewer._render_revision)


@pytest.mark.parametrize('requested,expected',[(.01,.25),(8,4),('invalid',1),(float('nan'),1),(float('inf'),1)])
def test_zoom_limits(viewer,requested,expected):
    assert viewer._clamp_zoom_factor(requested)==expected


def test_retina_backing_is_sharp_without_changing_logical_page_size(viewer,monkeypatch):
    monkeypatch.setattr(viewer,'devicePixelRatioF',lambda:2.0)
    viewer.zoom_factor=2.5;viewer._render_pixmap_page()
    pixmap=viewer._sharp_pixmap
    assert max(pixmap.width(),pixmap.height())==4000
    assert viewer.image_label.width()==1500 and viewer.image_label.height()==2000
    assert pixmap.devicePixelRatio()==2.0


def test_drawing_document_coordinates_survive_zoom_resize_and_reopen(app,paper,tmp_path):
    canvas=exam.DrawingCanvasWidget();canvas.setMinimumSize(0,0);canvas.resize(900,620)
    canvas.load_reference(dict(pdf_path=str(paper),page_index=2,clip=[0,0,600,800]));canvas.show()
    wait_for(app,lambda:not canvas._document_layer.image.isNull())
    assert max(canvas._document_layer.image.width(),canvas._document_layer.image.height())>=2048
    canvas.set_tool('line');canvas.set_zoom_percent(100)
    start=canvas._image_to_view_point(QPointF(140,200)).toPoint()
    end=canvas._image_to_view_point(QPointF(220,240)).toPoint()
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(canvas,end)
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=end)
    ink=canvas.image.copy();size=canvas.canvas_size
    canvas.set_guide_visible('ruler',True);canvas.set_guide_visible('protractor',True)
    radius=canvas.protractor.radius;length=canvas.ruler.length
    for zoom in (150,250,400,75):
        canvas.set_zoom_percent(zoom)
        canvas.resize(1100,700);pump(app)
        assert canvas.image==ink and canvas.canvas_size==size
        assert canvas.protractor.radius==radius and canvas.ruler.length==length
        point=QPointF(130,200)
        assert (canvas._view_to_image_point(canvas._image_to_view_point(point))-point).manhattanLength()<1e-6
    path=tmp_path/'drawing.png';assert canvas.save_image(str(path))
    exported=QImage(str(path));assert 3840<=max(exported.width(),exported.height())<=4096
    assert exported.width()*exported.height()<=12_020_000
    assert exported.text(PROJECT_KEY) and decode_project(exported)[0]==size
    reopened=exam.DrawingCanvasWidget();reopened.setMinimumSize(0,0);reopened.load_image(str(path))
    assert reopened.canvas_size==size
    assert reopened.image.convertToFormat(ink.format())==ink
    for widget in (canvas,reopened):
        widget.close_document_layer();widget.close();widget.deleteLater()


def test_drawing_guides_drag_and_rotate_in_screen_space_at_high_zoom(app):
    canvas=exam.DrawingCanvasWidget();canvas.setMinimumSize(0,0);canvas.resize(1000,700);canvas.show();pump(app)
    canvas.set_zoom_percent(400);canvas.set_guide_visible('protractor',True)
    canvas.protractor.center=QPointF(400,300)
    before=canvas.image.copy()
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=QPoint(400,300))
    QTest.mouseMove(canvas,QPoint(440,330))
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=QPoint(440,330))
    assert canvas.protractor.center==QPointF(440,330)
    handle=QPoint(440,round(330-canvas.protractor.radius-18))
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=handle)
    QTest.mouseMove(canvas,QPoint(round(440+canvas.protractor.radius+18),330))
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=QPoint(round(440+canvas.protractor.radius+18),330))
    assert canvas.protractor.angle==90
    assert canvas.image==before
    canvas.close();canvas.deleteLater()


def test_mark_scheme_return_restores_question_page_zoom_scroll_and_flags(window,app,paper,tmp_path):
    import shutil
    scheme=tmp_path/'mark_scheme.pdf';shutil.copy2(paper,scheme)
    window.mark_scheme_path=str(scheme)
    workspace=window._studio_workspace;workspace.select_question('1b');workspace.toggle_flag()
    viewer=window.pdf_viewer;viewer._apply_zoom_factor(1.5)
    wait_for(app,lambda:viewer._sharp_zoom==1.5)
    viewer.image_scroll.verticalScrollBar().setValue(250)
    prior=viewer.capture_view_state();active=window.session_state.active_question
    assert window._show_mark_scheme_in_viewer()
    assert workspace.return_to_question.isVisible()
    workspace.return_to_question.click();pump(app)
    assert window._active_pdf_source_key=='question'
    assert viewer.current_page==prior['page'] and viewer.zoom_factor==prior['zoom']
    assert viewer.image_scroll.verticalScrollBar().value()==prior['scroll'][1]
    assert window.session_state.active_question==active and active in window.session_state.flagged_questions
    assert not workspace.source_return_bar.isVisible()
    window.session_state.mode='exam';window.session_state.completed=False;window._set_mark_scheme_unlock(False)
    assert not window._mark_scheme_view_unlocked


def test_drawing_save_returns_to_same_question_and_preserves_exam_state(window,app):
    workspace=window._studio_workspace;workspace.select_question('2a');workspace.toggle_flag()
    window.toggle_pause()
    before=(window.session_state.active_question,window.session_state.pause_count,window.timer_paused,
            set(window.session_state.flagged_questions),window.pdf_viewer.current_page,window.pdf_viewer.zoom_factor)
    def save_dialog():
        dialog=next(widget for widget in QApplication.topLevelWidgets() if isinstance(widget,exam.DrawingEditorDialog))
        dialog.tool_combo.setCurrentIndex(dialog.tool_combo.findText('Rectangle'))
        assert dialog.tool_combo.width()>=dialog.tool_combo.fontMetrics().horizontalAdvance('Rectangle')+40
        painter=QPainter(dialog.canvas.image);painter.setPen(QPen(QColor('red'),3));painter.drawLine(140,200,220,240);painter.end()
        dialog._save_and_close()
    QTimer.singleShot(100,save_dialog)
    window.questionnaire._open_drawing_canvas('2(a)');pump(app)
    after=(window.session_state.active_question,window.session_state.pause_count,window.timer_paused,
           set(window.session_state.flagged_questions),window.pdf_viewer.current_page,window.pdf_viewer.zoom_factor)
    assert after==before
    saved=window.questionnaire.drawing_paths['2(a)'];assert Path(saved).is_file()
    assert not QImage(saved).isNull()


def test_replace_reopens_saved_drawing_and_upload_remains_available(window, app, monkeypatch):
    workspace = window._studio_workspace
    workspace.select_question('2a')
    questionnaire = window.questionnaire
    qid = window.session_state.active_question
    opened, uploaded = [], []
    monkeypatch.setattr(questionnaire, '_open_drawing_canvas', opened.append)
    monkeypatch.setattr(questionnaire, '_upload_drawing', uploaded.append)
    questionnaire.drawing_paths[qid] = ''
    workspace.select_question(qid)
    pump(app)
    button = next(button for button in questionnaire.findChildren(QPushButton)
                  if button.property('drawingActionType') == 'upload' and button.isVisible())
    assert button.text() == 'Upload Image'
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert uploaded == [qid]
    questionnaire.drawing_paths[qid] = 'saved-answer.png'
    workspace.select_question(qid)
    pump(app)
    assert button.text() == 'Replace'
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert opened == [qid]
    assert uploaded == [qid]
