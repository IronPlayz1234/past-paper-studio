"""Small native vector icons; no image dependencies or startup file decoding."""
from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter, QPainterPath, QLinearGradient, QPen
from PySide6.QtWidgets import QApplication
from UI.theme import get_theme_manager, ThemeManager
from Utils.gui_utils import Colors


def paint_icon(painter, size, background, foreground, accent):
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size/1024, size/1024)
    rect = QRectF(64,64,896,896)
    background = QColor(background); foreground = QColor(foreground); accent = QColor(accent)
    gradient = QLinearGradient(64,64,960,960)
    gradient.setColorAt(0,background.lighter(117));gradient.setColorAt(1,background)
    painter.setPen(QPen(background.lighter(150),5));painter.setBrush(gradient)
    painter.drawRoundedRect(rect,202,202)
    painter.setPen(Qt.PenStyle.NoPen)
    # Paper stack, retaining the recognizable silhouette from the supplied logo.
    painter.setBrush(accent)
    for x,y,angle in ((276,355,-12),(316,309,-5)):
        painter.save();painter.translate(x,y);painter.rotate(angle)
        painter.drawRoundedRect(QRectF(0,0,39,409),18,18);painter.restore()
    paper=QPainterPath();paper.moveTo(364,763);paper.lineTo(364,308)
    paper.quadTo(364,241,431,241);paper.lineTo(587,241);paper.lineTo(728,382)
    paper.lineTo(728,480);paper.quadTo(728,614,586,614);paper.lineTo(448,614)
    paper.lineTo(448,742);paper.quadTo(448,763,427,763);paper.closeSubpath()
    painter.setBrush(foreground);painter.drawPath(paper)
    # Counter and accent half of the P.
    painter.setBrush(background);painter.drawRoundedRect(QRectF(448,386,204,145),20,20)
    painter.setBrush(accent);painter.drawRoundedRect(QRectF(448,570,212,45),18,18)
    painter.drawRoundedRect(QRectF(448,659,162,47),18,18)
    for y in (422,473):painter.drawRoundedRect(QRectF(471,y,139,25),10,10)
    fold=QPainterPath();fold.moveTo(587,241);fold.lineTo(728,382);fold.lineTo(629,382)
    fold.quadTo(587,382,587,340);fold.closeSubpath()
    painter.setBrush(accent.lighter(115));painter.drawPath(fold)


def icon_pixmap(size=512, *, background=None, foreground=None, accent=None):
    background = background or Colors.BG_DARK
    foreground = foreground or ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT,background)
    accent = accent or ThemeManager._ensure_text_contrast(Colors.PRIMARY,background,min_ratio=3)
    pixmap=QPixmap(size,size);pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap)
    paint_icon(painter,size,background,foreground,accent);painter.end()
    return pixmap


class ThemeAppIcon(QObject):
    def __init__(self, app):
        super().__init__(app);self.app=app
        get_theme_manager().theme_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        icon=QIcon()
        for size in (32,64,128,256,512):icon.addPixmap(icon_pixmap(size))
        self.app.setWindowIcon(icon)


def install_theme_app_icon(app=None):
    app=app or QApplication.instance()
    if app is not None and not hasattr(app,'_pps_theme_icon'):
        app._pps_theme_icon=ThemeAppIcon(app)
