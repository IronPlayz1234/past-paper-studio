import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from UI.floating_settings_window import FloatingSettingsWindow
from UI.theme import get_theme_manager


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_scale_toggle_emits_callback_when_user_toggles():
    _app()
    captured = []
    window = FloatingSettingsWindow(on_scale_toggled=lambda enabled: captured.append(bool(enabled)))
    window.set_scale_control_state(True, visible=True)
    window.set_scale_enabled(True)

    window.scale_toggle.setChecked(False)
    window.scale_toggle.setChecked(True)

    assert captured == [False, True]


def test_system_accent_toggle_emits_callback_when_user_toggles():
    _app()
    captured = []
    window = FloatingSettingsWindow(on_system_accent_toggled=lambda enabled: captured.append(bool(enabled)))
    window.set_system_accent_control_state(True, visible=True)
    window.set_system_accent_enabled(False)

    window.system_accent_toggle.setChecked(True)
    window.system_accent_toggle.setChecked(False)

    assert captured == [True, False]


def test_sound_toggle_emits_callback_when_user_toggles():
    _app()
    captured = []
    window = FloatingSettingsWindow(on_sound_toggled=lambda enabled: captured.append(bool(enabled)))
    window.set_sound_control_state(True, visible=True)
    window.set_sound_enabled(True)

    window.sound_toggle.setChecked(False)
    window.sound_toggle.setChecked(True)

    assert captured == [False, True]


def test_answer_panel_position_is_removed_and_compatibility_setters_are_safe():
    _app()
    captured = []
    window = FloatingSettingsWindow(
        on_answer_panel_position_changed=lambda position: captured.append(str(position)),
    )
    window.set_answer_panel_position_control_state(True, visible=True)
    window.set_answer_panel_position("bottom")

    assert window.answer_panel_position_combo is None
    assert window.answer_panel_position_pref_label is None
    assert captured == []


def test_theme_card_click_emits_theme_selection():
    _app()
    captured = []
    window = FloatingSettingsWindow(on_theme_selected=lambda theme: captured.append(str(theme)))
    window.set_theme_names(["Archive Blue", "Coffee Shop"])
    window.set_selected_theme("Archive Blue")

    window._on_theme_card_clicked("Coffee Shop")

    assert captured == ["Coffee Shop"]


def test_settings_docs_requested_does_not_emit_user_hidden():
    app = _app()
    docs_events = []
    hidden_events = []
    window = FloatingSettingsWindow(
        on_docs_requested=lambda: docs_events.append("docs"),
        on_user_hidden=lambda: hidden_events.append("hidden"),
    )
    window.show()
    app.processEvents()

    window._open_docs()
    app.processEvents()

    assert docs_events == ["docs"]
    assert hidden_events == []


def test_settings_manual_hide_emits_user_hidden():
    app = _app()
    hidden_events = []
    window = FloatingSettingsWindow(on_user_hidden=lambda: hidden_events.append("hidden"))
    window.show()
    app.processEvents()

    window.hide()
    app.processEvents()

    assert hidden_events == ["hidden"]


def test_settings_theme_gallery_has_thirty_one_builtins_with_creator_opt_in():
    _app()
    window = FloatingSettingsWindow()
    window.set_theme_names(get_theme_manager().theme_names())
    assert len(window._theme_cards) == 31
    assert "tetris" not in window._theme_cards
    assert "custom theme creator" not in window._theme_cards
    window.custom_theme_creator_toggle.setChecked(True)
    assert len(window._theme_cards) == 32
    assert "custom theme creator" in window._theme_cards


