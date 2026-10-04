"""Home routing, shared history migration, flags and truthful mode-specific stats."""
import json
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QPushButton, QBoxLayout
from Core.study_history import StudyHistory, metadata, summary
from Core.gui_main import PastPaperFinderGUI
from Utils.gui_utils import ExamAttemptManager, HistoryManager, ConfigManager
from UI.localization import get_locale_manager, tr
from UI.theme import get_theme_manager
from UI.study_dashboard import greeting
from Tests.test_exam_rendering_stability import app, paper, window, pump, wait_for
from Tests.test_gui_dashboard_controls import _sample_group_with_audio


def snapshot(identity='one', mode='practice', **extra):
    return dict(attempt_key='paper-'+identity, study_attempt_id=identity,
        paper_code='0620_s24_qp_42', subject_code='0620', subject_name='Chemistry',
        paper_num='42', series='MJ', year='2024', pdf_url='/missing/0620_s24_qp_42.pdf',
        remaining_seconds=1500, saved_at='2026-10-04T09:30:00', first_saved_at='2026-10-04T09:00:00',
        question_ids=['1a','1b','2a'], answers={'1a':{'type':'text','value':'Student answer'}},
        workspace=dict(mode=mode,elapsed_seconds=1200,flagged_questions=['1b']), **extra)


@pytest.fixture
def study_store(tmp_path, monkeypatch):
    monkeypatch.setattr(StudyHistory, 'INDEX_FILE', str(tmp_path/'study_history.json'))
    monkeypatch.setattr(StudyHistory, 'COMPLETED_ROOT', str(tmp_path/'completed_attempts'))
    monkeypatch.setattr(StudyHistory, '_cache', None)
    monkeypatch.setattr(StudyHistory, '_signature', None)
    monkeypatch.setattr(ExamAttemptManager, 'ATTEMPTS_FILE', str(tmp_path/'unfinished.json'))
    monkeypatch.setattr(ExamAttemptManager, 'ATTEMPTS_BACKUP_FILE', str(tmp_path/'unfinished.backup.json'))
    monkeypatch.setattr(ExamAttemptManager, 'ATTEMPT_ASSETS_ROOT', str(tmp_path/'assets'))
    monkeypatch.setattr(HistoryManager, 'HISTORY_FILE', str(tmp_path/'search_history.json'))
    yield tmp_path


@pytest.fixture
def main(app, study_store, monkeypatch):
    monkeypatch.setattr(PastPaperFinderGUI, '_show_groq_startup_warning_if_needed', lambda self: None)
    monkeypatch.setattr(PastPaperFinderGUI, '_maybe_show_onboarding_dialog', lambda self: None)
    get_locale_manager(app).set_language('en_US')
    gui = PastPaperFinderGUI(); gui.resize(1440,900); gui.show()
    wait_for(app, lambda: gui._dashboard._future is None)
    pump(app,.12)
    yield gui
    get_locale_manager(app).set_language('en_US')
    gui._graceful_exit_finalizing = True; gui.close(); gui.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_imports_legacy_saves_once_and_keeps_original_answers(study_store, monkeypatch):
    practice = snapshot(); practice.pop('study_attempt_id')
    assert ExamAttemptManager.upsert_attempt(practice)
    completed = snapshot('two','exam'); completed.pop('study_attempt_id')
    completed['completed_attempt_id'] = 'completed-two'
    path = Path(StudyHistory.COMPLETED_ROOT)/'paper'/'two'/'attempt.json'
    path.parent.mkdir(parents=True); path.write_text(json.dumps(completed))
    original = path.read_bytes()
    records = StudyHistory.records()
    assert len(records) == 2
    stats = summary(records)
    assert stats['practiced'] == 1 and stats['attempted'] == 1
    assert len(stats['flagged']) == 1 and len(stats['resumable']) == 1
    monkeypatch.setattr(Path,'glob', lambda *a: pytest.fail('Metadata refresh rescanned completed saves'))
    StudyHistory._cache = None
    assert len(StudyHistory.records()) == 2
    assert path.read_bytes() == original
    assert ExamAttemptManager.get_attempt('paper-one')['answers'] == practice['answers']


