"""Regression coverage for the Alpha 7.5 audit fixes (no live services)."""
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest

from Grading.safe_math import arithmetic_value
from Grading.ai_grading import MathAnswerParser
from Core import atomic_storage, download_service
from Core.cache_tools import BudgetCache
from Core.exam_mode import ExamModeWindow, MarkSchemeParser, extract_paper_code
from Utils.gui_utils import ConfigManager, HistoryManager, parse_range


@pytest.mark.parametrize('text,value', [('2^3', 8), ('1/4', .25), ('25%', .25), ('√9', 3), ('sqrt(16)',4), ('x=0',0), ('2²+3',7), ('-2^2',-4)])
def test_bounded_arithmetic_accepts_exam_notation(text, value):
    assert arithmetic_value(text) == pytest.approx(value)


@pytest.mark.parametrize('text', ["__import__('os').system('echo unsafe')", "().__class__.__bases__", "open('owned','w')", "[x for x in range(10)]", '9**9**9', '1e999', 'True', '1/0', '2+'*300+'1', 'sqrt(-1)'])
def test_untrusted_arithmetic_is_rejected(text):
    assert MathAnswerParser.extract_number(text) is None


def test_malicious_answer_cannot_create_file(tmp_path):
    target = tmp_path / 'owned'
    assert MathAnswerParser.extract_number(f"__import__('pathlib').Path({str(target)!r}).touch()") is None
    assert not target.exists()


def test_zero_and_blank_answers_have_distinct_meanings():
    assert MathAnswerParser.compare_answers(0, '0')
    assert MathAnswerParser.compare_answers('2^3', '8')
    assert not MathAnswerParser.compare_answers('', '')
    assert not MathAnswerParser.compare_answers('', 0)


@pytest.mark.parametrize('text', ['1-999999999', '21,garbage', '0-9999', '1,,2', '21;../22', '-3', '1-2-3'])
def test_range_parser_rejects_unsafe_or_partial_queries(text):
    assert parse_range(text, minimum=1, maximum=99, max_items=40) == []


def test_range_parser_preserves_descending_and_typo_normalization():
    assert parse_range('2l,2O;21,23-22', minimum=1, maximum=99) == ['21','20','23','22']


@pytest.mark.parametrize('text', ['', '1 A', '1 A\n2 B\n2 C', '1 A\n2 B\n3 D', '1 A questionable explanation\n2 B'])
def test_mcq_key_must_be_complete_and_unambiguous(text):
    with pytest.raises(ValueError):
        MarkSchemeParser.validated_mcq_key(text, {'1', '2'})


@pytest.mark.parametrize('text', ['Question Answer\n1 A\n2 B', '1 A 2 B', 'Question\nAnswer\n1\nA\n2\nB'])
def test_mcq_key_supports_common_pdf_table_layouts(text):
    assert MarkSchemeParser.validated_mcq_key(text, {'1','2'}) == {'1':'A','2':'B'}


def test_windows_and_url_paths_extract_the_same_paper_metadata():
    paths = [r'C:\Users\Student\Downloads\0580_s24_qp_42.pdf', '/tmp/0580_s24_qp_42.pdf', 'https://example.test/0580_s24_qp_42.pdf?download=1']
    parsed = [extract_paper_code(path) for path in paths]
    assert parsed[0] and all(item == parsed[0] for item in parsed)


class Response:
    status_code = 200
    def __init__(self, body=b'%PDF-1.7\ncontent', headers=None, failure=False):
        self.body = body
        self.headers = headers or {}
        self.failure = failure
        self.closed = False
    def iter_content(self, size):
        yield self.body
        if self.failure:
            raise OSError('connection reset')
    def close(self):
        self.closed = True


@pytest.mark.parametrize('response', [Response(b'<html>maintenance</html>'), Response(headers={'Content-Length':'999'}), Response(failure=True), Response(b'')])
def test_failed_download_preserves_existing_file_and_removes_partial(tmp_path, response):
    target = tmp_path / 'paper.pdf'
    target.write_bytes(b'original document')
    with pytest.raises((ValueError, OSError)):
        download_service._download('https://example.test/paper.pdf', target, request=lambda *a, **kw: response)
    assert target.read_bytes() == b'original document'
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_compressed_download_does_not_compare_decoded_size_to_wire_size(tmp_path):
    target = tmp_path/'paper.pdf'
    response = Response(headers={'Content-Encoding':'gzip', 'Content-Length':'7'})
    download_service._download('https://example.test/paper.pdf', target, request=lambda *a, **kw: response)
    assert target.read_bytes().startswith(b'%PDF-')
    assert response.closed


