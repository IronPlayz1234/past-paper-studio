"""Synchronized, responsive exam presentation around the existing exam backend."""
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QBoxLayout, QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QMenu, QPushButton, QSizePolicy, QSplitter, QTextEdit, QTreeWidget, QGridLayout,
    QTreeWidgetItem, QVBoxLayout, QWidget, QMessageBox, QCheckBox)

from UI.theme import get_theme_manager
from UI.exam_interactions import button_style
from Utils.gui_utils import Colors
from Utils.question_id_mapper import parse_question_id, normalize_question_id_canonical as normalize_question_id


def _token(name, fallback):
    return get_theme_manager().get_theme_tokens(get_theme_manager().current_theme()).get(name, fallback)


def _widget_color(widget_type, fallback):
    manager = get_theme_manager()
    custom = manager._custom_entry(manager.current_theme()) or {}
    return custom.get('widget_colors', {}).get(widget_type, fallback)


def _empty_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.layout():
            _empty_layout(item.layout())
        elif item.widget():
            item.widget().hide()


def choose_session_mode(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Start a paper")
    dialog.setMinimumWidth(430)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(24, 24, 24, 24)
    heading = QLabel("How would you like to work?")
    heading.setFont(QFont("Arial", 18, QFont.Weight.Bold))
    root.addWidget(heading)
    detail = QLabel("Practice at your own pace, or simulate a timed exam.")
    detail.setWordWrap(True)
    root.addWidget(detail)
    dialog.selected_mode = None
    for mode, text, tip in (
        ("practice", "Practice · no time limit", "Stopwatch, optional pause and mark scheme access."),
        ("exam", "Exam · official time limit", "Countdown; mark scheme locked until completion."),
    ):
        button = QPushButton(text)
        button.setMinimumHeight(48)
        button.setToolTip(tip)
        def select(_checked=False, value=mode):
            dialog.selected_mode = value
            dialog.accept()
        button.clicked.connect(select)
        root.addWidget(button)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dialog.reject)
    root.addWidget(cancel)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    selected = dialog.selected_mode if accepted else None
    dialog.deleteLater()
    return selected


class QuestionNavigator(QFrame):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.setObjectName("studioQuestionNavigator")
        self.setMinimumWidth(200)
        self.setMaximumWidth(300)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        title = QLabel("Questions")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        root.addWidget(title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.filter = QComboBox()
        self.filter.addItems(["All questions", "Unanswered", "Flagged"])
        self.filter.setAccessibleName("Filter questions")
        self.filter.currentIndexChanged.connect(self.refresh)
        root.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAccessibleName("Question overview")
        self.tree.itemClicked.connect(self._selected)
        root.addWidget(self.tree, 1)
        self.items = {}

    def _selected(self, item, _column):
        qid = item.data(0, Qt.ItemDataRole.UserRole)
        if qid:
            self.workspace.select_question(qid)

    def refresh(self, *_):
        w = self.workspace.window
        completion = w._compute_question_completion_state()
        flags = w.session_state.flagged_questions
        qids = self.workspace.question_ids()
        self.summary.setText(f"Answered {sum(bool(completion.get(q)) for q in qids)} / {len(qids)}\nFlagged {len(flags.intersection(qids))}")
        expanded = {}
        def remember(item, path):
            expanded[path] = item.isExpanded()
            for i in range(item.childCount()):
                child = item.child(i)
                if not child.data(0, Qt.ItemDataRole.UserRole):
                    remember(child, path + '/' + child.text(0))
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            remember(item, item.text(0))
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self.items = {}
        groups = {}
        parts = {}
        for qid in qids:
            answered = completion.get(qid, False)
            if self.filter.currentIndex() == 1 and answered:
                continue
            if self.filter.currentIndex() == 2 and qid not in flags:
                continue
            parsed = parse_question_id(qid)
            main = str(parsed.main or qid)
            if main not in groups:
                groups[main] = QTreeWidgetItem(self.tree, [f"Question {main}"])
                groups[main].setExpanded(expanded.get(f"Question {main}", True))
            parent = groups[main]
            if parsed.part and parsed.subpart:
                key = (main, parsed.part)
                if key not in parts:
                    parts[key] = QTreeWidgetItem(parent, [f"({parsed.part})"])
                    parts[key].setExpanded(expanded.get(f"Question {main}/({parsed.part})", True))
                parent = parts[key]
            label = f"({parsed.subpart})" if parsed.subpart else (f"({parsed.part})" if parsed.part else main)
            state = "Flagged" if qid in flags else ("Answered" if answered else "Unanswered")
            symbol = "⚑" if qid in flags else ("✓" if answered else "○")
            node = QTreeWidgetItem(parent, [f"{label}   {symbol} {state}"])
            node.setData(0, Qt.ItemDataRole.UserRole, qid)
            page = self.workspace.question_page(qid)
            node.setToolTip(0, f"Question {qid}" + (f" · Page {page}" if page else " · Page not mapped"))
            self.items[qid] = node
            if qid == w.session_state.active_question:
                self.tree.setCurrentItem(node)
        self.tree.verticalScrollBar().setValue(scroll)


class AnswerWorkspace(QFrame):
    def __init__(self, workspace, original):
        super().__init__()
        self.workspace = workspace
        self.setObjectName("studioAnswerWorkspace")
        self.setMinimumWidth(320)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)
        header = QHBoxLayout()
        self.title = QLabel("Answer Workspace")
        self.title.setObjectName("answerWorkspaceTitle")
        self.title.setWordWrap(True)
        self.title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        header.addWidget(self.title, 1)
        self.flag = QPushButton("⚑ Flag")
        self.flag.setCheckable(True)
        self.flag.setToolTip("Flag this question for review (Alt+F)")
        self.flag.clicked.connect(workspace.toggle_flag)
        header.addWidget(self.flag)
        root.addLayout(header)
        self.page = QPushButton("Page not mapped")
        self.page.setToolTip("Show this question's page without changing the answer")
        self.page.clicked.connect(workspace.show_question_page)
        root.addWidget(self.page, 0, Qt.AlignmentFlag.AlignLeft)
        self.answer_label = QLabel("Answer")
        root.addWidget(self.answer_label)
        self.original = original
        root.addWidget(original, 1)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMaximumHeight(155)
        self.preview.hide()
        root.addWidget(self.preview)
        row = QHBoxLayout()
        self.previous = QPushButton("Previous Question")
        self.next = QPushButton("Next Question")
        self.previous.clicked.connect(lambda: workspace.step_question(-1))
        self.next.clicked.connect(lambda: workspace.step_question(1))
        row.addWidget(self.previous)
        row.addWidget(self.next)
        root.addLayout(row)
        self.status = QLabel("Answers save automatically")
        self.status.setWordWrap(True)
        root.addWidget(self.status)


