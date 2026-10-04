"""Offline pack creation; called only by a background task."""
from datetime import datetime
from pathlib import Path
import tempfile
from Core.atomic_storage import atomic_write_text
from Core.download_service import download_file, safe_filename


def build_offline_pack(parent, items, cancel_event=None):
    directory = Path(tempfile.mkdtemp(prefix='offline_revision_pack_' + datetime.now().strftime('%Y%m%d_'), dir=parent))
    saved, failures, names = [], [], set()
    for item in items:
        if cancel_event is not None and cancel_event.is_set():
            failures.append("Pack cancelled; remaining files were not downloaded.")
            break
        url = str(item.get('download_url') or item.get('direct_url') or item.get('url') or '')
        name = safe_filename(item.get('filename'))
        base = Path(name)
        number = 1
        while name.casefold() in names:
            name = f'{base.stem} ({number}){base.suffix}'
            number += 1
        names.add(name.casefold())
        try:
            download_file(url, directory/name, cancel=cancel_event)
            saved.append(name)
        except Exception as exc:
            failures.append(f'{name}: {exc}')
    manifest = '# Offline Revision Pack\n\n' + '\n'.join(f'- {name}' for name in saved)
    if failures:
        manifest += '\n\n## Failed downloads\n\n' + '\n'.join(f'- {line}' for line in failures)
    atomic_write_text(directory/'manifest.md', manifest+'\n')
    return str(directory), len(saved), failures
