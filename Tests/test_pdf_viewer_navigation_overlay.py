import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Core.exam_mode import PDFViewer


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_pdf_viewer_overlay_buttons_show_on_hover_area():
    app = _app()
    viewer = PDFViewer()
    viewer.resize(900, 640)
    viewer.pdf_path = "dummy.pdf"
    viewer.set_edge_navigation_enabled(True)
    viewer.show()
    app.processEvents()

    target = viewer._floating_indicator_target_widget()
    point = QPoint(max(1, target.width() // 2), max(1, target.height() // 2))
    viewer._update_edge_navigation_for_point(point, target)

    assert viewer._edge_prev_btn.isVisible() is True
    assert viewer._edge_next_btn.isVisible() is True
    viewer.close()


def test_pdf_viewer_left_right_keys_navigate_pages():
    _app()
    viewer = PDFViewer()
    viewer.pdf_path = "dummy.pdf"
    viewer.page_count = 4
    viewer.current_page = 1
    viewer.show()

    QTest.keyClick(viewer, Qt.Key.Key_Left)
    assert viewer.current_page == 0

    QTest.keyClick(viewer, Qt.Key.Key_Right)
    assert viewer.current_page == 1
    viewer.close()
