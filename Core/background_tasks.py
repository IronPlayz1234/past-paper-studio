"""Worker execution with a guarded, responsive Qt loading state.

Legacy synchronous callers can await a value without doing I/O on the GUI thread.
The application-modal loading dialog prevents overlapping user actions; Qt continues
painting and delivering timers/signals. Pure work functions must never touch widgets.
"""
from __future__ import annotations
import atexit
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import threading
import time

from Data.app_metadata import APP_NAME

_IO_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='ppf-io')
_GUI_WAIT_DEPTH = 0


def gui_work_pending():
    return _GUI_WAIT_DEPTH > 0


def in_gui_thread():
    from PySide6.QtCore import QCoreApplication, QThread
    app = QCoreApplication.instance()
    return app is not None and QThread.currentThread() == app.thread()


def _await_without_dialog(future, timeout, cancel):
    """Keep startup responsive when its splash already presents loading progress."""
    global _GUI_WAIT_DEPTH
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    poll = QTimer(loop)
    poll.setInterval(20)
    start = time.monotonic()
    timed_out = False

    def check():
        nonlocal timed_out
        if future.done():
            loop.quit()
        elif time.monotonic() - start >= timeout:
            timed_out = True
            if cancel:
                cancel()
            loop.quit()

    poll.timeout.connect(check)
    _GUI_WAIT_DEPTH += 1
    try:
        poll.start()
        if not future.done():
            loop.exec()
        if timed_out:
            raise TimeoutError('The operation took too long. Please try again.')
        return future.result()
    finally:
        poll.stop()
        loop.deleteLater()
        _GUI_WAIT_DEPTH -= 1


def await_future(future, title='Working…', *, timeout=180, cancel=None, show_progress=True):
    global _GUI_WAIT_DEPTH
    if future.done() or not in_gui_thread():
        return future.result(timeout=timeout)
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QProgressDialog
    from shiboken6 import isValid
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return future.result(timeout=timeout)
    if not show_progress:
        return _await_without_dialog(future, timeout, cancel)
    loop = QEventLoop()
    dialog = QProgressDialog(title, 'Cancel' if cancel else '', 0, 0, app.activeWindow())
    dialog.setWindowTitle(APP_NAME)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setAutoClose(False)
    dialog.setMinimumDuration(0)
    finishing = False
    reopen_timer = QTimer(dialog)
    reopen_timer.setSingleShot(True)
    reopen_timer.timeout.connect(dialog.show)
    if cancel is None:
        dialog.setCancelButton(None)
    else:
        def request_cancel():
            if finishing or future.done() or not isValid(dialog):
                return
            cancel()
            dialog.setLabelText('Cancelling…')
            dialog.setCancelButton(None)
            reopen_timer.start(0)
        dialog.canceled.connect(request_cancel)
    show_timer = QTimer()
    show_timer.setSingleShot(True)
    show_timer.timeout.connect(dialog.show)
    poll = QTimer()
    poll.setInterval(20)
    start = time.monotonic()
    timed_out = False
    def check():
        nonlocal timed_out
        if future.done():
            loop.quit()
        elif time.monotonic() - start >= timeout:
            timed_out = True
            if cancel:
                cancel()
            loop.quit()
    poll.timeout.connect(check)
    _GUI_WAIT_DEPTH += 1
    try:
        # A real modal scope, rather than processEvents() calls between blocking operations.
        show_timer.start(200)
        poll.start()
        if not future.done():
            loop.exec()
        if timed_out:
            raise TimeoutError('The operation took too long. Please try again.')
        return future.result()
    finally:
        finishing = True
        try:
            # A parent window can be destroyed while the nested event loop runs.
            # Its dialog and child timer then have invalid C++ objects.
            for timer in (reopen_timer, poll, show_timer):
                if isValid(timer):
                    timer.stop()
            if isValid(dialog):
                dialog.blockSignals(True)
                dialog.close()
                if isValid(dialog):
                    dialog.deleteLater()
        finally:
            _GUI_WAIT_DEPTH -= 1


def submit_io(function, *args, **kwargs):
    """Schedule pure background work; callers own result delivery to their UI."""
    return _IO_POOL.submit(partial(function, *args, **kwargs))


def run_io(function, *args, title='Working…', cancel=None, wait_timeout=180, **kwargs):
    if not in_gui_thread():
        return function(*args, **kwargs)
    return await_future(_IO_POOL.submit(partial(function, *args, **kwargs)), title,
                        timeout=wait_timeout, cancel=cancel)


def shutdown_io():
    _IO_POOL.shutdown(wait=False, cancel_futures=True)

atexit.register(shutdown_io)
