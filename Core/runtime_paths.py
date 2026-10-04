"""Runtime-safe path helpers for source and packaged executable modes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from Core.cache_tools import synchronized

_RESOURCE_BASE_ENV = "PAST_PAPER_FINDER_RESOURCE_BASE"


def _path_from_env(var_name: str) -> Path | None:
    raw = str(os.environ.get(var_name, "") or "").strip()
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser().resolve()
    except Exception:
        candidate = Path(raw)
    return candidate if candidate.exists() else None


def app_base_path() -> Path:
    """Return the base path used to resolve bundled resources."""
    env_base = _path_from_env(_RESOURCE_BASE_ENV)
    if env_base is not None:
        return env_base

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            return Path(str(meipass)).resolve()
        except Exception:
            return Path(str(meipass))

    if getattr(sys, "frozen", False):
        executable = str(getattr(sys, "executable", "") or "").strip()
        if executable:
            try:
                exe_path = Path(executable).resolve()
            except Exception:
                exe_path = Path(executable)

            macos_dir = exe_path.parent
            if sys.platform == "darwin":
                contents_dir = macos_dir.parent if macos_dir.name == "MacOS" else None
                if contents_dir and contents_dir.name == "Contents":
                    resources_dir = contents_dir / "Resources"
                    if resources_dir.exists():
                        return resources_dir
                    if macos_dir.exists():
                        return macos_dir
            return macos_dir

    # In source mode this module lives under Core/, so move one level up.
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> str:
    """Resolve a resource path for both script and PyInstaller builds."""
    base = app_base_path()
    if not parts:
        return str(base)

    clean_parts = [str(part) for part in parts if str(part)]
    if not clean_parts:
        return str(base)

    try:
        return str(base.joinpath(*clean_parts).resolve())
    except Exception:
        return str(base.joinpath(*clean_parts))


def path_exists(*parts: str) -> bool:
    """Fast helper for runtime resource existence checks."""
    return os.path.exists(resource_path(*parts))


def _writable_root(*, cache: bool = False) -> Path:
    """Stable locations independent of cwd, app bundle and executable extraction."""
    override = os.environ.get('PAST_PAPER_FINDER_CACHE_DIR' if cache else 'PAST_PAPER_FINDER_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    from PySide6.QtCore import QStandardPaths
    kind = QStandardPaths.StandardLocation.GenericCacheLocation if cache else QStandardPaths.StandardLocation.GenericDataLocation
    root = QStandardPaths.writableLocation(kind)
    if not root:
        raise OSError('No writable application data location is available')
    return Path(root) / 'PastPaperFinder'


def user_data_path(*parts: str) -> str:
    return str(_writable_root().joinpath(*parts))


def cache_path(*parts: str) -> str:
    return str(_writable_root(cache=True).joinpath(*parts))


def settings_env_path() -> str:
    return user_data_path('settings.env')


@synchronized
def migrate_legacy_data() -> None:
    """Copy once; preserve the original files and any existing destination data."""
    if os.environ.get('PAST_PAPER_FINDER_DATA_DIR') or getattr(sys, 'frozen', False):
        return
    import shutil
    import logging
    root = _writable_root()
    marker = root / '.legacy-migrated'
    if marker.exists():
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        names = ('past_paper_finder_config.json', 'paper_search_history.json',
                 'unfinished_exam_attempts.json', 'unfinished_exam_attempts.backup.json', 'custom_themes.json')
        bases = [app_base_path() / 'Data', app_base_path() / 'Core' / 'Data']
        for name in names:
            target = root / name
            candidates = [base/name for base in bases if (base/name).is_file()]
            if candidates and not target.exists():
                source = max(candidates, key=lambda p: p.stat().st_mtime_ns)
                shutil.copy2(source, target)
        for base in bases:
            assets = base / 'attempt_assets'
            if assets.is_dir():
                for source in assets.rglob('*'):
                    if source.is_file():
                        target = root / 'attempt_assets' / source.relative_to(assets)
                        if not target.exists():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, target)
        import json
        from Core.atomic_storage import atomic_write_json
        def relocate(value):
            if isinstance(value, dict):
                return {key: relocate(item) for key, item in value.items()}
            if isinstance(value, list):
                return [relocate(item) for item in value]
            if isinstance(value, str):
                normalized = value.replace('\\', '/')
                marker_text = 'attempt_assets/'
                if marker_text in normalized:
                    relative = normalized.split(marker_text, 1)[1]
                    target = (root / 'attempt_assets' / relative).resolve()
                    if target.is_relative_to(root / 'attempt_assets') and target.is_file():
                        return str(target)
            return value
        for name in ('unfinished_exam_attempts.json', 'unfinished_exam_attempts.backup.json'):
            target = root / name
            if target.is_file():
                try:
                    original = json.loads(target.read_text(encoding='utf-8'))
                    relocated = relocate(original)
                    if original != relocated:
                        atomic_write_json(target, relocated)
                except (ValueError, TypeError):
                    pass  # The normal recovery path handles damaged snapshots.
        env_candidates = [app_base_path() / '.env', app_base_path() / 'Core' / '.env']
        existing_env = [path for path in env_candidates if path.is_file()]
        env = max(existing_env, key=lambda p: p.stat().st_mtime_ns) if existing_env else env_candidates[0]
        target_env = Path(settings_env_path())
        if env.is_file() and not target_env.exists():
            shutil.copy2(env, target_env)
            target_env.chmod(0o600)
        marker.touch()
    except OSError:
        logging.getLogger(__name__).exception('Could not migrate legacy application data')
        raise