def test_cancelled_download_never_requests_or_publishes(tmp_path):
    cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        download_service._download('https://example.test/paper.pdf', tmp_path/'paper.pdf', cancel=cancel, request=lambda *a, **kw: pytest.fail('request after cancellation'))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('name', ['CON.pdf', r'..\NUL.zip', '../AUX.pdf', 'my:file?.pdf', 'a%2fb.pdf'])
def test_download_names_are_portable_and_cannot_escape_destination(name):
    safe = download_service.safe_filename(name)
    assert safe not in {'CON.pdf', 'NUL.zip', 'AUX.pdf'}
    assert not any(c in safe for c in '/\\:?')


def test_atomic_persistence_keeps_previous_data_on_replace_failure(tmp_path, monkeypatch):
    target = tmp_path/'settings.json'; target.write_text('{"original":true}')
    def fail(*a):
        raise PermissionError('read-only directory')
    monkeypatch.setattr(atomic_storage.os, 'replace', fail)
    with pytest.raises(PermissionError):
        atomic_storage.atomic_write_json(target, {'new':True})
    assert json.loads(target.read_text()) == {'original':True}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('data', [{}, None, 'broken', [None, 17, 'x', {}, {'year':[]} ]])
def test_valid_json_with_invalid_history_shape_is_ignored(tmp_path, monkeypatch, data):
    target = tmp_path/'history.json'; target.write_text(json.dumps(data))
    monkeypatch.setattr(HistoryManager,'HISTORY_FILE',str(target))
    assert HistoryManager.load_history() == []


def test_config_getters_do_not_write_and_return_independent_copies(tmp_path, monkeypatch):
    target = tmp_path/'config.json'; target.write_text('{"ui":{"theme":"Default"}}')
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(target))
    monkeypatch.setattr(ConfigManager, 'save_config', lambda *a: pytest.fail('getter saved config'))
    before = target.stat().st_mtime_ns
    first = ConfigManager.load_config(); first['ui']['theme'] = 'changed'
    assert ConfigManager.get_value('ui.theme') == 'Archive Blue'
    assert target.stat().st_mtime_ns == before


def test_delayed_timer_accounts_for_real_elapsed_time_and_pause(monkeypatch):
    import Core.exam_mode as module
    now = [100.0]; monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    state = SimpleNamespace(remaining_seconds=120, timer_paused=False, _timer_last_monotonic=100.0, _timer_fraction=0.0)
    now[0] = 105.6; ExamModeWindow._sync_exam_clock(state)
    assert state.remaining_seconds == 115
    now[0] = 106.2; ExamModeWindow._sync_exam_clock(state)
    assert state.remaining_seconds == 114
    state.timer_paused = True; now[0] = 200; ExamModeWindow._sync_exam_clock(state)
    assert state.remaining_seconds == 114
    state.timer_paused = False; now[0] = 201; ExamModeWindow._sync_exam_clock(state)
    assert state.remaining_seconds == 113


def test_pixmap_cache_evicts_lru_by_memory_budget():
    cache = BudgetCache(budget=800)
    image = SimpleNamespace(width=lambda:10, height=lambda:10)
    cache['a']=image; cache['b']=image; cache.get('a'); cache['c']=image
    assert list(cache) == ['a','c'] and cache.used == 800
    cache['large'] = SimpleNamespace(width=lambda:100, height=lambda:100)
    assert 'large' not in cache
    cache.clear(); assert cache.used == 0 and not cache.sizes


def test_ai_provider_failure_remains_pending_even_if_answer_matches(monkeypatch):
    from Grading.ai_grading import UnifiedAIGrader
    grader = object.__new__(UnifiedAIGrader)
    grader.config = SimpleNamespace(text_model='test',max_tokens=100,timeout=1)
    monkeypatch.setattr(grader, '_profile_block', lambda *a: '')
    def fail(**kwargs):
        raise OSError('provider unavailable')
    monkeypatch.setattr(grader, '_chat_text', fail)
    result = grader.grade_question('1', 'Define diffusion', 'diffusion', correct_answer='diffusion', max_marks=2)
    assert result.manual_review_required and result.error
    assert result.marks == 0 and result.parse_status == 'pending_manual_review'