def test_unique_flags_attempt_counts_and_restart_persistence(study_store):
    for identity, mode in [('a','practice'),('b','practice'),('c','exam')]:
        StudyHistory.record(snapshot(identity,mode),'completed')
    StudyHistory.record(snapshot('a','practice'),'completed')
    records = StudyHistory.records()
    assert len(records) == 3
    assert summary(records)['practiced'] == 2 and summary(records)['attempted'] == 1
    assert len(summary(records)['flagged']) == 1
    assert summary(records)['flagged']['0620|MJ|2024|42']['questions'] == {'1b'}
    StudyHistory._cache = None; StudyHistory._signature = None
    assert StudyHistory.records() == records


def test_practice_after_duration_remains_resumable_without_resetting_exam(study_store):
    practice = snapshot(); practice['remaining_seconds'] = 0
    practice['workspace']['elapsed_seconds'] = 6000
    assert ExamAttemptManager.upsert_attempt(practice)
    expired = snapshot('expired','exam'); expired['remaining_seconds'] = 0
    assert not ExamAttemptManager.upsert_attempt(expired)
    row = StudyHistory.records()[0]
    assert row['elapsed_seconds'] == 6000 and row['resume_key'] == 'paper-one'
    assert row['remaining_seconds'] == 0


def test_unknown_or_invalid_grade_is_not_invented(study_store):
    value = snapshot()
    assert 'score' not in metadata(value)
    value['grading_summary'] = dict(earned_marks=float('nan'), total_marks=80)
    assert 'score' not in metadata(value)
    value['grading_summary'] = dict(earned_marks=62,total_marks=80,pending_manual_count=2)
    row = metadata(value)
    assert row['score'] == [62,80] and row['score_provisional']


def test_corrupt_index_recovers_last_good_backup(study_store):
    StudyHistory.record(snapshot('one'),'completed')
    StudyHistory.record(snapshot('two'),'completed')
    Path(StudyHistory.INDEX_FILE).write_text('bad JSON')
    StudyHistory._cache = None
    records = StudyHistory.records()
    assert records and records[0]['id'] == 'one'


def test_fresh_dashboard_results_and_clear_states(main, app):
    dashboard = main._dashboard
    assert dashboard.stack.currentWidget() is dashboard.home
    texts = [label.text() for label in dashboard.home.findChildren(QLabel)]
    assert 'No activity yet' in texts and 'No Results' not in texts
    assert not dashboard.home.findChildren(QPushButton,'dashboardMetric')
    main.display_results([_sample_group_with_audio()],record_history=False); pump(app)
    assert dashboard.stack.currentWidget() is main.results_scroll
    dashboard.show_home(); assert dashboard.stack.currentWidget() is dashboard.home
    assert main.search_results
    dashboard.show_results(); assert dashboard.stack.currentWidget() is main.results_scroll
    assert len(main.search_results) == 1
    main._reset_search_results_section('Search cancelled')
    assert dashboard.stack.currentWidget() is dashboard.home
    main._reset_search_results_section('No Papers Found')
    assert dashboard.stack.currentWidget() is main.results_scroll


def test_home_survives_theme_and_font_refresh_and_resizes(main, app):
    dashboard = main._dashboard
    StudyHistory.record(snapshot(),'completed'); dashboard.refresh()
    wait_for(app,lambda: dashboard._future is None)
    for theme in ('Crimson Meridian','Coffee Shop','Old Library','Matcha Latte','Violet Afterburn','Solid Teal','OLED Dark','Solid White','OLED Light'):
        get_theme_manager().apply_theme(app,theme); pump(app,.12)
        assert dashboard.stack.currentWidget() is dashboard.home
        assert dashboard.records[0]['id'] == 'one'
    for width in (800,1440):
        main.resize(width,900); pump(app)
        expected = QBoxLayout.Direction.LeftToRight if dashboard.home.viewport().width()>=780 else QBoxLayout.Direction.TopToBottom
        assert dashboard.home._columns.direction() == expected


