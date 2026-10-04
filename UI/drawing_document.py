"""Re-render an original PDF independently of the persistent drawing ink layer."""
import base64
import json
import math
import os
from PySide6.QtCore import QObject, QTimer, QSize, QBuffer, QIODevice, QByteArray
from PySide6.QtGui import QImage
from Core.background_tasks import submit_io, await_future
from UI.document_geometry import backing_scale, MAX_BACKING_PIXELS

PROJECT_KEY = 'PastPaperStudioDrawing'


def render_source(source, scale):
    from Core import pdf_service
    with pdf_service.open(source['pdf_path']) as doc:
        page = doc[int(source['page_index'])]
        clip = pdf_service.Rect(source['clip'])
        pix = page.get_pixmap(matrix=pdf_service.Matrix(scale, scale), clip=clip,
                              alpha=False, show_progress=False, max_pixels=MAX_BACKING_PIXELS)
        return pix.width, pix.height, pix.stride, pix.samples


def source_image(result):
    width, height, stride, samples = result
    return QImage(samples, width, height, stride, QImage.Format.Format_RGB888).copy()


class DrawingDocumentLayer(QObject):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.source = None
        self.image = QImage()
        self.revision = 0
        self.closed = False
        self.future = None
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(130)
        self.debounce.timeout.connect(self._start)
        self.poll = QTimer(self)
        self.poll.setInterval(25)
        self.poll.timeout.connect(self._finish)

    def set_source(self, source):
        if not isinstance(source, dict) or not os.path.isfile(source.get('pdf_path', '')):
            return False
        try:
            clip = list(map(float, source['clip']))
            if len(clip) != 4 or not all(math.isfinite(v) for v in clip) or clip[2] <= clip[0] or clip[3] <= clip[1]:
                return False
            self.source = dict(source, clip=clip, page_index=int(source['page_index']))
        except (ValueError, TypeError, KeyError):
            return False
        self.schedule()
        return True

    def schedule(self):
        if self.source and not self.closed:
            self.revision += 1
            self.debounce.start()

    def _scale(self, minimum_edge=2048):
        c = self.canvas
        ratio = backing_scale(c.canvas_size.width()*c.view_zoom, c.canvas_size.height()*c.view_zoom,
                              c.devicePixelRatioF(), minimum_edge=minimum_edge)
        return c.view_zoom * ratio

    def _start(self):
        if self.closed or not self.source:
            return
        if self.future and not self.future.done():
            return  # Completion coalesces the latest revision, without a job queue.
        self.pending_revision = self.revision
        self.future = submit_io(render_source, dict(self.source), self._scale())
        self.poll.start()

    def _finish(self):
        if self.closed or not self.future or not self.future.done():
            return
        self.poll.stop()
        try:
            result = self.future.result()
            if self.pending_revision == self.revision:
                self.image = source_image(result)
                self.canvas.update()
        except Exception:
            pass  # Existing source/composite remains visible if a PDF disappears.
        self.future = None
        if self.pending_revision != self.revision:
            self.debounce.start()

    def export_image(self):
        if self.source:
            # Quality export uses the same bounded original-PDF renderer; it does
            # not enlarge the preview. Qt remains responsive during the wait.
            job = submit_io(render_source, dict(self.source), self._scale(4096))
            self.image = source_image(await_future(job, 'Saving drawing…', show_progress=False))
        return self.image

    def close(self):
        self.closed = True
        self.revision += 1
        self.debounce.stop()
        self.poll.stop()
        if self.future:
            self.future.cancel()
        self.future = None
        self.image = QImage()


def encode_png(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise ValueError('Could not encode drawing ink')
    buffer.close()
    return base64.b64encode(bytes(data)).decode('ascii')


def encode_project(ink, logical_size, source, background):
    return json.dumps(dict(version=1, logical_size=[logical_size.width(), logical_size.height()],
                           ink=encode_png(ink), source=source,
                           background=encode_png(background) if not background.isNull() else None))


def decode_project(image):
    raw = image.text(PROJECT_KEY)
    if not raw or len(raw) > 48*1024*1024:
        return None
    try:
        record = json.loads(raw)
        width, height = map(int, record['logical_size'])
        if record.get('version') != 1 or width < 1 or height < 1 or width*height > MAX_BACKING_PIXELS:
            return None
        ink = QImage.fromData(base64.b64decode(record['ink'], validate=True), 'PNG')
        if ink.isNull() or ink.width()*ink.height() > MAX_BACKING_PIXELS:
            return None
        ratio = ink.width()/width
        if abs(ink.height()/height-ratio) > .01:
            return None
        ink.setDevicePixelRatio(ratio)
        background = QImage.fromData(base64.b64decode(record['background'],validate=True),'PNG') if record.get('background') else QImage()
        return QSize(width,height), ink, record.get('source'), background
    except (ValueError, KeyError, TypeError):
        return None
