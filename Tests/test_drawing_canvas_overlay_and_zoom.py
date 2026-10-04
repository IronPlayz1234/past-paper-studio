import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import QPointF

from Core.exam_mode import DrawingCanvasWidget, DrawingEditorDialog, ExamModeWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_overlay_toggle_does_not_switch_active_drawing_tool():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_tool("pen")
    canvas.set_tool("ruler")
    assert canvas.tool == "pen"
    assert canvas.ruler.visible is True


def test_line_snaps_to_ruler_axis_when_near():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("ruler", True)
    canvas.set_guide_angle("ruler", 0.0)
    canvas.ruler.center = QPointF(220.0, 180.0)

    start = QPointF(120.0, 184.0)
    end = QPointF(360.0, 222.0)
    snapped_start, snapped_end = canvas._snap_line_to_ruler(start, end)

    assert abs(float(snapped_start.y()) - 165.0) < 1.0
    assert abs(float(snapped_end.y()) - float(snapped_start.y())) < 1e-3


def test_pen_segment_snaps_to_ruler_axis_when_near():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("ruler", True)
    canvas.set_guide_angle("ruler", 0.0)
    canvas.ruler.center = QPointF(220.0, 180.0)

    start = QPointF(130.0, 186.0)
    end = QPointF(300.0, 210.0)
    snapped_start, snapped_end, did_snap = canvas._snap_pen_segment_to_ruler(start, end)
    assert did_snap is True
    assert abs(float(snapped_start.y()) - float(snapped_end.y())) < 1e-3
    assert abs(float(snapped_start.y()) - 165.0) < 1.0


def test_overlay_hit_test_prefers_protractor_when_both_overlap():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("ruler", True)
    canvas.set_guide_visible("protractor", True)
    canvas.ruler.center = QPointF(260.0, 220.0)
    canvas.protractor.center = QPointF(260.0, 220.0)

    overlay, mode = canvas._overlay_hit_test(QPointF(260.0, 220.0))
    assert overlay == "protractor"
    assert mode == "move"


def test_overlay_hit_test_prefers_protractor_body_when_overlapping_ruler():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("ruler", True)
    canvas.set_guide_visible("protractor", True)
    canvas.ruler.center = QPointF(260.0, 220.0)
    canvas.protractor.center = QPointF(260.0, 220.0)

    # Inside protractor body while still intersecting ruler hit area.
    overlay, mode = canvas._overlay_hit_test(QPointF(300.0, 210.0))
    assert overlay == "protractor"
    assert mode == "move"


def test_protractor_hit_test_allows_drag_from_body_area():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("protractor", True)
    canvas.protractor.center = QPointF(260.0, 220.0)

    mode = canvas._hit_test_protractor(QPointF(295.0, 180.0))
    assert mode is not None
    assert mode[0] == "move"
    assert canvas._hit_test_protractor(QPointF(295.0, 260.0)) is None


def test_ruler_defaults_to_a_usable_screen_size():
    _app()
    canvas = DrawingCanvasWidget()
    assert canvas.ruler.length == 240.0


def test_protractor_precision_ticks_include_single_degrees():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_protractor_mode("semi")
    ticks = canvas._protractor_tick_degrees()
    assert 121 in ticks
    assert 131 in ticks
    assert len(ticks) == 181


def test_round_protractor_mode_has_360_labels():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_protractor_mode("round")
    assert canvas.protractor.mode == DrawingCanvasWidget.PROTRACTOR_MODE_ROUND
    ticks = canvas._protractor_tick_degrees()
    labels = canvas._protractor_label_degrees()
    assert len(ticks) == 360
    assert 359 in ticks
    assert 0 in labels
    assert 360 in labels


def test_zoom_changes_view_only_and_saved_image_size_is_unzoomed(tmp_path: Path):
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_zoom_percent(240)
    assert canvas.zoom_percent() == 240

    out = tmp_path / "drawing.png"
    assert canvas.save_image(str(out)) is True
    loaded = QImage(str(out))
    from UI.drawing_document import decode_project
    assert decode_project(loaded)[0] == canvas.canvas_size
    assert 3840 <= max(loaded.width(),loaded.height()) <= 4096


def test_zoomed_pan_changes_view_transform_mapping():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.resize(600, 420)
    canvas.set_zoom_percent(220)
    before = canvas._view_to_image_point(QPointF(300.0, 210.0))
    canvas._pan_view_by(120.0, 0.0)
    after = canvas._view_to_image_point(QPointF(300.0, 210.0))
    assert float(after.x()) < float(before.x())


def test_protractor_overlay_paints_with_labels_without_crashing():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("protractor", True)
    canvas.protractor.radius = 140.0
    canvas.resize(640, 480)

    image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    canvas.render(image)
    assert image.width() == canvas.size().width()


def test_round_protractor_overlay_paints_without_crashing():
    _app()
    canvas = DrawingCanvasWidget()
    canvas.set_guide_visible("protractor", True)
    canvas.set_protractor_mode("round")
    canvas.protractor.radius = 140.0
    canvas.resize(640, 480)

    image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    canvas.render(image)
    assert image.height() == canvas.size().height()


def test_protractor_toggle_uses_picker_and_applies_mode(monkeypatch, tmp_path: Path):
    _app()
    out = tmp_path / "drawing-out.png"
    dialog = DrawingEditorDialog(str(out))

    def _pick_round(*_args, **_kwargs):
        return ("Round Protractor (0-360)", True)

    monkeypatch.setattr("Core.exam_mode.QInputDialog.getItem", _pick_round)
    dialog.toggle_protractor_btn.setChecked(True)

    assert dialog.canvas.protractor.visible is True
    assert dialog.canvas.protractor.mode == DrawingCanvasWidget.PROTRACTOR_MODE_ROUND


def test_load_image_does_not_create_undo_history(tmp_path: Path):
    _app()
    canvas = DrawingCanvasWidget()
    source = tmp_path / "source.png"
    img = QImage(canvas.canvas_size, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    assert img.save(str(source), "PNG")

    canvas.load_image(str(source))
    assert canvas.undo_stack == []


def test_drawing_reference_clip_keeps_full_page_width():
    class _Rect:
        def __init__(self, x0, y0, x1, y1):
            self.x0 = float(x0)
            self.y0 = float(y0)
            self.x1 = float(x1)
            self.y1 = float(y1)
            self.width = float(x1 - x0)
            self.height = float(y1 - y0)

    class _Page:
        def __init__(self):
            self.rect = _Rect(0.0, 0.0, 600.0, 900.0)

        def search_for(self, _probe):
            return [_Rect(120.0, 240.0, 360.0, 280.0)]

    clip = ExamModeWindow._build_drawing_reference_clip(_Page(), "Draw the structure and label it")
    assert clip is not None
    assert abs(float(clip.x0) - 0.0) < 1e-6
    assert abs(float(clip.x1) - 600.0) < 1e-6