@pytest.mark.parametrize('language',['en_US','en_GB','es','hi','fr'])
def test_dashboard_strings_localize_and_answers_stay_original(main, app, language):
    dashboard = main._dashboard
    value = snapshot(); StudyHistory.record(value,'completed')
    dashboard.refresh(); wait_for(app,lambda: dashboard._future is None)
    get_locale_manager(app).set_language(language); pump(app)
    labels = [label.text() for label in dashboard.home.findChildren(QLabel)]
    assert tr('Recent Activity') in labels and tr('Flagged Papers') in labels
    metrics = [button.accessibleName() for button in dashboard.home.findChildren(QPushButton, 'dashboardMetric')]
    assert tr('Practiced')+': '+tr('{count} sessions').format(count=1) in metrics
    assert greeting(9) == tr('Good morning')
    assert greeting(14,'Alex') == tr('{greeting}, {name}').format(greeting=tr('Good afternoon'),name='Alex')
    assert value['answers']['1a']['value'] == 'Student answer'


def test_paper_actions_delegate_and_flagged_resume_preserves_timer(main, app, monkeypatch):
    value = snapshot(); assert ExamAttemptManager.upsert_attempt(value)
    dashboard = main._dashboard; dashboard.refresh(); wait_for(app,lambda: dashboard._future is None)
    row = dashboard.records[0]
    launched=[]; looked=[]
    monkeypatch.setattr(main,'launch_exam_mode_for_item',lambda *a,**kw: launched.append((a,kw)))
    monkeypatch.setattr(main,'_open_quick_look_window',lambda item: looked.append(item))
    dashboard.quick_look(row); dashboard.start(row,'practice'); dashboard.start(row,'exam')
    assert looked[0]['type']=='QP'
    assert launched[0][1]['session_mode_override']=='practice'
    assert launched[1][1]['session_mode_override']=='exam'
    dashboard.resume(row,'1b')
    saved=launched[-1][1]['resume_snapshot']
    assert saved['remaining_seconds']==1500 and saved['workspace']['elapsed_seconds']==1200
    assert saved['workspace']['active_question']=='1b'
    dashboard.open_flagged()
    assert dashboard.home.kind=='flagged'
    dashboard.open_paper(row)
    assert dashboard.home.kind=='paper'
    assert any(b.text()=='Resume' for b in dashboard.home.findChildren(QPushButton))


def test_completed_answer_snapshot_is_read_only_and_history_uses_same_record(main, app, study_store):
    value=snapshot(); value['completed_attempt_id']='one'
    path=study_store/'complete.json'; path.write_text(json.dumps(value))
    StudyHistory.record(value,'completed',path)
    dashboard=main._dashboard; dashboard.refresh(); wait_for(app,lambda:dashboard._future is None)
    row=dashboard.records[0]; dashboard.open_attempt(row); dashboard.view_answers(row)
    wait_for(app,lambda:dashboard._future is None)
    assert dashboard.answer_snapshot['answers']==value['answers']
    assert json.loads(path.read_text())==value
    assert any(main.history_list.item(i).data(256).get('entry_type')=='study_attempt'
               for i in range(main.history_list.count()) if isinstance(main.history_list.item(i).data(256),dict))


