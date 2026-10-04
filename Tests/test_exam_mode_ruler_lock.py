import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from Core.exam_mode import PDFViewer


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_ruler_screen_size_is_fixed_and_document_graduations_are_calibrated(monkeypatch):
    _app()
    viewer = PDFViewer()
    viewer.resize(1000, 700)
    viewer.pdf_path = "mock.pdf"
    monkeypatch.setattr(viewer, "_compute_scale_pixels_per_mm", lambda: 4.0)

    viewer.set_movable_ruler_enabled(True)
    assert viewer._ruler_state.length_px == 240.0
    assert viewer._ruler_state.pixels_per_mm == 4.0

    viewer._scale_ruler(2.0)
    assert viewer._ruler_state.length_px == 240.0
    viewer.close()


def test_ruler_eye_controls_toggle_visibility():
    app = _app()
    viewer = PDFViewer()
    viewer.resize(980, 680)
    viewer.show()
    app.processEvents()

    viewer.pdf_path = "mock.pdf"
    viewer.set_movable_ruler_enabled(True)
    viewer._ruler_hovered = True
    viewer._sync_ruler_visibility_buttons()

    assert viewer._ruler_state.visible is True
    assert viewer._ruler_hide_btn.isVisible() is True

    viewer._set_ruler_visible(False)
    app.processEvents()
    assert viewer._ruler_state.visible is False
    assert viewer._ruler_show_btn.isVisible() is True

    viewer._set_ruler_visible(True)
    app.processEvents()
    assert viewer._ruler_state.visible is True
    viewer.close()


def test_pdf_viewer_styles_include_border_and_thin_scrollbars():
    _app()
    viewer = PDFViewer()
    viewer.apply_runtime_theme()
    style = viewer.styleSheet()
    assert "border: 2px solid" in style
    assert "QScrollBar:vertical" in style
    assert "QScrollBar:horizontal" in style
    viewer.close()
