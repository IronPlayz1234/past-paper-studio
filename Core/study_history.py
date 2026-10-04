"""Lightweight metadata index over the existing unfinished/completed attempt saves.

Answers and drawing assets stay in their original storage. Index migration is
performed by the Dashboard's IO worker once, never by painting or theme changes.
"""
from __future__ import annotations
import copy
import hashlib
import json
import logging
import math
import re
import shutil
import threading
from pathlib import Path
from Core.atomic_storage import atomic_write_json
from Core.runtime_paths import user_data_path


def integer(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def paper_identity(snapshot):
    code = str(snapshot.get('subject_code', ''))
    year = str(snapshot.get('year', ''))
    series = str(snapshot.get('series', '')).upper()
    component = str(snapshot.get('paper_num', snapshot.get('component', '')))
    source = str(snapshot.get('paper_code', '')) + ' ' + str(snapshot.get('pdf_url', ''))
    match = re.search(r'(\d{4})_([smw])(\d{2})_(?:qp|ms|gt)_(\d{1,2})(?!\d)', source, re.I)
    if match:
        code, season, short_year, component = match.groups()
        series = {'s': 'MJ', 'm': 'FM', 'w': 'ON'}[season.lower()]
        year = str(2000 + int(short_year))
    return code, series, year, component


def session_id(snapshot):
    explicit = snapshot.get('study_attempt_id') or snapshot.get('completed_attempt_id')
    if explicit:
        return str(explicit)
    raw = str(snapshot.get('attempt_key', '')) + '|' + str(snapshot.get('first_saved_at', snapshot.get('saved_at', '')))
    return 'legacy-' + hashlib.sha256(raw.encode()).hexdigest()[:24]


def metadata(snapshot, status='saved', source_path=''):
    code, series, year, component = paper_identity(snapshot)
    workspace = snapshot.get('workspace') or {}
    workspace = workspace if isinstance(workspace, dict) else {}
    answers = snapshot.get('answers') or {}
    answers = answers if isinstance(answers, dict) else {}
    answered = 0
    for value in answers.values():
        if isinstance(value, dict):
            cells = value.get('cells') or {}
            cells = cells.values() if isinstance(cells, dict) else []
            populated = value.get('value') or value.get('image_path') or any(v is not None and str(v).strip() for v in cells)
        else:
            populated = str(value or '').strip()
        answered += bool(populated)
    flags = workspace.get('flagged_questions', [])
    flags = sorted({str(q) for q in flags}) if isinstance(flags, (list, set)) else []
    question_ids = snapshot.get('question_ids') or []
    question_count = len(question_ids) if isinstance(question_ids, (list, tuple, set, dict)) else 0
    result = dict(
        id=session_id(snapshot), paper_id='|'.join((code, series, year, component)),
        subject_code=code, subject_name=str(snapshot.get('subject_name') or code),
        series=series, year=year, component=component,
        mode='practice' if workspace.get('mode', snapshot.get('session_mode')) == 'practice' else 'exam',
        status=status, elapsed_seconds=integer(workspace.get('elapsed_seconds')),
        answered_count=answered, question_count=question_count,
        flagged_questions=flags, paper_flagged=bool(snapshot.get('paper_flagged', False)),
        started_at=str(snapshot.get('first_saved_at') or snapshot.get('saved_at') or ''),
        updated_at=str(snapshot.get('completed_at') or snapshot.get('saved_at') or ''),
        pdf_url=str(snapshot.get('pdf_url') or ''), local_pdf_path=str(snapshot.get('local_pdf_path') or ''),
        resume_key=str(snapshot.get('attempt_key') or '') if status == 'saved' else '',
        remaining_seconds=integer(snapshot.get('remaining_seconds')), source_path=str(source_path),
        snapshot_key='',
        paper_resources=snapshot.get('paper_resources') or {},
    )
    grading = snapshot.get('grading_summary')
    if isinstance(grading, dict):
        try:
            earned, total = float(grading['earned_marks']), float(grading['total_marks'])
            if math.isfinite(earned) and math.isfinite(total) and total > 0 and 0 <= earned <= total:
                result['score'] = [earned, total]
                result['score_provisional'] = bool(grading.get('pending_manual_count'))
        except (KeyError, ValueError, TypeError, OverflowError):
            pass
    return result


class StudyHistory:
    INDEX_FILE = user_data_path('study_history.json')
    COMPLETED_ROOT = user_data_path('completed_attempts')
    _lock = threading.RLock()
    _cache = None
    _signature = None

    @classmethod
    def _load(cls):
        path = Path(cls.INDEX_FILE)
        signature = (str(path), path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else (str(path), None)
        if cls._cache is not None and signature == cls._signature:
            return copy.deepcopy(cls._cache)
        payload = None
        for candidate in (path, path.with_suffix('.backup.json')):
            try:
                value = json.loads(candidate.read_text(encoding='utf-8'))
                if isinstance(value, dict) and isinstance(value.get('attempts'), list):
                    value['attempts'] = [row for row in value['attempts'] if isinstance(row, dict) and row.get('id')]
                    payload = value
                    break
            except (OSError, ValueError):
                pass
        if payload is None:
            # Existing completed saves are imported once. The caller runs on IO.
            records = []
            for source in Path(cls.COMPLETED_ROOT).glob('*/*/attempt.json'):
                try:
                    snapshot = json.loads(source.read_text(encoding='utf-8'))
                    if isinstance(snapshot, dict):
                        records.append(metadata(snapshot, 'completed', source))
                except (OSError, ValueError):
                    continue
            payload = {'version': 1, 'attempts': records}
        cls._cache, cls._signature = copy.deepcopy(payload), signature
        return payload

    @classmethod
    def _save(cls, payload):
        path = Path(cls.INDEX_FILE)
        if path.exists():
            # A corrupt primary must never replace a recoverable backup.
            try:
                json.loads(path.read_text(encoding='utf-8'))
                shutil.copy2(path, path.with_suffix('.backup.json'))
            except (OSError, ValueError):
                pass
        atomic_write_json(path, payload)
        cls._cache = copy.deepcopy(payload)
        cls._signature = (str(path), path.stat().st_mtime_ns, path.stat().st_size)

    @classmethod
    def record(cls, snapshot, status='saved', source_path=''):
        try:
            if not snapshot.get('subject_code') or str(snapshot.get('attempt_key', '')).startswith('dev-test'):
                return
            row = metadata(snapshot, status, source_path)
            with cls._lock:
                payload = cls._load()
                old = next((r for r in payload['attempts'] if r.get('id') == row['id']), {})
                if old.get('status') == 'completed' and status != 'completed':
                    return
                # Grading updates and later saves retain previously known fields.
                row = {**old, **row}
                payload['attempts'] = [r for r in payload['attempts'] if r.get('id') != row['id']] + [row]
                cls._save(payload)
        except (OSError, ValueError, TypeError):
            logging.getLogger(__name__).exception('Could not update study history metadata')

    @classmethod
    def records(cls):
        from Utils.gui_utils import ExamAttemptManager
        from Utils.dev_test_attempts import is_dev_test_attempt_entry
        # Lock ordering: read resume storage before taking the index lock.
        unfinished = [s for s in ExamAttemptManager.load_attempts() if not is_dev_test_attempt_entry(s)]
        with cls._lock:
            payload = cls._load()
            by_id = {r['id']: r for r in payload['attempts'] if isinstance(r, dict) and r.get('id')}
            for snapshot in unfinished:
                if ExamAttemptManager._is_valid_entry(snapshot):
                    row = metadata(snapshot)
                    if by_id.get(row['id'], {}).get('status') == 'completed':
                        # A worker may have read the resume file just before the
                        # GUI commits completion. Never downgrade that commit.
                        continue
                    by_id[row['id']] = {**by_id.get(row['id'], {}), **row}
                elif all(snapshot.get(key) for key in ('attempt_key', 'subject_code', 'pdf_url')) and isinstance(snapshot.get('answers'), dict):
                    # Expired legacy Exam saves remain viewable, never resumable.
                    row = metadata(snapshot, 'abandoned')
                    if by_id.get(row['id'], {}).get('status') == 'completed':
                        continue
                    row['snapshot_key'] = str(snapshot['attempt_key'])
                    by_id[row['id']] = {**by_id.get(row['id'], {}), **row}
            active_keys = {str(s.get('attempt_key')) for s in unfinished if ExamAttemptManager._is_valid_entry(s)}
            for row in by_id.values():
                if row.get('status') == 'saved' and row.get('resume_key') not in active_keys:
                    row['resume_key'] = ''
                    row['status'] = 'abandoned'
            normalized = {'version': 1, 'attempts': list(by_id.values())}
            if normalized != payload or not Path(cls.INDEX_FILE).exists():
                cls._save(normalized)
            return sorted(copy.deepcopy(normalized['attempts']), key=lambda r: r.get('updated_at', ''), reverse=True)

    @staticmethod
    def read_attempt(row):
        from Utils.gui_utils import ExamAttemptManager
        if row.get('resume_key'):
            return ExamAttemptManager.get_attempt(row['resume_key'])
        if row.get('snapshot_key'):
            return next((snapshot for snapshot in ExamAttemptManager.load_attempts()
                         if snapshot.get('attempt_key') == row['snapshot_key']), None)
        if row.get('source_path'):
            try:
                value = json.loads(Path(row['source_path']).read_text(encoding='utf-8'))
                return value if isinstance(value, dict) else None
            except (OSError, ValueError):
                pass
        return None


def summary(records):
    flagged = {}
    for row in records:
        if row.get('flagged_questions') or row.get('paper_flagged'):
            group = flagged.setdefault(row['paper_id'], {'paper': row, 'questions': set(), 'attempts': []})
            group['questions'].update(row.get('flagged_questions') or [])
            group['attempts'].append(row)
    return dict(flagged=flagged, practiced=sum(r.get('mode') == 'practice' for r in records),
                attempted=sum(r.get('mode') == 'exam' for r in records),
                resumable=[r for r in records if r.get('status') == 'saved' and r.get('resume_key')])