def test_toggle_switch_clicks_on_right_side_can_turn_it_off():
    app = _app()
    window = FloatingSettingsWindow()
    window.set_sound_control_state(True, visible=True)
    window.show()
    app.processEvents()

    toggle = window.sound_toggle
    toggle.setChecked(False)
    app.processEvents()
    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(toggle.width() - 4, toggle.height() // 2))
    app.processEvents()
    assert toggle.isChecked() is True

    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(toggle.width() - 4, toggle.height() // 2))
    app.processEvents()
    assert toggle.isChecked() is False


def test_settings_window_has_no_lite_mode_controls():
    _app()
    window = FloatingSettingsWindow()
    attrs = dir(window)
    assert not any("lite" in name.lower() for name in attrs)


def test_header_toggles_do_not_overlap_at_narrow_width():
    app = _app()
    window = FloatingSettingsWindow()
    window.set_sound_control_state(True, visible=True)
    window.set_scale_control_state(True, visible=True)
    window.set_system_accent_control_state(True, visible=True)
    window.resize(420, 420)
    window.show()
    app.processEvents()

    anim_rect = window.sound_toggle.geometry()
    scale_rect = window.scale_toggle.geometry()
    accent_rect = window.system_accent_toggle.geometry()
    assert not anim_rect.intersects(scale_rect)
    assert not anim_rect.intersects(accent_rect)
    assert not scale_rect.intersects(accent_rect)


def test_theme_gallery_sections_render_in_required_order():
    _app()
    window = FloatingSettingsWindow()
    window.set_preferences(show_startup_animation=True, full_screen_on_startup=True, custom_theme_creator_enabled=True)
    window.set_theme_names(get_theme_manager().theme_names())
    assert window.theme_section_titles() == ["Classic", "Solid Colors", "Signature Themes", "Custom"]


def test_theme_gallery_section_card_order_matches_required_spec():
    _app()
    window = FloatingSettingsWindow()
    window.set_preferences(show_startup_animation=True, full_screen_on_startup=True, custom_theme_creator_enabled=True)
    names = get_theme_manager().theme_names()
    window.set_theme_names(names)
    assert window.theme_names_for_section("Classic") == names[:5]
    assert window.theme_names_for_section("Signature Themes") == names[5:16]
    assert window.theme_names_for_section("Solid Colors") == names[16:31]
    assert window.theme_names_for_section("Custom")[0] == "Custom Theme Creator"


def test_theme_search_filters_live_and_restores_full_gallery():
    app = _app()
    window = FloatingSettingsWindow()
    manager = get_theme_manager()
    window.set_theme_names(list(manager.THEMES.keys()))
    window.nav_list.setCurrentRow(1)
    window.show()
    app.processEvents()

    window.theme_search_input.setText("cOffe")
    app.processEvents()
    visible_after_partial = sorted(card.theme_name() for card in window._theme_cards.values() if not card.isHidden())
    assert visible_after_partial == ["Coffee Shop"]
    assert window.theme_empty_state_label.isHidden() is True

    window.theme_search_input.setText("does-not-exist")
    app.processEvents()
    visible_after_none = [card.theme_name() for card in window._theme_cards.values() if not card.isHidden()]
    assert visible_after_none == []
    assert window.theme_empty_state_label.isHidden() is False

    window.theme_search_input.clear()
    app.processEvents()
    visible_after_clear = [card.theme_name() for card in window._theme_cards.values() if not card.isHidden()]
    assert len(visible_after_clear) == len(window._theme_cards)
    assert window.theme_empty_state_label.isHidden() is True


def test_theme_card_swatches_reflect_mapped_primary_and_secondary_colors():
    _app()
    window = FloatingSettingsWindow()
    window.set_theme_names(["Violet Afterburn"])
    card = window._theme_cards["violet afterburn"]
    tokens = get_theme_manager().get_theme_tokens("Violet Afterburn")
    assert tokens["PRIMARY"].lower() in card._primary_swatch.styleSheet().lower()
    assert tokens["SECONDARY"].lower() in card._secondary_swatch.styleSheet().lower()


def test_removed_themes_are_not_shown_even_if_passed_to_gallery():
    _app()
    window = FloatingSettingsWindow()
    window.set_theme_names(["Tetris", "RGB", "Archive Blue"])
    assert "tetris" not in window._theme_cards
    assert "rgb" not in window._theme_cards
    assert "archive blue" in window._theme_cards


def test_selected_theme_card_remains_visible_and_emphasized_with_search():
    app = _app()
    window = FloatingSettingsWindow()
    manager = get_theme_manager()
    window.set_theme_names(list(manager.THEMES.keys()))
    window.nav_list.setCurrentRow(1)
    window.show()
    app.processEvents()
    window.set_selected_theme("Violet Afterburn")

    window.theme_search_input.setText("violet")
    app.processEvents()
    crimson_card = window._theme_cards["violet afterburn"]
    assert crimson_card.isHidden() is False
    assert "2px solid" in crimson_card.styleSheet()

    window.theme_search_input.setText("archive")
    app.processEvents()
    assert window._selected_theme_text() == "Archive Blue"


def test_flow_layout_centers_theme_rows_including_incomplete_last_row():
    app = _app()
    window = FloatingSettingsWindow()
    core_cards = get_theme_manager().theme_names()[5:13]
    window.resize(760, 700)
    window.set_theme_names(core_cards)
    window.nav_list.setCurrentRow(1)
    window.show()
    app.processEvents()

    cards = [window._theme_cards[name.casefold()] for name in core_cards]
    rows = {}
    for card in cards:
        rows.setdefault(card.geometry().y(), []).append(card)
    ordered_rows = [sorted(row, key=lambda widget: widget.geometry().x()) for _, row in sorted(rows.items())]

    assert len(ordered_rows) >= 2
    first_row = ordered_rows[0]
    last_row = ordered_rows[-1]
    assert first_row[0].geometry().x() > 0
    if len(last_row) < len(first_row):
        assert last_row[0].geometry().x() > first_row[0].geometry().x()


@pytest.mark.parametrize("theme", ["Simple Light", "Archive Blue", "Matcha Latte", "Old Library"])
@pytest.mark.parametrize("size", [(760, 520), (900, 640)])
def test_general_footer_remains_visible_without_crowding_controls(theme, size):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QLabel

    app = _app()
    manager = get_theme_manager()
    previous_theme = manager.current_theme()
    window = FloatingSettingsWindow()
    try:
        manager.apply_theme(app, theme)
        window.apply_runtime_theme()
        window.set_scale_control_state(True, visible=True)
        window.resize(*size)
        window.show()
        app.processEvents()

        notice = window.sourcing_notice_label
        footer_top = notice.mapTo(window.general_page, QPoint(0, 0))
        assert window.general_page.rect().contains(footer_top)
        assert window.general_page.rect().contains(
            footer_top + QPoint(notice.width() - 1, notice.height() - 1)
        )
        assert notice.height() >= notice.heightForWidth(notice.width())

        body = window.general_scroll_area.widget()
        prefs = window.sound_toggle.parentWidget()
        actions = next(label for label in body.findChildren(QLabel) if label.text() == "Actions")
        assert actions.mapTo(body, QPoint(0, 0)).y() > prefs.geometry().bottom()
        toggles = [window.sound_toggle, window.scale_toggle, window.system_accent_toggle]
        assert all(prefs.rect().contains(toggle.geometry()) for toggle in toggles)
        assert all(not first.geometry().intersects(second.geometry())
                   for i, first in enumerate(toggles) for second in toggles[i + 1:])

        window.general_scroll_area.ensureWidgetVisible(window.ai_config_btn)
        app.processEvents()
        viewport = window.general_scroll_area.viewport()
        button_top = window.ai_config_btn.mapTo(viewport, QPoint(0, 0))
        assert viewport.rect().contains(button_top)
        assert viewport.rect().contains(
            button_top + QPoint(window.ai_config_btn.width() - 1, window.ai_config_btn.height() - 1)
        )
    finally:
        window.hide()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        manager.apply_theme(app, previous_theme)
        app.processEvents()
