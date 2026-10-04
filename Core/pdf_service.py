"""A single process owns all PyMuPDF documents and performs PDF/OCR work.

Only plain data crosses the process boundary. Geometry objects are local values;
rendering, table detection and extraction always execute in the worker process.
"""
from __future__ import annotations
import atexit
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import wraps
import importlib
import math
import multiprocessing
from pathlib import Path
import threading
from types import SimpleNamespace
import uuid
import weakref

from fitz import Matrix, Rect
from Core.background_tasks import await_future

_POOL = None
_LOCK = threading.RLock()
_DOCUMENTS = {}  # Used exclusively inside the process.
_MAX_RENDER_PIXELS = 8_000_000


def _worker():
    return multiprocessing.current_process().name != 'MainProcess'


def _pool():
    global _POOL
    with _LOCK:
        if _POOL is None:
            _POOL = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
        return _POOL


def _dispatch(operation, args):
    import fitz
    if operation == 'open':
        positional, keywords = args
        document = fitz.open(*positional, **keywords)
        if document.needs_pass or len(document) == 0:
            document.close()
            raise ValueError('PDF is encrypted or has no pages')
        identity = uuid.uuid4().hex
        _DOCUMENTS[identity] = document
        return identity, len(document), document.name, [tuple(page.rect) for page in document]
    if operation == 'close':
        document = _DOCUMENTS.pop(args[0], None)
        if document is not None:
            document.close()
        return None
    if operation == 'call':
        module, qualname, positional, keywords = args
        function = importlib.import_module(module)
        for part in qualname.split('.'):
            function = getattr(function, part)
        return getattr(function, '__wrapped__', function)(*positional, **keywords)
    identity, index, positional, keywords = args
    document = _DOCUMENTS.get(identity)
    if document is None:
        raise ValueError('PDF document has been closed')
    page = document[index]
    if operation == 'rect':
        return tuple(page.rect)
    if operation == 'text':
        return page.get_text(*positional, **keywords)
    if operation == 'search':
        return [tuple(rect) for rect in page.search_for(*positional, **keywords)]
    if operation == 'tables':
        finder = page.find_tables(*positional, **keywords)
        return [dict(row_count=t.row_count, col_count=t.col_count, bbox=t.bbox,
                     rows=[list(row.cells) for row in t.rows], values=t.extract()) for t in finder.tables]
    if operation == 'render':
        limit = max(1, min(12_000_000, int(keywords.pop('max_pixels', _MAX_RENDER_PIXELS))))
        matrix = fitz.Matrix(*keywords.pop('matrix', (1, 0, 0, 1, 0, 0)))
        clip = keywords.get('clip')
        if clip is not None:
            keywords['clip'] = fitz.Rect(clip)
        area = fitz.Rect(clip) if clip is not None else page.rect
        transformed = area * matrix
        pixels = max(1, abs(transformed.width * transformed.height))
        if pixels > limit:
            matrix = matrix * fitz.Matrix(math.sqrt(limit/pixels), math.sqrt(limit/pixels))
        pixmap = page.get_pixmap(matrix=matrix, **keywords)
        return pixmap.width, pixmap.height, pixmap.stride, pixmap.n, pixmap.samples
    raise ValueError('Unknown PDF operation')


def _request(operation, args, *, show_progress=True):
    try:
        return await_future(_pool().submit(_dispatch, operation, args), 'Processing PDF…',
                            timeout=180, show_progress=show_progress)
    except (TimeoutError, BrokenProcessPool) as exc:
        shutdown_pdf_service(force=True)
        raise RuntimeError('PDF processing stopped. Reopen the document and try again.') from exc


def isolated_pdf(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if _worker():
            return function(*args, **kwargs)
        return _request('call', (function.__module__, function.__qualname__, args, kwargs))
    return wrapper


def _close_later(identity):
    pool = _POOL
    if pool is not None:
        try:
            pool.submit(_dispatch, 'close', (identity,))
        except RuntimeError:
            pass


class Document:
    def __init__(self, identity, count, name, page_rectangles):
        self.identity, self.page_count, self.name = identity, count, name
        self.page_rectangles = page_rectangles
        self.is_closed = False
        self._finalizer = weakref.finalize(self, _close_later, identity)
    def __len__(self):
        return self.page_count
    def __iter__(self):
        return (self[i] for i in range(len(self)))
    def __getitem__(self, index):
        if self.is_closed or not 0 <= index < self.page_count:
            raise ValueError('Invalid PDF page')
        return Page(self, index)
    def load_page(self, index):
        return self[index]
    def close(self):
        if not self.is_closed:
            self.is_closed = True
            self._finalizer()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.close()


class Page:
    def __init__(self, document, index):
        self.document, self.number = document, index
    def _call(self, operation, args=(), kwargs=None, *, show_progress=True):
        return _request(operation, (self.document.identity, self.number, args, dict(kwargs or {})), show_progress=show_progress)
    @property
    def rect(self):
        if self.document.is_closed:
            raise ValueError('PDF document has been closed')
        return Rect(self.document.page_rectangles[self.number])
    def get_text(self, *args, **kwargs):
        return self._call('text', args, kwargs)
    def search_for(self, *args, **kwargs):
        return [Rect(rect) for rect in self._call('search', args, kwargs)]
    def get_pixmap(self, *, matrix=None, clip=None, show_progress=True, **kwargs):
        if matrix is not None:
            kwargs['matrix'] = tuple(matrix)
        if clip is not None:
            kwargs['clip'] = tuple(clip)
        return Pixmap(*self._call('render', kwargs=kwargs, show_progress=show_progress))
    def find_tables(self, **kwargs):
        tables = []
        for record in self._call('tables', kwargs=kwargs):
            values = record.pop('values')
            rows = [SimpleNamespace(cells=cells) for cells in record.pop('rows')]
            tables.append(SimpleNamespace(**record, rows=rows, extract=lambda data=values: data))
        return SimpleNamespace(tables=tables)


class Pixmap:
    def __init__(self, width, height, stride, n, samples):
        self.width, self.height, self.stride, self.n, self.samples = width, height, stride, n, samples
    def save(self, path):
        from PIL import Image
        image = Image.frombytes('RGBA' if self.n == 4 else 'RGB', (self.width, self.height), self.samples)
        image.save(path)


def open(*args, **kwargs):
    if _worker():
        import fitz
        return fitz.open(*args, **kwargs)
    return Document(*_request('open', (args, kwargs)))


def shutdown_pdf_service(force=False):
    global _POOL
    with _LOCK:
        pool, _POOL = _POOL, None
    if pool is None:
        return
    if force:
        if hasattr(pool, 'terminate_workers'):
            pool.terminate_workers()
            return
        # Compatibility with Python <=3.13, before terminate_workers was added.
        processes = list((getattr(pool, '_processes', None) or {}).values())
        for process in processes:
            if process.is_alive():
                process.terminate()
        pool.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
        return
    pool.shutdown(wait=True, cancel_futures=True)

atexit.register(shutdown_pdf_service)
