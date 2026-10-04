import json
import pytest
from Utils.gui_utils import ConfigManager
from UI.theme import get_theme_manager

@pytest.mark.parametrize("old_theme", ["Default", "Legacy", "Tetris", "RGB", "Crimson Meridian", "not a theme"])
def test_old_theme_config_migrates_without_rewriting_saved_data(monkeypatch, tmp_path, old_theme):
    path = tmp_path / "config.json"
    original = {"default_level": "O Level", "ui": {"theme": old_theme, "animations_enabled": True,
                "theme_animations": {old_theme: True}, "sound_enabled": False}}
    path.write_text(json.dumps(original))
    monkeypatch.setattr(ConfigManager, "CONFIG_FILE", str(path))
    loaded = ConfigManager.load_config()
    assert loaded["default_level"] == "IGCSE"
    assert loaded["ui"]["theme"] == "Archive Blue"
    assert "theme_animations" not in loaded["ui"]
    assert "animations_enabled" not in loaded["ui"]
    assert loaded["ui"]["sound_enabled"] is False
    assert json.loads(path.read_text()) == original

@pytest.mark.parametrize("name", get_theme_manager().theme_names())
def test_retained_theme_persistence(monkeypatch, tmp_path, name):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"default_level": "AS/A Level", "ui": {"theme": name}}))
    monkeypatch.setattr(ConfigManager, "CONFIG_FILE", str(path))
    assert ConfigManager.load_config()["ui"]["theme"] == name
    assert ConfigManager.load_config()["default_level"] == "A Level"


@pytest.mark.parametrize('legacy,current', [('Matrix Green', 'Cipher Green'),
    ('Matrix Red', 'Cipher Red'), ('Matrix Purple', 'Cipher Purple'), ('Matrix Rain', 'Cipher Green')])
def test_renamed_cipher_theme_preferences_migrate_without_rewriting_files(monkeypatch, tmp_path, legacy, current):
    path = tmp_path / 'config.json'
    original = {'ui': {'theme': legacy}}
    path.write_text(json.dumps(original))
    monkeypatch.setattr(ConfigManager, 'CONFIG_FILE', str(path))
    assert ConfigManager.load_config()['ui']['theme'] == current
    assert get_theme_manager().get_theme_tokens(legacy) == get_theme_manager().get_theme_tokens(current)
    assert legacy not in get_theme_manager().theme_names()
    assert json.loads(path.read_text()) == original


def test_legacy_alias_keeps_palette_and_migrates_custom_base(tmp_path, monkeypatch):
    from UI.theme import ThemeManager
    manager = get_theme_manager()
    assert 'Legacy' not in manager.theme_names()
    assert manager._resolve_theme_name('Legacy') == 'Archive Blue'
    assert manager.get_theme_tokens('Legacy') == manager.get_theme_tokens('Archive Blue')
    assert manager.get_theme_tokens('Default') == manager.get_theme_tokens('Archive Blue')
    monkeypatch.setattr(ThemeManager, 'CUSTOM_THEMES_FILE', tmp_path / 'themes.json')
    custom = ThemeManager()
    assert custom.save_custom_theme('Old Study Theme', {'QWidget': '#123456'}, base_theme='Legacy')
    assert ThemeManager()._custom_entry('Old Study Theme')['base_theme'] == 'Archive Blue'
    assert not custom.save_custom_theme('Legacy', {'QWidget': '#123456'})
