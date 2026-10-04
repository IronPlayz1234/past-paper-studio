"""Second-pass subject navigation, ambient ownership and real geometry regressions."""

import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QProgressBar
from Data.subject_categories import subject_category
from UI.static_theme_surface import StaticThemeSurface
from UI.studio_main_shell import StudioMainShell
from UI.studio_widgets import ElidedLabel, ResponsiveActions
from Utils.gui_utils import SubjectDatabase
from Tests.test_experimental_main_shell import window, groups, pump

DESKTOP_SIZES = [
    (1920, 1080),
    (1536, 864),
    (1440, 900),
    (1366, 768),
    (1280, 800),
    (800, 560),
]


@pytest.fixture(autouse=True)
def second_pass(monkeypatch):
    monkeypatch.setenv("PPF_STUDIO_GUI", "1")


def local_rect(widget, parent):
    return QRect(widget.mapTo(parent, QPoint(0, 0)), widget.size())


def test_browser_uses_catalog_filters_codes_and_names_and_switches_level(window):
    app, gui = window
    browser = gui._experimental_shell.subject_browser
    assert set(browser.visible_codes()) == set(
        SubjectDatabase.get_searchable_subjects("IGCSE")
    )
    assert "0520" not in browser.visible_codes()
    browser.search.setText("chem")
    assert browser.visible_codes() == ["0620"]
    browser.search.setText("0620")
    assert browser.visible_codes() == ["0620"]
    browser.search.setText("math")
    assert set(browser.visible_codes()) == {"0580", "0607"}
    browser.search.setText("not a supported subject")
    assert browser.visible_codes() == []
    assert browser.list.item(0).text() == "No matching subjects"
    browser.search.clear()
    gui.subjects_set_from_text("0620 - Chemistry")
    assert browser.selected_code == gui.subject_code == "0620"
    gui.alevel_level_btn.click()
    pump(app)
    assert gui.current_level == "A Level"
    assert set(browser.visible_codes()) == set(
        SubjectDatabase.get_searchable_subjects("A Level")
    )
    assert not gui.subject_code and not browser.selected_code
    browser.search.setText("9701")
    browser._choose_item(browser._first_subject())
    assert gui.subject_code == "9701" and gui.subject_name == "Chemistry"
    assert "9701" in browser.selection_label.text()
    assert subject_category("unmapped-code") == "Other"
    browser.set_catalog({"new-code": "A Newly Added Subject"}, "Example")
    assert browser.visible_codes() == ["new-code"]
    assert browser.list.item(0).text() == "Other"


def test_keyboard_selection_does_not_accidentally_search(window):
    app, gui = window
    browser = gui._experimental_shell.subject_browser
    searches = []
    gui.search_button.clicked.disconnect()
    gui.search_button.clicked.connect(lambda: searches.append(True))
    browser.search.setText("chem")
    browser.search.setFocus()
    QTest.keyClick(browser.search, Qt.Key.Key_Down)
    assert gui.focusWidget() is browser.list
    QTest.keyClick(browser.list, Qt.Key.Key_Return)
    assert gui.subject_code == "0620"
    assert searches == []
    QTest.keyClick(browser.list, Qt.Key.Key_Up)
    assert gui.focusWidget() is browser.search
    QTest.keyClick(browser.search, Qt.Key.Key_Escape)
    assert len(browser.visible_codes()) == 11
    gui.search_button.setFocus()
    QTest.keyClick(gui.search_button, Qt.Key.Key_Return)
    assert searches == [True]


@pytest.mark.parametrize("size", DESKTOP_SIZES)
@pytest.mark.parametrize("mode", ["list", "grid"])
@pytest.mark.parametrize("long_metadata", [False, True])
def test_desktop_resizing_keeps_all_actions_inside_cards(
    window, size, mode, long_metadata
):
    app, gui = window
    gui._set_results_view_mode(mode, persist=False, rerender=False)
    papers = groups(7)
    if long_metadata:
        for group in papers:
            group.source = "educational-archive-with-a-long-document-identifier-" * 3
    gui.display_results(papers, record_history=False)
    for current in [(1920, 1080), size, (1280, 800), size]:
        gui.resize(*current)
        pump(app)
    assert gui.size().width() == size[0]
    assert gui.results_panel.width() > gui.search_panel.width()
    if size[0] >= 1280:
        assert 340 <= gui.search_panel.width() <= 440
    else:
        assert 280 <= gui.search_panel.width() <= 340
    assert gui.results_scroll.horizontalScrollBar().maximum() == 0
    assert gui.results_container.width() <= gui.results_scroll.viewport().width()
    assert local_rect(gui.search_button, gui).bottom() < gui.height()
    cards = [
        card
        for card in gui.results_container.findChildren(QFrame)
        if card.property("themeRole") == "resultCard" and card.isVisibleTo(gui)
    ]
    assert cards
    for card in cards:
        actions = card._experimental_actions
        assert isinstance(actions, ResponsiveActions)
        assert card.rect().contains(local_rect(actions, card)), (
            size,
            mode,
            card.size(),
            local_rect(actions, card),
        )
        buttons = card.findChildren(QPushButton)
        for button in buttons:
            rect = local_rect(button, card)
            assert card.rect().contains(rect), (size, mode, card.size(), rect)
            assert button.width() >= button.minimumWidth() >= 84
            assert button.height() >= 36
        for i, first in enumerate(buttons):
            for second in buttons[i + 1 :]:
                assert not local_rect(first, card).intersects(local_rect(second, card))
        for label in card.findChildren(QLabel):
            assert not local_rect(label, card).intersects(local_rect(actions, card)), (
                size,
                mode,
                label.text(),
            )
            if label.wordWrap():
                assert label.height() >= label.heightForWidth(label.width())
    shell = gui._experimental_shell
    for control in [shell.results_actions, shell.results_heading]:
        assert gui.results_panel.rect().contains(local_rect(control, gui.results_panel))
    assert not local_rect(shell.results_actions, gui.results_panel).intersects(
        local_rect(shell.results_heading, gui.results_panel)
    )
    assert gui.launch_exam_btn.height() >= 44


