"""Validated, bounded downloads with atomic publication and owned temporary files."""
from __future__ import annotations
import atexit
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit
import requests
from Core.background_tasks import run_io

_TEMP = None
_TEMP_LOCK = threading.Lock()
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024


def temp_directory():
    global _TEMP
    with _TEMP_LOCK:
        if _TEMP is None:
            _TEMP = tempfile.TemporaryDirectory(prefix='past-paper-finder-')
        return _TEMP.name


def cleanup_temporary_downloads():
    global _TEMP
    with _TEMP_LOCK:
        directory, _TEMP = _TEMP, None
    if directory:
        directory.cleanup()

atexit.register(cleanup_temporary_downloads)


def remove_owned_temporary_file(path):
    """Never delete a caller's local paper or exported download."""
    if not path or _TEMP is None:
        return
    candidate = Path(path).resolve()
    root = Path(_TEMP.name).resolve()
    if candidate.parent != root:
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        # Windows may still hold a native PDF handle; the service cleans up at exit.
        pass


def safe_filename(value, default='paper.pdf'):
    name = unquote(str(value or '')).replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
    if not name:
        name = default
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        name = '_' + name
    stem, extension = os.path.splitext(name)
    return stem[:150] + extension[:12]


def validate_payload(prefix, expected_extension, content_type=''):
    sample = bytes(prefix).lstrip()
    lower = sample.lower()
    if not sample or lower.startswith((b'<!doctype', b'<html', b'<?xml')):
        raise ValueError('The server returned an empty file or error page')
    extension = str(expected_extension).lower().lstrip('.')
    if extension == 'pdf' and not sample.startswith(b'%PDF-'):
        raise ValueError('The response is not a PDF document')
    if extension == 'zip' and not sample.startswith(b'PK'):
        raise ValueError('The response is not a ZIP archive')
    if extension in {'mp3','wav'} and str(content_type).lower().startswith('text/'):
        raise ValueError('The response is not audio')


def _download(url, destination, *, cancel=None, expected_extension=None, timeout=90, request=None):
    if urlsplit(str(url)).scheme.lower() not in {'http','https'}:
        raise ValueError('A valid HTTP(S) download URL is required')
    if cancel is not None and cancel.is_set():
        raise InterruptedError('Download cancelled')
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    response = None
    started = time.monotonic()
    try:
        response = (request or requests.get)(url, timeout=(5, 15), stream=True)
        if int(response.status_code) != 200:
            raise OSError(f'HTTP {response.status_code}')
        headers = getattr(response, 'headers', {})
        size_header = headers.get('Content-Length', headers.get('content-length'))
        expected_size = int(size_header) if str(size_header or '').isdigit() else None
        if expected_size is not None and expected_size > MAX_DOWNLOAD_BYTES:
            raise ValueError('Download exceeds the 128 MB limit')
        prefix = b''
        size = 0
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.part', delete=False) as handle:
            temporary = handle.name
            chunks = response.iter_content(64*1024) if hasattr(response, 'iter_content') else [response.content]
            for chunk in chunks:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('Download cancelled')
                if time.monotonic()-started > timeout:
                    raise TimeoutError('Download exceeded its time limit')
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ValueError('Download exceeds the 128 MB limit')
                if len(prefix) < 4096:
                    prefix += chunk[:4096-len(prefix)]
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if cancel is not None and cancel.is_set():
            raise InterruptedError('Download cancelled')
        encoding = headers.get('Content-Encoding', headers.get('content-encoding', ''))
        if expected_size is not None and not encoding and size != expected_size:
            raise ValueError('Download was incomplete')
        validate_payload(prefix, expected_extension or target.suffix, headers.get('Content-Type', headers.get('content-type','')))
        os.replace(temporary, target)
        temporary = None
        return str(target)
    finally:
        if response is not None and hasattr(response, 'close'):
            response.close()
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def download_file(url, destination, **kwargs):
    cancel = kwargs.pop('cancel', None) or threading.Event()
    return run_io(
                      lambda: _download(url, destination, cancel=cancel, **kwargs),
                      title='Downloading file…', cancel=cancel.set, wait_timeout=120)


def download_pdf(url, *, cancel=None):
    # Unique name for each request; only the service owns this path.
    import uuid
    target = Path(temp_directory()) / (uuid.uuid4().hex + '.pdf')
    return download_file(url, target, expected_extension='pdf', cancel=cancel)


def fetch_bytes(url, *, expected_extension='pdf', cancel=None):
    import uuid
    target = Path(temp_directory()) / (uuid.uuid4().hex + '.' + expected_extension)
    try:
        download_file(url, target, expected_extension=expected_extension, cancel=cancel)
        return target.read_bytes()
    finally:
        target.unlink(missing_ok=True)
