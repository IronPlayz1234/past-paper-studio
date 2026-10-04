"""Regression checks for lazy answer retention and portable workspace metadata."""
from pathlib import Path
import pytest
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from Core.exam_session import ExamSessionState
from Core.exam_mode import ExamModeWindow, MathQuestionnaire
from Utils.question_id_mapper import QuestionLeaf


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_session_flags_mode_and_timing_survive_resume():
    state = ExamSessionState(mode='practice', elapsed_seconds=5401,
        active_question='2(a)(ii)', flagged_questions={'1(a)','2(a)(ii)'},
        assisted=True, pause_count=2)
    resumed = ExamSessionState.restore({'workspace': state.snapshot()})
    assert resumed == state
    resumed.flagged_questions.add('3')
    assert '3' not in state.flagged_questions


@pytest.mark.parametrize('snapshot', [None, {}, {'workspace':None}, {'workspace':{'elapsed_seconds':'invalid','flagged_questions':None}}])
def test_old_or_malformed_snapshot_uses_safe_exam_defaults(snapshot):
    restored = ExamSessionState.restore(snapshot)
    assert restored.mode == 'exam'
    assert restored.elapsed_seconds == 0
    assert restored.flagged_questions == set()


@pytest.mark.parametrize('mode,workspace,expected_elapsed', [
    ('exam', None, 600),
    ('exam', {'elapsed_seconds': 650}, 650),
    ('practice', None, 0),
])
def test_resume_migrates_legacy_countdown_without_overwriting_new_elapsed(mode, workspace, expected_elapsed):
    from types import SimpleNamespace
    snapshot = {'remaining_seconds': 3000, 'workspace': workspace}
    window = SimpleNamespace(
        resume_snapshot=snapshot, remaining_seconds=3600, duration=60,
        session_state=ExamSessionState.restore(snapshot, mode),
        questionnaire=None, optional_selectors={}, notes_widget=None, is_listening=False,
        _update_timer_label=lambda: None,
        _extract_notes_text_from_snapshot=lambda value: '',
    )
    ExamModeWindow._apply_resume_snapshot(window)
    assert window.remaining_seconds == 3000
    assert window.session_state.elapsed_seconds == expected_elapsed


def test_lazy_editors_preserve_unvisited_text_table_objective_and_drawing(app, tmp_path):
    drawing = tmp_path/'saved.png'
    image=QImage(64,64,QImage.Format.Format_RGB32);image.fill(QColor('white'));image.save(str(drawing))
    leaves=[
        QuestionLeaf(canonical_id='1',display_id='1',main=1,response_type='text'),
        QuestionLeaf(canonical_id='2',display_id='2',main=2,response_type='table', table_spec={
            'rows':1,'cols':1,'cells':[{'row':0,'col':0,'is_answer':True,'text':'','input_kind':'text'}]}),
        QuestionLeaf(canonical_id='3',display_id='3',main=3,response_type='drawing'),
        QuestionLeaf(canonical_id='4',display_id='4',main=4,response_type='text',section_type='objective'),
    ]
    widget=MathQuestionnaire(question_items=leaves,lazy_workspace=True,drawing_session_dir=str(tmp_path/'session'))
    payload={
        '1':{'type':'text','value':'x^{10} + y_{2}'},
        '2':{'type':'table','cells':{'0,0':'42'},'value':'R1C1=42'},
        '3':{'type':'drawing','image_path':str(drawing),'notes':'Apparatus'},
        '4':{'type':'text','value':'B'},
    }
    widget.apply_saved_answers(payload)
    assert not widget.question_widgets
    assert widget.get_answers()==payload
    widget.ensure_question_widget('1')
    assert len(widget.question_widgets)==1
    assert widget.answers['1'].to_caret_text()=='x^{10} + y_{2}'
    widget.answers['1'].setPlainText('Updated explanation')
    assert widget.get_answers()['2']==payload['2']
    assert widget.get_answers()['3']==payload['3']
    widget.ensure_question_widget('2')
    assert widget.table_inputs['2'].get_cell_answers()=={'0,0':'42'}
    widget.ensure_question_widget('3')
    assert Path(widget.drawing_paths['3']).is_file()
    assert widget.drawing_paths['3']!=str(drawing)
    widget.ensure_question_widget('4')
    assert widget.objective_inputs['4'].currentText()=='B'
    assert widget.get_answers()['1']['value']=='Updated explanation'
    widget.deleteLater()
