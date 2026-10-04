"""Deferred viewer UI work must stop when its Qt receiver is destroyed."""


def test_pdf_hover_callback_is_cancelled_when_viewer_is_deleted():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from Core.exam_mode import PDFViewer

    app = QApplication.instance() or QApplication([])
    viewer = PDFViewer()
    target = viewer._floating_indicator_targets[0]
    calls = []
    viewer._should_show_floating_indicator = lambda: calls.append("checked") or False
    QCoreApplication.sendEvent(target, QEvent(QEvent.Type.Hide))
    app.processEvents()
    assert calls == ["checked"]
    QCoreApplication.sendEvent(target, QEvent(QEvent.Type.Hide))
    viewer.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert calls == ["checked"]