class ExamWorkspace(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._selecting = False
        self._last_orientation = None
        self._preview_signature = None
        self._navigator_before_focus = True
        self._was_focused = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self.refresh_status)
        self._install_header()
        if window.questionnaire is not None:
            window.questionnaire.setMinimumHeight(0)
        self.navigator = QuestionNavigator(self)
        self.answer = None
        self.outer_splitter = None
        if window.exam_splitter is not None and getattr(window, 'questionnaire', None) is not None:
            pdf = window._exam_splitter_pdf_widget
            original = window._exam_splitter_answer_widget
            self.answer = AnswerWorkspace(self, original)
            window._exam_splitter_answer_widget = self.answer
            window.exam_splitter.addWidget(self.answer)
            self.outer_splitter = QSplitter(Qt.Orientation.Horizontal)
            self.outer_splitter.setHandleWidth(5)
            content = window.exam_page.layout().itemAt(0).layout()
            content.removeWidget(window.exam_splitter)
            self.outer_splitter.addWidget(self.navigator)
            self.outer_splitter.addWidget(window.exam_splitter)
            self.outer_splitter.setStretchFactor(0, 0)
            self.outer_splitter.setStretchFactor(1, 1)
            self.outer_splitter.setSizes([220, 1180])
            content.addWidget(self.outer_splitter)
        else:
            self.navigator.hide()
        window.installEventFilter(self)
        self._header_size_timer = QTimer(self)
        self._header_size_timer.setSingleShot(True)
        self._header_size_timer.timeout.connect(self._reserve_header_sizes)
        self._install_shortcuts()
        self.resize_workspace()
        self.refresh_theme()
        qids = self.question_ids()
        if qids:
            active = window.session_state.active_question
            self.select_question(active if active in qids else qids[0], navigate=True)
        self.apply_focus()
        self._start_mcq_mapping()

    def _start_mcq_mapping(self):
        w = self.window
        if w.paper_mode != 'MCQ_ONLY' or not w.local_pdf_path:
            return
        from Core.background_tasks import submit_io
        from Utils.unified_question_extractor import UnifiedQuestionExtractor
        extractor = UnifiedQuestionExtractor()
        self._mapping_future = submit_io(extractor.extract_questions,
            pdf_path=w.local_pdf_path, subject_code=w.subject_code,
            paper_number=w.paper_number_raw, exam_year=w.exam_year, mode='MCQ_ONLY',
            default_marks=1.0, expected_mcq_count=w.questionnaire.num_questions)
        self._mapping_poll = QTimer(self)
        self._mapping_poll.setInterval(100)
        self._mapping_poll.timeout.connect(self._finish_mcq_mapping)
        self._mapping_poll.start()

    def _finish_mcq_mapping(self):
        if self.window._graceful_exit_cleanup_started:
            self._mapping_poll.stop()
            return
        if not self._mapping_future.done():
            return
        self._mapping_poll.stop()
        try:
            result = self._mapping_future.result()
        except Exception:
            return  # Unknown mappings remain explicit rather than inventing a page.
        w = self.window
        w.question_items = result.question_items
        w.question_texts = result.question_texts
        self.select_question(w.session_state.active_question)

    def _install_header(self):
        w = self.window
        _empty_layout(w.top_bar.layout())
        root = w.top_bar.layout()
        self.header = QWidget(w.top_bar)
        self.header.setObjectName("studioExamHeader")
        columns = QVBoxLayout(self.header)
        columns.setContentsMargins(8, 4, 8, 4)
        columns.setSpacing(6)
        row = QGridLayout()
        row.setColumnStretch(0, 1)
        row.setColumnStretch(2, 1)
        self.paper_title = QLabel(f"{w.subject_name}  {w.subject_code}/{w.paper_number_raw}")
        self.paper_title.setWordWrap(True)
        self.paper_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.paper_title.setFont(QFont("Arial", 17, QFont.Weight.Bold))
        series = {"MJ":"May/June", "ON":"October/November", "FM":"February/March"}.get(w.series, w.series)
        self.paper_title.setToolTip(f"{series} {w.exam_year} · {w.session_state.mode.title()}")
        self.identity = QWidget()
        identity_layout = QVBoxLayout(self.identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(2)
        identity_layout.addWidget(self.paper_title)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("font-size:13px;")
        identity_layout.addWidget(self.caption)
        self.identity.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.caption.setFixedHeight(36)
        row.addWidget(self.identity, 0, 0)
        w.timer_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        w.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reserve = '999:59 / 999m' if w.session_state.mode == 'practice' else '999:59'
        w.timer_label.setFixedWidth(w.timer_label.fontMetrics().horizontalAdvance(reserve) + 36)
        w.timer_label.setFixedHeight(46)
        row.addWidget(w.timer_label, 0, 1)
        self.actions = QWidget()
        self.actions.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.action_layout = QHBoxLayout(self.actions)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(6)
        for widget in (w.pause_btn, w.question_navigator_btn, w.additional_tools_btn, w.focus_mode_btn):
            self.action_layout.addWidget(widget)
            widget.show()
        w.additional_tools_btn.setText("Tools")
        w.focus_mode_btn.setText("Focus")
        w.pause_btn.setFixedWidth(max(w.pause_btn.fontMetrics().horizontalAdvance(t) for t in ('Pause', 'Resume')) + 36)
        w.focus_mode_btn.setFixedWidth(w.focus_mode_btn.fontMetrics().horizontalAdvance('Exit Focus') + 36)
        self.answers_toggle = QPushButton("Answers")
        self.answers_toggle.setCheckable(True)
        self.answers_toggle.setChecked(True)
        self.answers_toggle.setToolTip("Show or collapse Answer Workspace")
        self.answers_toggle.clicked.connect(self.toggle_answers)
        self.action_layout.addWidget(self.answers_toggle)
        self.more = QPushButton("•••")
        self.more.setAccessibleName("More exam actions")
        self.more.clicked.connect(self.show_more)
        self.action_layout.addWidget(self.more)
        w.submit_btn.setText("Finish Practice" if w.session_state.mode == 'practice' else "Finish Exam")
        w.submit_btn.clicked.disconnect()
        w.submit_btn.clicked.connect(self.show_finish_review)
        self.action_layout.addWidget(w.submit_btn)
        w.submit_btn.show()
        # Caption/stylesheet polishing can round the action row's height by a
        # pixel. Keep buttons anchored so Pause/Resume never nudges vertically.
        for i in range(self.action_layout.count()):
            widget = self.action_layout.itemAt(i).widget()
            if widget is not None:
                self.action_layout.setAlignment(widget, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.actions, 0, 2, Qt.AlignmentFlag.AlignRight)
        columns.addLayout(row)
        self.header_columns = columns
        self.header_row = row
        root.addWidget(self.header, 1)
        # These existing controls stay available through the overflow menu.
        for widget in (w.end_btn, w.download_ms_btn, w.exam_settings_btn, w.paper_info_btn,
                       w.grading_mode_btn, w.top_bar_pill):
            widget.hide()
        self._pdf_toolbar(w.pdf_viewer)
        w._question_scale_visible = False
        for viewer in w._iter_ruler_viewers():
            viewer.set_centimeter_scale_enabled(False)

    def _pdf_toolbar(self, viewer):
        _empty_layout(viewer.controls_layout)
        row = viewer.controls_layout
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        for widget in (viewer.prev_btn, viewer.page_label, viewer.next_btn):
            row.addWidget(widget)
            widget.show()
        viewer.prev_btn.setText("‹")
        viewer.next_btn.setText("›")
        viewer.prev_btn.setAccessibleName("Previous PDF page")
        viewer.next_btn.setAccessibleName("Next PDF page")
        row.addStretch(1)
        for widget in (viewer.zoom_out_btn, viewer.zoom_label, viewer.zoom_in_btn, viewer.fit_btn):
            row.addWidget(widget)
            widget.show()
        viewer.fit_btn.setText("Fit")
        viewer.fit_btn.clicked.disconnect()
        fit = QMenu(viewer.fit_btn)
        fit.addAction("Fit Width", viewer.fit_to_width)
        fit.addAction("Fit Page", viewer.fit_to_page)
        fit.addAction("Actual Size", lambda: viewer._apply_zoom_factor(1.0))
        viewer.fit_btn.setMenu(fit)
        overflow = QPushButton("•••")
        overflow.setAccessibleName("More PDF controls")
        menu = QMenu(overflow)
        menu.addAction("Rotate left 90°", viewer.rotate_current_page_ccw)
        menu.addAction("Rotate right 90°", viewer.rotate_current_page_cw)
        menu.addSeparator()
        menu.addAction("One page", lambda: viewer.page_mode_combo.setCurrentIndex(0))
        menu.addAction("Two pages", lambda: viewer.page_mode_combo.setCurrentIndex(1))
        overflow.setMenu(menu)
        row.addWidget(overflow)
        if self.window.is_listening:
            row.addWidget(viewer.audio_header)
            viewer.audio_header.show()
        self.pdf_overflow = overflow
        self.source_return_bar = QWidget(viewer)
        source_row = QHBoxLayout(self.source_return_bar)
        source_row.setContentsMargins(4, 4, 4, 4)
        self.return_to_question = QPushButton('← Back to Question Paper')
        self.return_to_question.setAccessibleName('Back to Question Paper')
        self.return_to_question.clicked.connect(self.window._show_question_paper_in_viewer)
        source_row.addWidget(self.return_to_question)
        source_row.addWidget(QLabel('Mark Scheme'))
        source_row.addStretch()
        viewer.layout().insertWidget(0, self.source_return_bar)
        self.sync_source_controls()
        for button in viewer.controls_row.findChildren(QPushButton):
            button.setMinimumWidth(30)
        viewer.fit_btn.setMinimumWidth(52)

    def sync_source_controls(self):
        self.source_return_bar.setVisible(self.window._active_pdf_source_key == 'mark_scheme')

    def question_ids(self):
        hidden = getattr(getattr(self.window, 'questionnaire', None), 'hidden_questions', set())
        return [q for q in self.window._question_label_order() if q not in hidden]

    def question_page(self, qid):
        item = next((i for i in self.window.question_items if i.canonical_id == qid), None)
        try:
            page = int(item.page) if item and item.page is not None else None
            return page if page and page > 0 else None
        except (TypeError, ValueError):
            return None

    def select_question(self, qid, *, navigate=True):
        qid = normalize_question_id(str(qid))
        if self._selecting or not self.answer or qid not in self.question_ids():
            return
        self._selecting = True
        try:
            w = self.window
            questionnaire = w.questionnaire
            w.session_state.active_question = qid
            if hasattr(questionnaire, 'ensure_question_widget'):
                questionnaire.ensure_question_widget(qid)
            for key, widget in questionnaire.question_widgets.items():
                widget.setVisible(str(key) == qid)
                if str(key) == qid:
                    self._prepare_question_row(widget)
            questionnaire.scroll.verticalScrollBar().setValue(0)
            if w.session_state.completed:
                w._set_questionnaire_editable(False)
            self.answer.title.setText(f"Question {qid}")
            page = self.question_page(qid)
            self.answer.page.setText(f"Page {page}" if page else "Page not mapped")
            self.answer.page.setEnabled(page is not None)
            qids = self.question_ids()
            index = qids.index(qid)
            self.answer.previous.setEnabled(index > 0)
            self.answer.next.setEnabled(index < len(qids)-1)
            if navigate and page:
                self.show_question_page()
            self.refresh_status()
            w._mark_resume_snapshot_dirty()
        finally:
            self._selecting = False

    def _prepare_question_row(self, widget):
        from UI.localization import source_text
        layout = widget.layout()
        if isinstance(layout, QBoxLayout):
            layout.setDirection(QBoxLayout.Direction.TopToBottom)
            layout.setContentsMargins(0, 0, 0, 0)
            # Question identity and page controls live in the workspace header.
            for i in range(layout.count()):
                child = layout.itemAt(i).widget()
                if isinstance(child, QLabel) or (isinstance(child, QPushButton) and source_text(child).startswith('Page ')):
                    child.hide()
        for split in getattr(self.window.questionnaire, 'answer_split_widgets', {}).values():
            if split.parentWidget() is widget and isinstance(split.layout(), QBoxLayout):
                split.layout().setDirection(QBoxLayout.Direction.TopToBottom)
        for editor in widget.findChildren(QTextEdit):
            in_table = False
            ancestor = editor.parentWidget()
            while ancestor and ancestor is not widget:
                if ancestor.__class__.__name__ == 'TableAnswerWidget':
                    in_table = True
                    break
                ancestor = ancestor.parentWidget()
            is_note = editor in getattr(self.window.questionnaire, 'drawing_note_inputs', {}).values()
            editor.setMinimumHeight(48 if in_table else (90 if is_note else 240))
            editor.setMaximumHeight(16777215)
            background = _widget_color('QTextEdit', _token('INPUT_BG', Colors.BG_DARK))
            foreground = get_theme_manager()._ensure_text_contrast(Colors.TEXT_LIGHT, background)
            editor.setStyleSheet(f"QTextEdit {{background:{background};color:{foreground};font-size:16px;border:1px solid {Colors.BG_LIGHT};border-radius:6px;padding:10px;}}")
        widget.setStyleSheet("background:transparent;border:none;")
        widget.setMinimumHeight(widget.layout().minimumSize().height())
        # Drawing actions retain the existing editor/upload/clear workflows.
        for button in widget.findChildren(QPushButton):
            if button.property('drawingActionType'):
                button.setMinimumWidth(0)
                button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
                button.setStyleSheet(button_style() + 'QPushButton {min-width:0px;min-height:26px;}')
            if button.text() in {'A', 'B', 'C', 'D'} and hasattr(self.window.questionnaire, 'radio_buttons'):
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)
                button.setMinimumHeight(42)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            if button.property('drawingActionType') == 'upload':
                has_drawing = bool(self.window.questionnaire.drawing_paths.get(self.window.session_state.active_question))
                button.setText('Replace' if has_drawing else 'Upload Image')
                button.setToolTip('Open the saved drawing to edit its replacement' if has_drawing else 'Upload a drawing image')
                button.setAccessibleName('Replace Drawing' if has_drawing else 'Upload Drawing Image')
            if button.property('drawingActionType') == 'open':
                button.setText("Edit Drawing" if self.window.questionnaire.drawing_paths.get(self.window.session_state.active_question) else "Draw Answer")
        questionnaire = self.window.questionnaire
        qid = self.window.session_state.active_question
        drawing_status = getattr(questionnaire, 'drawing_status_labels', {}).get(qid)
        if drawing_status:
            drawing_status.setText('Drawing saved' if questionnaire.drawing_paths.get(qid) else 'No drawing yet')
        marks_badge = getattr(questionnaire, 'marks_labels', {}).get(qid)
        if marks_badge and self.window.session_state.completed and marks_badge.text():
            marks_badge.show()
        for holder in (questionnaire.scroll, getattr(questionnaire, '_container_widget', None)):
            if holder:
                holder.setStyleSheet("background:transparent;border:none;")

    def show_question_page(self):
        w = self.window
        page = self.question_page(w.session_state.active_question)
        if page:
            if w._active_pdf_source_key != 'question':
                w._show_pdf_source('question', emit_signal=False)
            w.pdf_viewer.go_to_page(page-1)

    def step_question(self, delta):
        qids = self.question_ids()
        if not qids:
            return
        current = self.window.session_state.active_question
        index = qids.index(current) if current in qids else 0
        self.select_question(qids[max(0, min(len(qids)-1, index+delta))])

    def toggle_flag(self):
        state = self.window.session_state
        qid = state.active_question
        if not qid or state.completed:
            return
        if qid in state.flagged_questions:
            state.flagged_questions.remove(qid)
        else:
            state.flagged_questions.add(qid)
        self.window._mark_resume_snapshot_dirty()
        self.refresh_status()

    def refresh_status(self):
        self.navigator.refresh()
        w = self.window
        state = w.session_state
        series = {"MJ":"May/June", "ON":"October/November", "FM":"February/March"}.get(w.series, w.series)
        details = [f"{series} {w.exam_year}", state.mode.title()]
        if state.assisted: details.append("Assisted")
        if state.pause_count: details.append(f"Paused {state.pause_count}×")
        if w.manual_grading_only: details.append("Manual grading")
        self.caption.setText(" · ".join(details))
        w.grade_status_label.setVisible(bool(w._grading_in_progress) and not w.focus_mode_enabled)
        if not self.answer:
            return
        w = self.window
        qid = w.session_state.active_question
        flagged = qid in w.session_state.flagged_questions
        self.answer.flag.setChecked(flagged)
        self.answer.flag.setText("⚑ Flagged" if flagged else "⚑ Flag")
        self.answer.flag.setEnabled(not w.session_state.completed)
        payload = w.questionnaire.get_answers().get(qid, {})
        image = payload.get('image_path', '') if isinstance(payload, dict) else ''
        try:
            signature = (qid, image, Path(image).stat().st_mtime_ns) if image and Path(image).is_file() else None
        except OSError:
            signature = None
        if signature and signature != self._preview_signature:
            pixmap = QPixmap(image)
            if not pixmap.isNull():
                self.answer.preview.setPixmap(pixmap.scaled(260, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.answer.preview.setToolTip("Saved drawing preview")
                self.answer.preview.show()
        elif signature is None:
            self.answer.preview.hide()
        self._preview_signature = signature
        self.answer.status.setText("Attempt completed · answers locked" if w.session_state.completed else "Answers save automatically")
        current = w.questionnaire.question_widgets.get(qid) or w.questionnaire.question_widgets.get(int(qid) if qid.isdigit() else qid)
        if current:
            self._prepare_question_row(current)

    def answer_changed(self):
        self._refresh_timer.start()

    def toggle_navigator(self):
        if not self.outer_splitter:
            return
        self.navigator.setVisible(not self.navigator.isVisible())
        if self.navigator.isVisible():
            self.navigator.refresh()

    def toggle_answers(self, visible):
        if self.answer:
            self.answer.setVisible(bool(visible))

    def apply_focus(self):
        w = self.window
        focused = w.focus_mode_enabled
        if focused:
            if not self._was_focused:
                self._navigator_before_focus = not self.navigator.isHidden()
            self.navigator.hide()
        elif self.outer_splitter and self._was_focused:
            self.navigator.setVisible(self._navigator_before_focus and w.width() >= 1150)
        self._was_focused = focused
        for widget in (w.pause_btn, w.question_navigator_btn, w.additional_tools_btn,
                       self.more, self.answers_toggle, self.identity):
            widget.setVisible(not focused)
        w.pause_btn.setEnabled(not w.session_state.completed)
        w.focus_mode_btn.show()
        w.focus_mode_btn.setText("Exit Focus" if focused else "Focus")
        w.submit_btn.setVisible(not focused and w.paper_mode != 'VIEWER_ONLY' and not w._submission_locked_for_autograde)
        w.grade_status_label.setVisible(not focused and bool(w._grading_in_progress))
        if focused and w.utility_drawer:
            w.utility_drawer.hide()

    def show_more(self):
        w = self.window
        menu = QMenu(self.more)
        menu.setStyleSheet(self.menu_style())
        menu.addAction("Paper information", w._show_paper_info_popover)
        menu.addAction("Settings", w._show_exam_settings_window)
        menu.addAction("Pause / Resume (recorded)", w.toggle_pause)
        if w.session_state.mode == 'practice' or w.session_state.completed:
            menu.addAction("Download mark scheme", w.download_mark_scheme)
            menu.addAction("View mark scheme", w._show_mark_scheme_in_viewer)
        if 'insert' in w._available_pdf_sources:
            menu.addAction("Question paper / Insert", w._toggle_question_insert_view)
            menu.addAction("Split question paper and insert", w._open_insert_split_view)
        if w.session_state.completed:
            menu.addAction("Grading / Mapping", w._show_grading_mode_menu)
        menu.addSeparator()
        if not w.session_state.completed:
            menu.addAction("Save and close attempt", self.save_and_close)
        menu.addAction("Close finished attempt" if w.session_state.completed else "End without grading…", w.graceful_exit if w.session_state.completed else w.end_exam)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def save_and_close(self):
        if self.window.session_state.completed or self.window._save_unfinished_attempt():
            self.window.graceful_exit()

    def add_document_tools(self, menu):
        action = menu.addAction("Protractor")
        action.setCheckable(True)
        overlay = getattr(self.window.pdf_viewer, '_document_protractor', None)
        action.setChecked(bool(overlay and overlay.isVisible()))
        action.toggled.connect(self.toggle_protractor)
        menu.addAction("Reset protractor position", self.reset_protractor)
        qid = self.window.session_state.active_question
        if getattr(self.window.questionnaire, 'answer_types', {}).get(qid) == 'drawing' and not self.window.session_state.completed:
            menu.addSeparator()
            menu.addAction("Edit drawing answer", lambda: self.window.questionnaire._open_drawing_canvas(qid))
            menu.addAction("Upload drawing image…", lambda: self.window.questionnaire._upload_drawing(qid))

    def toggle_protractor(self, enabled):
        viewer = self.window.pdf_viewer
        overlay = getattr(viewer, '_document_protractor', None)
        if overlay is None and enabled:
            from UI.document_protractor import DocumentProtractor
            overlay = DocumentProtractor(viewer)
            viewer._document_protractor = overlay
        if overlay:
            overlay.update_scale()
            overlay.setVisible(enabled)
            overlay.raise_()

    def reset_protractor(self):
        overlay = getattr(self.window.pdf_viewer, '_document_protractor', None)
        if overlay:
            overlay.reset_position()

    @staticmethod
    def menu_style():
        return f"QMenu {{background:{Colors.BG_CARD};color:{Colors.TEXT_LIGHT};border:1px solid {Colors.BG_LIGHT};padding:5px;}} QMenu::item {{padding:6px 16px;font-size:14px;}} QMenu::item:selected {{background:{_token('SELECTION', Colors.BG_LIGHT)};}}"

    def show_finish_review(self):
        w = self.window
        if w.session_state.completed:
            w.open_submit_review_page()
            return
        if w.paper_mode == 'VIEWER_ONLY':
            w.end_exam()
            return
        w._sync_exam_clock()
        completion = w._compute_question_completion_state()
        qids = self.question_ids()
        unanswered = [q for q in qids if not completion.get(q, False)]
        flagged = [q for q in qids if q in w.session_state.flagged_questions]
        dialog = QDialog(w)
        dialog.setWindowTitle("Ready to finish?")
        dialog.setMinimumWidth(420)
        root = QVBoxLayout(dialog)
        heading = QLabel("Ready to finish?")
        heading.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        root.addWidget(heading)
        detail = QLabel(f"Answered: {len(qids)-len(unanswered)} / {len(qids)}\nUnanswered: {len(unanswered)}\nFlagged: {len(flagged)}\n{'Elapsed' if w.session_state.mode == 'practice' else 'Time remaining'}: {w.timer_label.text()}")
        detail.setStyleSheet("font-size:16px;")
        root.addWidget(detail)
        for label, questions, filter_index in (("Review Unanswered", unanswered, 1), ("Review Flagged", flagged, 2)):
            button = QPushButton(label)
            button.setEnabled(bool(questions))
            def review(_checked=False, ids=questions, index=filter_index):
                dialog.reject()
                self.navigator.filter.setCurrentIndex(index)
                self.navigator.show()
                self.select_question(ids[0])
            button.clicked.connect(review)
            root.addWidget(button)
        cancel = QPushButton("Keep working")
        cancel.clicked.connect(dialog.reject)
        root.addWidget(cancel)
        finish = QPushButton("Finish Practice" if w.session_state.mode == 'practice' else "Finish Exam")
        finish.clicked.connect(dialog.accept)
        root.addWidget(finish)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        if accepted:
            w.complete_workspace_attempt()

    def refresh_completed_review(self):
        w = self.window
        grid = w.submit_review_grid
        if grid is None:
            return
        while grid.count():
            item = grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        qids = self.question_ids()
        completed = w._compute_question_completion_state()
        flags = w.session_state.flagged_questions.intersection(qids)
        state = w.session_state
        elapsed = f"{state.elapsed_seconds//60:02d}:{state.elapsed_seconds%60:02d}"
        w.submit_review_title_label.setText("Practice completed" if state.mode == 'practice' else "Exam completed")
        w.submit_review_subtitle.setText(f"Time used {elapsed} · Flagged {len(flags)}" + (" · Assisted practice" if state.assisted else "") + (f" · Paused {state.pause_count} times" if state.pause_count else "") + "\nAnswers are saved and locked. Review your responses, then choose AI or manual grading.")
        w.submit_review_subtitle.setWordWrap(True)
        w.submit_answered_count_label.setText(f"Answered {sum(bool(completed.get(q)) for q in qids)} / {len(qids)}")
        w.submit_unanswered_count_label.setText(f"Unanswered {sum(not completed.get(q, False) for q in qids)}")
        # The old color-only legend is replaced by explicit state text on every card.
        legend = w.submit_review_page.layout().itemAt(3).layout()
        if legend:
            for i in range(legend.count()):
                widget = legend.itemAt(i).widget()
                if widget: widget.hide()
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        columns = max(2, min(6, (w.width()-60)//185))
        for i, qid in enumerate(qids):
            card = QFrame()
            card.setMinimumWidth(150)
            card.setFixedHeight(174)
            card.setStyleSheet(f"QFrame {{background:{Colors.BG_CARD};color:{Colors.TEXT_LIGHT};border-radius:6px;}} QLabel,QCheckBox {{font-size:14px;color:{Colors.TEXT_LIGHT};}} QComboBox {{font-size:14px;}}")
            row = QVBoxLayout(card)
            row.setContentsMargins(10,10,10,10)
            question = QPushButton(f"Question {qid}" + ("  ⚑" if qid in flags else ""))
            question.setToolTip("Review this answer and its PDF page")
            question.setStyleSheet(f"QPushButton {{background:{Colors.BG_LIGHT};color:{Colors.TEXT_LIGHT};border:none;border-radius:6px;font-size:14px;padding:5px 8px;}}")
            def select(_checked=False, q=qid):
                w._go_back_to_exam_page()
                self.select_question(q)
            question.clicked.connect(select)
            row.addWidget(question)
            row.addWidget(QLabel("Answered" if completed.get(qid) else "Unanswered"))
            confidence = QComboBox()
            confidence.addItems(["Confidence: low", "Confidence: medium", "Confidence: high"])
            confidence.setCurrentIndex({'low':0,'medium':1,'high':2}.get(w.question_confidence.get(qid, 'medium'),1))
            confidence.currentIndexChanged.connect(lambda index,q=qid:w.question_confidence.__setitem__(q,('low','medium','high')[index]))
            row.addWidget(confidence)
            reviewed = QCheckBox("Reviewed")
            reviewed.setChecked(qid in w.question_reviewed)
            reviewed.toggled.connect(lambda checked,q=qid:w.question_reviewed.add(q) if checked else w.question_reviewed.discard(q))
            row.addWidget(reviewed)
            grid.addWidget(card, i//columns, i%columns)
        w.submit_review_scroll.show()
        w.submit_back_btn.setText("Review answers")
        w._update_grading_action_visibility()

    def _install_shortcuts(self):
        self.shortcuts = []
        for sequence, callback in (("Alt+Right", lambda: self.step_question(1)),
            ("Alt+Left", lambda: self.step_question(-1)), ("Alt+F", self.toggle_flag),
            ("Alt+N", self.toggle_navigator), ("Alt+A", self.focus_answer),
            ("Alt+Shift+F", self.window._toggle_focus_mode)):
            shortcut = QShortcut(QKeySequence(sequence), self.window)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    def focus_answer(self):
        if not self.answer:
            return
        self.answer.show()
        self.answers_toggle.setChecked(True)
        editors = self.answer.findChildren(QTextEdit)
        for editor in editors:
            if editor.isVisibleTo(self.answer):
                editor.setFocus()
                return

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.Resize:
            self.resize_workspace()
        if watched is self.window and event.type() in (QEvent.Type.Show, QEvent.Type.FontChange, QEvent.Type.LanguageChange):
            if hasattr(self, '_header_size_timer'):
                self._header_size_timer.start(0)
        return False

    def _reserve_header_sizes(self):
        from UI.localization import tr
        w = self.window
        for button, labels in ((w.pause_btn, ('Pause', 'Resume')), (w.focus_mode_btn, ('Focus', 'Exit Focus'))):
            # Enforce content width in QSS as well: stylesheet polishing otherwise
            # replaces QWidget's minimum-width reservation on a fresh root.
            content = max(button.fontMetrics().horizontalAdvance(tr(text)) for text in labels) + 14
            neutral = _widget_color('QFrame', Colors.BG_CARD)
            text = get_theme_manager()._ensure_text_contrast(_widget_color('QLabel', Colors.TEXT_LIGHT), neutral)
            style = button_style(neutral, text, padding='7px 10px')
            button.setStyleSheet(style + f'QPushButton {{min-width:{content}px;max-width:{content}px;}}')
        self.resize_workspace()

    def resize_workspace(self):
        w = self.window
        if w.exam_splitter is not None and self.answer:
            orientation = Qt.Orientation.Horizontal if w.width() >= 1050 else Qt.Orientation.Vertical
            if orientation != self._last_orientation:
                w.exam_splitter.setOrientation(orientation)
                w.exam_splitter.setHandleWidth(6)
                w._exam_splitter_pdf_widget.setMinimumWidth(0)
                self.answer.setMinimumWidth(320 if orientation == Qt.Orientation.Horizontal else 0)
                self.answer.setMinimumHeight(240 if orientation == Qt.Orientation.Vertical else 0)
                w._exam_splitter_pdf_widget.setMinimumHeight(220 if orientation == Qt.Orientation.Vertical else 0)
                w._answer_panel_position = 'right' if orientation == Qt.Orientation.Horizontal else 'bottom'
                w._splitter_settings_key = w._splitter_settings_key_for_position(w._answer_panel_position)
                w._restore_splitter_sizes(w.exam_splitter, [650, 350])
                self._last_orientation = orientation
            if w.width() < 1150:
                self.navigator.hide()
        threshold = w.timer_label.width() + 2*self.actions.sizeHint().width() + 48
        if w.width() < threshold:
            self.header_row.removeWidget(self.actions)
            self.header_columns.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.header_columns.removeWidget(self.actions)
            self.header_row.addWidget(self.actions, 0, 2, Qt.AlignmentFlag.AlignRight)

    def refresh_theme(self):
        w = self.window
        neutral = _widget_color('QFrame', Colors.BG_CARD)
        text = get_theme_manager()._ensure_text_contrast(_widget_color('QLabel', Colors.TEXT_LIGHT), neutral)
        w.setStyleSheet(f"QDialog {{background:{Colors.BG_DARK};color:{Colors.TEXT_LIGHT};}}")
        w.top_bar.setStyleSheet(f"background:{Colors.BG_DARK};border:none;")
        self.header.setStyleSheet(f"QWidget#studioExamHeader {{background:transparent;}} QLabel {{color:{Colors.TEXT_LIGHT};}}")
        for button in self.actions.findChildren(QPushButton):
            if button not in (w.pause_btn,w.focus_mode_btn):
                button.setMinimumWidth(0)
            button.setStyleSheet(button_style(neutral, text, padding='7px 10px'))
        w.submit_btn.setStyleSheet(button_style(Colors.PRIMARY, Colors.TEXT_WHITE, primary=True, padding='8px 14px'))
        self.navigator.setStyleSheet(f"QFrame#studioQuestionNavigator {{background:{neutral};border:none;border-radius:8px;}} QLabel {{color:{text};font-size:13px;}} QTreeWidget {{background:transparent;color:{text};border:none;font-size:14px;}} QTreeWidget::item {{padding:7px 2px;}} QTreeWidget::item:selected {{background:{_token('SELECTION', Colors.BG_LIGHT)};color:{get_theme_manager()._ensure_text_contrast(Colors.TEXT_WHITE, _token('SELECTION', Colors.BG_LIGHT))};}}")
        viewer = w.pdf_viewer
        viewer.controls_row.setStyleSheet(f"QWidget {{background:{neutral};color:{text};border:none;}} QLabel {{font-size:14px;}}" + button_style(neutral,text,padding='5px 8px') + 'QPushButton {min-width:24px;min-height:24px;}')
        self.return_to_question.setStyleSheet(button_style(neutral,text))
        viewer.image_scroll.setStyleSheet(f"QScrollArea {{background:{Colors.BG_DARK};border:none;}}")
        if self.answer:
            self.answer.setStyleSheet(f"QFrame#studioAnswerWorkspace {{background:{neutral};border:none;border-radius:8px;}} QLabel {{color:{text};font-size:14px;}} QLabel#answerWorkspaceTitle {{font-size:18px;font-weight:600;}}" + button_style(neutral,text))
            self.refresh_status()
        if hasattr(self, '_header_size_timer'):
            self._header_size_timer.start(0)
