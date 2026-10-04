"""Persistent local profiles, live presentation, and header/navigation regression checks."""
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QLabel, QPushButton, QFrame
from Tests.test_study_dashboard import app, main, study_store, snapshot, pump, wait_for
from Core.study_history import StudyHistory
from Utils.gui_utils import ConfigManager
from UI.profile_controls import get_profile, Profile, ProfileEditor
from UI.localization import get_locale_manager, tr


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(tmp_path/'config.json'))
    monkeypatch.setattr(ConfigManager, '_CACHE', None)
    monkeypatch.setattr(ConfigManager, '_CACHE_SIGNATURE', None)
    monkeypatch.setattr('UI.profile_controls.user_data_path', lambda name: tmp_path/name)
    yield


def test_name_persists_and_greeting_and_menu_update_live(main, app):
    editor = ProfileEditor(); editor.show()
    editor.name_input.setText('Sohan'); editor.name_input.textEdited.emit('Sohan')
    pump(app,.25)
    assert Profile().name() == 'Sohan'
    assert main._profile_header.menu_name.text() == 'Sohan'
    assert any('Sohan' in label.text() for label in main._dashboard.home.findChildren(QLabel,'dashboardGreeting'))
    editor.name_input.setText(''); editor.save_name(); pump(app)
    assert main._profile_header.menu_name.text() == 'Student'
    assert all(',' not in label.text() for label in main._dashboard.home.findChildren(QLabel,'dashboardGreeting') if label.isVisible())
    editor.close(); editor.deleteLater()


def test_avatar_single_managed_copy_persists_crops_and_removes(main, app, tmp_path):
    source = tmp_path/'wide.png'
    image=QImage(1200,600,QImage.Format.Format_ARGB32); image.fill(QColor('#aa6644')); image.save(str(source))
    get_profile().set_image(source); pump(app)
    saved=Path(Profile().image_path())
    assert saved != source and saved.is_file()
    copy=QImage(str(saved)); assert copy.width()==512 and copy.height()==256
    assert not main._profile_header.avatar._pixmap.isNull()
    get_profile().set_image(source)
    assert len(list(tmp_path.glob('profile_avatar*')))==1
    get_profile().remove_image(); pump(app)
    assert source.is_file() and not saved.exists()
    assert main._profile_header.avatar._pixmap.isNull()
    ConfigManager.set_value('profile.avatar_path',str(tmp_path/'missing.png'))
    main._profile_header.avatar.reload()
    assert main._profile_header.avatar._pixmap.isNull()


def test_invalid_avatar_keeps_previous_image(main, tmp_path):
    source=tmp_path/'valid.png'; image=QImage(16,16,QImage.Format.Format_RGB32);image.fill(Qt.GlobalColor.red);image.save(str(source))
    get_profile().set_image(source); original=Path(Profile().image_path()).read_bytes()
    invalid=tmp_path/'broken.png';invalid.write_text('not an image')
    with pytest.raises(ValueError): get_profile().set_image(invalid)
    assert Path(Profile().image_path()).read_bytes()==original


def test_navigation_always_returns_to_empty_results_and_retains_filters(main, app):
    main.year_entry.setText('2024'); main.component_entry.setText('42')
    controller=main._dashboard
    buttons=[b for b in controller.home.findChildren(QPushButton) if b.text()==tr('Back to results') and b.isVisible()]
    assert len(buttons)==1; buttons[0].click();pump(app)
    assert controller.stack.currentWidget() is main.results_scroll
    assert controller.home_button.isVisible()
    assert main.year_entry.text()=='2024' and main.component_entry.text()=='42'
    controller.home_button.click();pump(app)
    assert controller.stack.currentWidget() is controller.home


@pytest.mark.parametrize('width',[800,1050,1440,1920])
def test_centered_exam_selector_logo_and_profile_layout(main, app, width):
    main.resize(width,900);pump(app)
    header=main._profile_header
    assert not main.settings_btn.isVisibleTo(main)
    assert header.logo.isVisible() and header.control.isVisible()
    assert header.layout.itemAtPosition(0,1).widget() is main.level_selector_card
    assert abs(main.level_selector_card.geometry().center().x()-header.rect().center().x())<=3
    assert header.logo.geometry().right()<main.level_selector_card.geometry().left()
    main.alevel_level_btn.click();pump(app)
    assert main.current_level=='A Level'
    main.igcse_level_btn.click();pump(app)
    assert main.current_level=='IGCSE'


@pytest.mark.parametrize('theme',['Coffee Shop','Old Library','Matcha Latte','Violet Afterburn','Crimson Meridian','Solid Teal','OLED Light','OLED Dark'])
def test_theme_language_and_subject_accents_after_profile_update(main, app, theme):
    get_profile().set_name('Sohan')
    main.on_theme_changed_by_user(theme);pump(app)
    get_locale_manager(app).set_language('fr');pump(app)
    assert main._profile_header.settings_action.text()==tr('Open Settings')
    assert main._profile_header.menu_name.text()=='Sohan'
    assert main._profile_header.logo.grab().width()>0
    StudyHistory.record(snapshot(),'completed');main._dashboard.refresh();wait_for(app,lambda: main._dashboard._future is None)
    cards=main._dashboard.home.findChildren(QLabel,'metricValue')
    assert any(label.text()=='1' for label in cards)
    assert all(label.parentWidget().height() >= 110 for label in cards if label.isVisible())
    assert any('border-left:3px' in card.styleSheet() for card in main._dashboard.home.findChildren(QFrame))


def test_profile_menu_opens_settings_and_long_names_stay_plain_text(main, app):
    get_profile().set_name('<b>Sohan</b>'+'x'*70)
    assert len(get_profile().name())==80
    header=main._profile_header
    assert header.menu_name.textFormat()==Qt.TextFormat.PlainText
    header.settings_action.trigger();pump(app)
    assert main._settings_window.isVisible()
    assert main._settings_window.profile_editor.name_input.text()==get_profile().name()
    get_locale_manager(app).set_language('es');pump(app)
    assert main._settings_window.profile_editor.name_input.placeholderText()==tr('Your name')
    assert main._settings_window.profile_editor.name_input.text()==get_profile().name()
    main._settings_window.hide()