def test_real_practice_save_and_exam_completion_refresh_home_without_overwriting(main, app, paper, monkeypatch):
    import Core.exam_mode as exam
    monkeypatch.setattr(exam.ExamModeWindow,'_show_groq_startup_warning_if_needed',lambda self:None)
    monkeypatch.setattr(exam.ExamModeWindow,'_prefetch_mark_scheme_in_background',lambda self:None)
    def structure(self):
        ids=['1a','1b']; self.question_items=self._build_items_from_ids(ids)
        return ids,{qid:2.0 for qid in ids}
    monkeypatch.setattr(exam.ExamModeWindow,'_build_ai_question_structure',structure)
    first=exam.launch_exam_mode(main,'0620','Chemistry','42','2024',pdf_url=str(paper),session_mode='practice',manual_grading_only=True)
    pump(app)
    first.session_state.elapsed_seconds=6000
    first.session_state.flagged_questions.add('1b')
    key=first._attempt_key
    assert first._save_unfinished_attempt(notify_on_failure=False)
    first.graceful_exit(); wait_for(app,lambda:main.isVisible() and main.isEnabled())
    wait_for(app,lambda:main._dashboard._future is None)
    assert len(summary(main._dashboard.records)['flagged'])==1
    second=exam.launch_exam_mode(main,'0620','Chemistry','42','2024',pdf_url=str(paper),session_mode='exam',manual_grading_only=True)
    assert second._attempt_key!=key
    assert second.complete_workspace_attempt()
    panel=second._ensure_manual_grading_panel()
    rows=second._build_manual_grade_rows()
    second.manual_rows_snapshot=rows
    panel.set_rows(rows)
    for entry in panel.mark_inputs.values(): entry.setText('1')
    second._finalize_manual_grade()
    completed=json.loads(Path(second._completed_attempt_path).read_text())
    assert completed['grading_summary']['earned_marks']==len(rows)
    assert completed['grading_summary']['pending_manual_count']==0
    second.graceful_exit(); wait_for(app,lambda:main.isVisible() and main.isEnabled())
    wait_for(app,lambda:main._dashboard._future is None)
    stats=summary(main._dashboard.records)
    assert stats['practiced']==1 and stats['attempted']==1
    assert len(stats['resumable'])==1
    assert ExamAttemptManager.get_attempt(key)['workspace']['elapsed_seconds']>=6000
    assert main._dashboard.stack.currentWidget() is main._dashboard.home


def test_expired_legacy_answers_and_flags_survive_history_and_later_saves(study_store):
    expired=snapshot('expired','exam'); expired['remaining_seconds']=0
    assert ExamAttemptManager.save_attempts([expired])
    assert all(row.get('attempt_key')!='paper-expired' for row in ExamAttemptManager.list_attempts())
    assert ExamAttemptManager.upsert_attempt(snapshot('new','practice'))
    records=StudyHistory.records()
    row=next(row for row in records if row['id']=='expired')
    assert row['status']=='abandoned' and not row['resume_key']
    assert row['flagged_questions']==['1b']
    assert StudyHistory.read_attempt(row)['answers']==expired['answers']
    assert ExamAttemptManager.delete_attempt('paper-new')
    assert StudyHistory.read_attempt(row)['answers']==expired['answers']


def test_background_refresh_cannot_downgrade_a_concurrent_completion(study_store, monkeypatch):
    stale=snapshot()
    completed=snapshot()
    completed['grading_summary']=dict(earned_marks=3,total_marks=4,pending_manual_count=0)
    path=study_store/'completed.json';path.write_text(json.dumps(completed))
    def read_before_completion():
        StudyHistory.record(completed,'completed',path)
        return [stale]
    monkeypatch.setattr(ExamAttemptManager,'load_attempts',read_before_completion)
    row=StudyHistory.records()[0]
    assert row['status']=='completed' and row['source_path']==str(path)
    assert row['score']==[3,4] and not row['resume_key']
    StudyHistory.record(stale,'saved')
    assert StudyHistory.records()[0]['status']=='completed'


def test_dashboard_retains_results_scroll_and_recent_title_opens_attempt(main, app):
    from copy import deepcopy
    groups=[]
    for i in range(12):
        group=deepcopy(_sample_group_with_audio())
        group.year=str(2000+i)
        group.primary_docs['QP'].url=f'https://example.test/0625_s{i:02}_qp_41.pdf'
        groups.append(group)
    main.display_results(groups,record_history=False)
    pump(app)
    scroll=main.results_scroll.verticalScrollBar()
    scroll.setValue(scroll.maximum()//2)
    position=scroll.value()
    assert position>0, (main.results_scroll.size(), main.results_scroll.viewport().size(),
        main.results_container.size(), main.results_container.minimumSizeHint(),
        main.results_container_layout.count(), main._results_view_mode,
        main._dashboard.stack.currentWidget() is main.results_scroll)
    main._dashboard.show_home();main._dashboard.show_results();pump(app)
    assert scroll.value()==position
    StudyHistory.record(snapshot(),'completed')
    main._dashboard.refresh();wait_for(app,lambda:main._dashboard._future is None)
    main._dashboard.show_home()
    title=main._dashboard.home.findChild(QPushButton,'dashboardPaperTitle')
    title.click()
    assert main._dashboard.home.kind=='attempt'
