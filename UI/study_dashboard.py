"""Native home state over shared attempt metadata; no PDF work during refresh."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Qt, QLocale, QDateTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QHBoxLayout, QBoxLayout, QStackedWidget, QTextBrowser)
from Core.study_history import StudyHistory, summary
from Core.background_tasks import submit_io
from UI.localization import tr, get_locale_manager
from UI.theme import get_theme_manager, ThemeManager
from Utils.gui_utils import Colors, ConfigManager


def greeting(hour=None, name=''):
    hour = datetime.now().hour if hour is None else hour
    source = 'Good morning' if 5 <= hour < 12 else 'Good afternoon' if 12 <= hour < 18 else 'Good evening'
    value = tr(source)
    return tr('{greeting}, {name}').format(greeting=value, name=name) if name else value


def duration(seconds):
    seconds = max(0, int(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def when(value):
    parsed = QDateTime.fromString(str(value), Qt.DateFormat.ISODate)
    return QLocale().toString(parsed, QLocale.FormatType.ShortFormat) if parsed.isValid() else tr('Date unavailable')


def paper_title(row):
    return f"{row.get('subject_name', '')} {row.get('subject_code', '')}/{row.get('component', '')}".strip()


def paper_subtitle(row):
    series = tr({'MJ':'May/June', 'ON':'October/November', 'FM':'February/March'}.get(row.get('series'), 'Series unavailable'))
    return f"{series} {row.get('year', '')}".strip()


def attempt_subtitle(row):
    parts = [tr('Practice' if row.get('mode') == 'practice' else 'Exam'),
             tr({'started':'Started', 'saved':'Saved', 'completed':'Completed', 'abandoned':'Abandoned'}.get(row.get('status'), 'Saved')),
             when(row.get('updated_at'))]
    if row.get('elapsed_seconds'):
        parts.append(tr('Time spent: {time}').format(time=duration(row['elapsed_seconds'])))
    if row.get('score'):
        score, total = row['score']
        parts.append(tr('Score: {score}/{total}').format(score=f'{score:g}', total=f'{total:g}'))
        if row.get('score_provisional'):
            parts.append(tr('Provisional'))
    return ' · '.join(parts)


class StudyDashboard(QScrollArea):
    def __init__(self, controller):
        super().__init__(controller.main.results_panel)
        self.controller = controller
        self.kind = 'home'
        self.selected = None
        self.setObjectName('studyDashboard')
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget(); self.body.setObjectName('dashboardBody')
        self.body.setAutoFillBackground(False)
        self.layout_body = QVBoxLayout(self.body)
        self.layout_body.setContentsMargins(0, 4, 12, 16)
        self.layout_body.setSpacing(16)
        self.setWidget(self.body)
        self._columns = None
        self._metrics = None
        self._action_rows = []
        self.refresh_theme()
        get_theme_manager().theme_changed.connect(self.refresh_theme)
        get_locale_manager().language_changed.connect(self.render)
        from UI.profile_controls import get_profile
        get_profile().changed.connect(self.render)
        self.render()

    def label(self, text, parent=None, *, heading=False, muted=False):
        label = QLabel(text, parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        if heading:
            font = QFont(); font.setPointSize(16); font.setWeight(QFont.Weight.DemiBold)
            label.setFont(font)
        if muted:
            label.setObjectName('dashboardMuted')
        return label

    def button(self, text, callback, parent=None, primary=False):
        button = QPushButton(tr(text), parent)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty('dashboardPrimary', primary)
        button.clicked.connect(lambda _=False: callback())
        return button

    def section(self, title, parent_layout):
        frame = QFrame(); frame.setObjectName('dashboardSection')
        layout = QVBoxLayout(frame); layout.setContentsMargins(16, 14, 16, 14); layout.setSpacing(10)
        layout.addWidget(self.label(tr(title), heading=True))
        parent_layout.addWidget(frame)
        return layout

    def entry(self, row, parent_layout, *, resume=False, flagged_count=None):
        card = QFrame(); card.setObjectName('dashboardEntry')
        self.subject_accent(card, row)
        layout = QVBoxLayout(card); layout.setContentsMargins(12, 10, 12, 10); layout.setSpacing(5)
        open_row = self.controller.open_paper if flagged_count is not None else self.controller.open_attempt
        title = self.button(paper_title(row), lambda: open_row(row))
        title.setProperty('ppsNoTranslation', True); title.setObjectName('dashboardPaperTitle')
        title.setAccessibleName(paper_title(row))
        layout.addWidget(title)
        layout.addWidget(self.label(paper_subtitle(row), muted=True))
        if flagged_count is not None:
            layout.addWidget(self.label(tr('{count} flagged questions').format(count=flagged_count), muted=True))
        else:
            layout.addWidget(self.label(attempt_subtitle(row), muted=True))
        if resume:
            layout.addWidget(self.label(tr('{answered} / {total} answered · {time} elapsed').format(
                answered=row.get('answered_count',0), total=row.get('question_count') or '—', time=duration(row.get('elapsed_seconds'))), muted=True))
            layout.addWidget(self.button('Resume', lambda: self.controller.resume(row)), 0, Qt.AlignmentFlag.AlignRight)
        elif flagged_count is None:
            layout.addWidget(self.button('Open attempt', lambda: self.controller.open_attempt(row)), 0, Qt.AlignmentFlag.AlignRight)
        parent_layout.addWidget(card)

    def render(self, *_):
        scroll = self.verticalScrollBar().value()
        while self.layout_body.count():
            item = self.layout_body.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()
        self._columns = None
        self._metrics = None
        self._action_rows = []
        if self.kind == 'home':
            self.render_home()
        else:
            self.render_detail()
        self.layout_body.addStretch(1)
        self.resize_columns()
        self.verticalScrollBar().setValue(scroll)

    def render_home(self):
        head = QWidget(); layout = QVBoxLayout(head); layout.setContentsMargins(0, 4, 0, 4); layout.setSpacing(5)
        from UI.profile_controls import get_profile
        name = get_profile().name()
        title = self.label(greeting(name=name), heading=True)
        title.setObjectName('dashboardGreeting')
        layout.addWidget(title)
        layout.addWidget(self.label(tr('Pick up where you left off.'), muted=True))
        layout.addWidget(self.button('Back to results', self.controller.show_results), 0, Qt.AlignmentFlag.AlignLeft)
        self.layout_body.addWidget(head)
        records = self.controller.records
        stats = summary(records)
        if not records:
            starter = self.section('No activity yet', self.layout_body)
            starter.addWidget(self.label(tr('Search for a paper to begin.'), muted=True))
            actions = QHBoxLayout(); actions.addWidget(self.button('Search Papers', self.controller.focus_search, primary=True))
            actions.addWidget(self.button('Open Documentation', self.controller.main.open_user_documentation)); actions.addStretch()
            starter.addLayout(actions)
            if self.controller.error:
                starter.addWidget(self.label(tr('Study history could not be loaded. Your saved attempts are unchanged.'), muted=True))
                starter.addWidget(self.button('Retry', self.controller.refresh))
            return
        metrics = QWidget(); grid = QBoxLayout(QBoxLayout.Direction.LeftToRight, metrics)
        self._metrics = grid
        grid.setContentsMargins(0,0,0,0); grid.setSpacing(12)
        for title, count, unit, callback in (
            ('Flagged', len(stats['flagged']), '{count} papers', self.controller.open_flagged),
            ('Practiced', stats['practiced'], '{count} sessions', lambda: self.controller.open_activity('practice')),
            ('Attempted', stats['attempted'], '{count} exams', lambda: self.controller.open_activity('exam'))):
            button = self.button('', callback)
            button.setObjectName('dashboardMetric'); button.setMinimumHeight(114)
            button.setAccessibleName(tr(title)+': '+tr(unit).format(count=count))
            content = QVBoxLayout(button); content.setContentsMargins(16,10,16,10); content.setSpacing(2)
            for value, object_name in ((tr(title).upper(),'metricLabel'),(str(count),'metricValue'),(tr(unit).format(count='').strip(),'metricUnit')):
                label = self.label(value); label.setObjectName(object_name)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                content.addWidget(label)
            grid.addWidget(button, 1)
        self.layout_body.addWidget(metrics)
        columns = QWidget(); self._columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, columns)
        self._columns.setContentsMargins(0,0,0,0); self._columns.setSpacing(16)
        left = QWidget(); right = QWidget()
        recent_layout = QVBoxLayout(left); recent_layout.setContentsMargins(0,0,0,0); recent_layout.setSpacing(12)
        side_layout = QVBoxLayout(right); side_layout.setContentsMargins(0,0,0,0); side_layout.setSpacing(12)
        self._columns.addWidget(left, 3); self._columns.addWidget(right, 2)
        self.layout_body.addWidget(columns)
        recent = self.section('Recent Activity', recent_layout)
        for row in records[:3]:
            self.entry(row, recent)
        recent.addWidget(self.button('View all activity', lambda: self.controller.open_activity(None)))
        if stats['resumable']:
            continued = self.section('Continue where you left off', side_layout)
            for row in stats['resumable'][:2]: self.entry(row, continued, resume=True)
        flagged = self.section('Flagged Papers', side_layout)
        if not stats['flagged']:
            flagged.addWidget(self.label(tr('Flag questions during a session to find them here.'), muted=True))
        else:
            for group in list(stats['flagged'].values())[:2]:
                self.entry(group['paper'], flagged, flagged_count=len(group['questions']))
            flagged.addWidget(self.button('View all flagged papers', self.controller.open_flagged))
        recent_layout.addStretch(); side_layout.addStretch()

    def render_detail(self):
        self.layout_body.addWidget(self.button('Back to Dashboard', self.controller.show_home), 0, Qt.AlignmentFlag.AlignLeft)
        self.layout_body.addWidget(self.button('Back to results', self.controller.show_results), 0, Qt.AlignmentFlag.AlignLeft)
        records = self.controller.records
        row = self.selected or {}
        if self.kind == 'flagged':
            layout = self.section('Flagged Papers', self.layout_body)
            groups = summary(records)['flagged']
            if not groups: layout.addWidget(self.label(tr('No flagged papers yet.'), muted=True))
            for group in groups.values(): self.entry(group['paper'], layout, flagged_count=len(group['questions']))
        elif self.kind == 'activity':
            layout = self.section('Recent Activity', self.layout_body)
            filtered = [r for r in records if not self.selected or r['mode'] == self.selected]
            if not filtered: layout.addWidget(self.label(tr('No activity in this mode yet.'), muted=True))
            for record in filtered: self.entry(record, layout)
        elif self.kind == 'paper':
            layout = self.section('Paper history', self.layout_body)
            layout.addWidget(self.label(paper_title(row), heading=True))
            layout.addWidget(self.label(paper_subtitle(row), muted=True))
            self.paper_actions(row, layout)
            for record in records:
                if record['paper_id'] == row['paper_id']: self.entry(record, layout, resume=bool(record.get('resume_key')))
        elif self.kind == 'attempt':
            layout = self.section('Attempt details', self.layout_body)
            self.subject_accent(layout.parentWidget(), row)
            layout.addWidget(self.label(paper_title(row), heading=True))
            layout.addWidget(self.label(paper_subtitle(row), muted=True))
            layout.addWidget(self.label(attempt_subtitle(row)))
            layout.addWidget(self.label(tr('{answered} / {total} answered').format(answered=row.get('answered_count',0), total=row.get('question_count') or '—')))
            flags = row.get('flagged_questions') or []
            if flags:
                layout.addWidget(self.label(tr('Flagged questions: {questions}').format(questions=', '.join(flags))))
            if row.get('resume_key'):
                layout.addWidget(self.button('Resume', lambda: self.controller.resume(row)))
                if flags: layout.addWidget(self.button('Resume at flagged question', lambda: self.controller.resume(row, flags[0])))
            self.paper_actions(row, layout)
            layout.addWidget(self.button('View saved answers', lambda: self.controller.view_answers(row)))
            if row.get('score'):
                layout.addWidget(self.button('View results', lambda: self.controller.view_answers(row)))
            layout.addWidget(self.button('View paper history', lambda: self.controller.open_paper(row)))
            if self.controller.answer_snapshot is not None:
                snapshot = self.controller.answer_snapshot
                answers = snapshot.get('answers') or {}
                answers = answers if isinstance(answers, dict) else {}
                if not answers: layout.addWidget(self.label(tr('No saved answers are available.'), muted=True))
                for qid, answer in answers.items():
                    layout.addWidget(self.label(tr('Question {qid}').format(qid=qid)))
                    browser = QTextBrowser(); browser.setOpenExternalLinks(False); browser.setMaximumHeight(130)
                    browser.setProperty('ppsNoTranslation', True)
                    if isinstance(answer, dict):
                        value = answer.get('value') or answer.get('notes') or ''
                        if answer.get('type') == 'table':
                            cells = answer.get('cells') or {}
                            value = '\n'.join(f'{k}: {v}' for k,v in cells.items()) if isinstance(cells, dict) else ''
                        browser.setPlainText(str(value))
                        if answer.get('image_path'):
                            # Original image opened only on explicit user action.
                            path = str(answer['image_path'])
                            layout.addWidget(self.button('Open drawing', lambda path=path: self.controller.open_local(path)))
                    else: browser.setPlainText(str(answer))
                    layout.addWidget(browser)
                grading = snapshot.get('grading_summary')
                if grading:
                    layout.addWidget(self.label(tr('Saved grading result'), heading=True))
                    if row.get('score'):
                        score, total = row['score']; layout.addWidget(self.label(tr('Score: {score}/{total}').format(score=f'{score:g}',total=f'{total:g}')))
            elif self.controller.answer_error:
                layout.addWidget(self.label(tr('This attempt has no readable answer snapshot. You can still open the paper or start again.'), muted=True))

    def paper_actions(self, row, layout):
        actions = QWidget(); box = QBoxLayout(QBoxLayout.Direction.TopToBottom, actions); box.setContentsMargins(0,0,0,0); box.setSpacing(6)
        self._action_rows.append(box)
        box.addWidget(self.button('Quick Look', lambda: self.controller.quick_look(row)))
        box.addWidget(self.button('Open paper', lambda: self.controller.main.open_papers([self.controller.paper_item(row)])))
        box.addWidget(self.button('Practice again', lambda: self.controller.start(row, 'practice'), primary=True))
        box.addWidget(self.button('Take exam again', lambda: self.controller.start(row, 'exam')))
        layout.addWidget(actions)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.resize_columns()

    def resize_columns(self):
        if self._metrics is not None:
            self._metrics.setDirection(QBoxLayout.Direction.LeftToRight if self.viewport().width() >= 620 else QBoxLayout.Direction.TopToBottom)
        if self._columns is not None:
            self._columns.setDirection(QBoxLayout.Direction.LeftToRight if self.viewport().width() >= 780 else QBoxLayout.Direction.TopToBottom)
        for box in self._action_rows:
            box.setDirection(QBoxLayout.Direction.LeftToRight if self.viewport().width() >= 780 else QBoxLayout.Direction.TopToBottom)

    def subject_accent(self, card, row):
        # Share History's intentional semantic subject colors, limited to a slim bar.
        accent = self.controller.main._history_subject_accent_color(row.get('subject_code'))
        card.setStyleSheet(f'QFrame#{card.objectName()} {{border-left:3px solid {accent};}}')

    def refresh_theme(self, *_):
        bg = Colors.BG_CARD
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, bg)
        muted = ThemeManager._ensure_text_contrast(Colors.TEXT_GRAY, bg)
        border = Colors.BG_LIGHT
        foreground = ThemeManager._ensure_text_contrast(Colors.TEXT_WHITE, Colors.PRIMARY)
        self.setStyleSheet(
            'QScrollArea#studyDashboard,QWidget#dashboardBody {background:transparent;border:none;}'
            f'QLabel {{background:transparent;color:{text};border:none;}} QLabel#dashboardMuted {{color:{muted};font-size:12px;}}'
            f'QFrame#dashboardSection {{background:{bg};border:1px solid {border};border-radius:8px;}}'
            f'QFrame#dashboardEntry {{background:transparent;border:1px solid {border};border-radius:6px;}}'
            f'QPushButton {{background:{bg};color:{text};border:1px solid {border};border-radius:6px;padding:7px 10px;min-height:22px;font-size:13px;}}'
            f'QPushButton:hover {{background:{Colors.BG_LIGHT};border-color:{Colors.PRIMARY};}}'
            f'QPushButton:pressed {{background:{Colors.BG_LIGHT};}} QPushButton:focus {{border:1px solid {Colors.PRIMARY};}}'
            f'QPushButton[dashboardPrimary="true"] {{background:{Colors.PRIMARY};color:{foreground};}}'
            f'QPushButton[dashboardPrimary="true"]:hover {{background:{Colors.PRIMARY_HOVER};}}'
            'QLabel#dashboardGreeting {font-size:32px;font-weight:700;}'
            'QLabel#metricLabel {font-size:11px;font-weight:600;} QLabel#metricValue {font-size:32px;font-weight:700;} QLabel#metricUnit {font-size:12px;}'
            'QPushButton#dashboardMetric {text-align:left;padding:0;min-height:112px;max-height:112px;}'
            'QPushButton#dashboardPaperTitle {font-weight:600;text-align:left;border:none;padding:0;}'
        )


class DashboardController(QObject):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.records = []
        self.error = False
        self.answer_snapshot = None
        self.answer_error = False
        self._future = None
        self._future_kind = 'records'
        self._updating_history = False
        self._refresh_again = False
        self._pending_answers = None
        self._answer_request_id = None
        self._results_scroll_position = 0
        self.poll = QTimer(self); self.poll.setInterval(20); self.poll.timeout.connect(self.receive)
        layout = main.results_panel.layout()
        index = layout.indexOf(main.results_scroll)
        layout.removeWidget(main.results_scroll)
        self.stack = QStackedWidget(main.results_panel)
        self.stack.setStyleSheet('QStackedWidget {background:transparent;border:none;}')
        self.stack.addWidget(main.results_scroll)
        self.home = StudyDashboard(self); self.stack.addWidget(self.home)
        layout.insertWidget(index, self.stack, 1)
        toolbar = layout.itemAt(0).layout()
        self.toolbar_widgets = [toolbar.itemAt(i).widget() for i in range(toolbar.count()) if toolbar.itemAt(i).widget()]
        self.home_button = QPushButton(tr('Dashboard'))
        self.home_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.home_button.clicked.connect(self.show_home)
        shell = getattr(main, '_experimental_shell', None)
        (shell.results_actions.layout() if shell else toolbar).addWidget(self.home_button)
        self.show_home()
        self.refresh()

    def refresh(self):
        if self._future is not None:
            self._refresh_again = True
            return
        self._future_kind = 'records'
        self._future = submit_io(StudyHistory.records)
        self.poll.start()

    def receive(self):
        if self._future is None or not self._future.done(): return
        future, kind = self._future, self._future_kind
        self._future = None; self.poll.stop()
        try:
            value = future.result()
            if kind == 'records':
                self.records = value; self.error = False
                if self.home.kind in ('paper', 'attempt') and self.home.selected:
                    selected_id = self.home.selected.get('id')
                    self.home.selected = next((row for row in value if row['id'] == selected_id), self.home.selected)
                self._updating_history = True
                try: self.main.refresh_history()
                finally: self._updating_history = False
            elif self.home.kind == 'attempt' and self.home.selected.get('id') == self._answer_request_id:
                self.answer_snapshot = value; self.answer_error = value is None
        except Exception:
            if kind == 'records': self.error = True
            else: self.answer_error = True
        self.home.render()
        if self._pending_answers is not None:
            row = self._pending_answers; self._pending_answers = None
            self.view_answers(row)
            return
        if self._refresh_again:
            self._refresh_again = False; self.refresh()

    def show_home(self, *_):
        self.home.kind = 'home'; self.home.selected = None
        self._show_dashboard()

    def _show_dashboard(self):
        if self.stack.currentWidget() is self.main.results_scroll:
            self._results_scroll_position = self.main.results_scroll.verticalScrollBar().value()
        # Only clear a loading placeholder, never the retained search results.
        if getattr(self.main, '_results_skeleton_active', False):
            self.main._hide_results_skeleton()
        for widget in self.toolbar_widgets: widget.hide()
        self.main.exam_launch_footer.hide()
        self.stack.setCurrentWidget(self.home)
        self.home.verticalScrollBar().setValue(0)
        self.home.render()

    def show_results(self):
        for widget in self.toolbar_widgets: widget.show()
        self.stack.setCurrentWidget(self.main.results_scroll)
        # Rebuilding only on explicit return: existing result state is preserved.
        if self.main.search_results:
            self.main.display_results(list(self.main.search_results), record_history=False)
            self.main.results_scroll.verticalScrollBar().setValue(self._results_scroll_position)
            QTimer.singleShot(0, self, self._restore_results_scroll)
        else:
            self.main._show_results_empty_state("Search for papers to get started")

    def _restore_results_scroll(self):
        if self.stack.currentWidget() is self.main.results_scroll:
            self.main.results_scroll.verticalScrollBar().setValue(self._results_scroll_position)

    def shutdown(self):
        self.poll.stop()
        if self._future is not None:
            self._future.cancel()
        self._pending_answers = None

    def enter_results(self):
        for widget in self.toolbar_widgets: widget.show()
        self.stack.setCurrentWidget(self.main.results_scroll)

    def focus_search(self):
        self.main.control_center_tabs.setCurrentIndex(0)
        self.main._set_sidebar_collapsed(False, persist=False, animate=False)
        self.main._focus_control_anchor('subject')

    def open_flagged(self):
        self.home.kind = 'flagged'; self.home.selected = None; self._show_dashboard()

    def open_activity(self, mode=None):
        self.home.kind = 'activity'; self.home.selected = mode; self._show_dashboard()

    def open_paper(self, row):
        self.home.kind = 'paper'; self.home.selected = row; self._show_dashboard()

    def open_attempt(self, row):
        self.home.kind = 'attempt'; self.home.selected = row
        self.answer_snapshot = None; self.answer_error = False
        self._show_dashboard()

    def view_answers(self, row):
        if self._future is not None:
            self._pending_answers = row
            return
        self._answer_request_id = row['id']
        self._future_kind = 'answers'; self._future = submit_io(StudyHistory.read_attempt, row); self.poll.start()

    @staticmethod
    def paper_item(row):
        local = str(row.get('local_pdf_path') or '')
        target = local if local and Path(local).is_file() else row.get('pdf_url', '')
        return dict(subject_code=row['subject_code'], subject=row['subject_name'],
                    year=row['year'], series=row['series'], component=row['component'],
                    url=target, direct_url=target, type='QP', source='')

    def quick_look(self, row):
        self.main._open_quick_look_window(self.paper_item(row))

    def start(self, row, mode):
        self.main.launch_exam_mode_for_item(self.paper_item(row), paper_num_override=row['component'],
            paper_resources=row.get('paper_resources') or None, session_mode_override=mode)

    def resume(self, row, question=None):
        self.main.continue_saved_exam_attempt(row['resume_key'], flagged_question=question)

    @staticmethod
    def open_local(path):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