def test_incomplete_mcq_key_does_not_lock_answers(monkeypatch):
    import Core.exam_mode as exam
    warning=[]; locked=[]
    monkeypatch.setattr(exam,'show_warning',lambda *a:warning.append(a))
    monkeypatch.setattr(MarkSchemeParser,'extract_text_from_pdf',lambda *a:'1 A')
    state=SimpleNamespace(
        questionnaire=SimpleNamespace(get_answers=lambda:{'1':'A','2':'B'},num_questions=2),
        mark_scheme_path='scheme.pdf', subject_code='0620',paper_num=1,
        _set_grading_status=lambda *a:None,
        grade_status_label=SimpleNamespace(setText=lambda *a:None),
        _lock_submission_and_answers=lambda:locked.append(True),
    )
    ExamModeWindow._auto_grade_mcq(state)
    assert warning and not locked


def test_migration_preserves_originals_and_relocates_drawing_assets(tmp_path, monkeypatch):
    from Core import runtime_paths
    project=tmp_path/'project'; legacy=project/'Core'/'Data'; legacy.mkdir(parents=True)
    asset=legacy/'attempt_assets'/'attempt'/'1.png';asset.parent.mkdir(parents=True);asset.write_bytes(b'image')
    snapshot=legacy/'unfinished_exam_attempts.json'
    snapshot.write_text(json.dumps([{'answers':{'1':{'image_path':str(asset)}}}]))
    source_env=project/'Core'/'.env';source_env.write_text('GROQ_API_KEY=test-not-real\n')
    destination=tmp_path/'user-data'
    monkeypatch.delenv('PAST_PAPER_FINDER_DATA_DIR')
    monkeypatch.setattr(runtime_paths,'_writable_root',lambda **kw:destination)
    monkeypatch.setattr(runtime_paths,'app_base_path',lambda:project)
    runtime_paths.migrate_legacy_data()
    migrated=json.loads((destination/'unfinished_exam_attempts.json').read_text())
    assert Path(migrated[0]['answers']['1']['image_path']).read_bytes()==b'image'
    assert Path(migrated[0]['answers']['1']['image_path']).is_relative_to(destination)
    assert asset.exists() and snapshot.exists() and source_env.exists()
    assert (destination/'settings.env').stat().st_mode & 0o777 == 0o600
    (destination/'settings.env').write_text('already saved\n')
    runtime_paths.migrate_legacy_data()
    assert (destination/'settings.env').read_text() == 'already saved\n'


def test_temp_cleanup_never_deletes_user_document(tmp_path):
    user_file=tmp_path/'paper.pdf';user_file.write_bytes(b'original')
    owned=Path(download_service.temp_directory())/'audit_cleanup_test.pdf';owned.write_bytes(b'%PDF-1.7')
    download_service.remove_owned_temporary_file(user_file)
    download_service.remove_owned_temporary_file(owned)
    assert user_file.exists() and not owned.exists()


@pytest.mark.parametrize('raw', ['Could not evaluate the answer.', 'Please see question 7 for details.'])
@pytest.mark.parametrize('drawing', [False, True])
def test_unparseable_ai_reply_is_pending_not_a_guessed_mark(tmp_path, monkeypatch, raw, drawing):
    from Grading.ai_grading import UnifiedAIGrader
    grader=object.__new__(UnifiedAIGrader)
    grader.config=SimpleNamespace(text_model='test',vision_model='test',max_tokens=100,timeout=1)
    monkeypatch.setattr(grader,'_profile_block',lambda *a:'')
    monkeypatch.setattr(grader,'_chat_text',lambda **kw:raw)
    monkeypatch.setattr(grader,'_chat_image',lambda **kw:raw)
    if drawing:
        image=tmp_path/'drawing.png';image.write_bytes(b'image')
        result=grader.grade_drawing('1','Draw a cell','Cell wall labelled',str(image),max_marks=3)
        assert result['manual_review_required'] and result['marks']==0
    else:
        result=grader.grade_question('1','Explain diffusion','diffusion',correct_answer='diffusion',max_marks=3)
        assert result.manual_review_required and result.marks==0