@pytest.mark.parametrize("width", [800, 1280, 1920])
def test_history_long_entries_and_last_card_fit_after_resizing(
    window, monkeypatch, width
):
    app, gui = window
    attempts = [
        {
            "subject_code": "0417",
            "subject_name": "Information and Communication Technology (ICT)",
            "attempt_key": f"long-document-{i}",
            "question_paper_code": "0417_s24_qp_11_very-long-document-identifier.pdf",
            "component": "11",
            "year": "2024",
            "series": "MJ",
            "saved_at": "2026-10-03T10:00:00",
            "answers": {"1": "A"},
            "question_ids": ["1", "2", "3", "4"],
        }
        for i in range(15)
    ]
    monkeypatch.setattr(
        gui,
        "_format_attempt_question_paper_code",
        lambda attempt: attempt["question_paper_code"],
    )
    monkeypatch.setattr(
        "Core.gui_main.ExamAttemptManager.list_attempts", lambda: attempts
    )
    monkeypatch.setattr("Core.gui_main.HistoryManager.get_history", lambda: [])
    gui.refresh_history()
    gui.control_center_tabs.setCurrentIndex(1)
    gui.resize(width, 800)
    pump(app)
    gui.resize(1920, 1080)
    pump(app)
    gui.resize(width, 800)
    pump(app)
    viewport = gui.history_list.viewport()
    for i in range(gui.history_list.count()):
        item = gui.history_list.item(i)
        card = gui.history_list.itemWidget(item)
        item_rect = gui.history_list.visualItemRect(item)
        assert item_rect.left() >= 0 and item_rect.right() < viewport.width()
        assert card.width() <= viewport.width() - 2 * gui.history_list.spacing()
        assert card.height() >= card.layout().totalSizeHint().height()
        for label in card.findChildren(ElidedLabel):
            assert label.toolTip() == label.text()
            assert card.rect().contains(local_rect(label, card))
        for bar in card.findChildren(QProgressBar):
            assert card.rect().contains(local_rect(bar, card))
    gui.history_list.scrollToBottom()
    pump(app)
    last = gui.history_list.item(gui.history_list.count() - 1)
    assert viewport.rect().contains(gui.history_list.visualItemRect(last))
    gui.history_list.setCurrentRow(0)
    pump(app)
    assert (
        gui.history_list.itemWidget(gui.history_list.item(0)).property("selected")
        is True
    )


def test_application_owns_one_static_canvas_and_first_pass_is_available(
    window, monkeypatch
):
    from UI.theme import get_theme_manager

    app, gui = window
    assert isinstance(gui._experimental_shell, StudioMainShell)
    canvas = gui._central_widget
    assert isinstance(canvas, StaticThemeSurface) and canvas._application_canvas
    manager = get_theme_manager()
    for theme in ["Archive Blue", "Synthwave '84", "Coffee Shop", "Carbon Fiber"]:
        manager.apply_theme(app, theme)
        pump(app)
        first = canvas._render_count
        assert canvas._background is not None
        assert gui.results_container._background is None
        gui.grab()
        gui.grab()
        pump(app)
        assert canvas._render_count == first
        assert not canvas.findChildren(
            QTimer, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
    from UI.studio_main_shell import create_main_shell, main_canvas_enabled

    monkeypatch.setenv("PPF_STUDIO_GUI", "0")
    assert not main_canvas_enabled()
    monkeypatch.setenv("PPF_EXPERIMENTAL_MAIN_GUI", "0")
    assert create_main_shell(gui) is None
