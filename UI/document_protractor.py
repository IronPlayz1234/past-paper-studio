"""Dismissible, draggable protractor scoped to a PDF viewport."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QTransform, QRegion
from PySide6.QtWidgets import QWidget, QToolButton
from Utils.gui_utils import Colors
from UI.document_geometry import local_point, snapped_angle


class DocumentProtractor(QWidget):
    def __init__(self, viewer):
        super().__init__(viewer.image_scroll.viewport())
        self.viewer = viewer
        self.angle = 0.0
        self._drag = None
        self.radius = 110.0  # Logical screen pixels, independent of document zoom/DPR.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.close_button = QToolButton(self)
        self.close_button.setText('×')
        self.close_button.setToolTip('Remove protractor')
        self.close_button.setAccessibleName('Remove protractor')
        self.close_button.clicked.connect(self.hide)
        self.update_scale()
        self.reset_position()
        self.setAccessibleName('Floating protractor')
        self.close_button.setToolTip('Remove protractor · drag the body to move; round handle rotates; Shift snaps')

    def update_scale(self):
        center = QPointF(self.pos()) + QPointF(self.width()/2, self.height()/2)
        side = round(2*self.radius + 76)
        if self.width() != side or self.height() != side:
            self.resize(side, side)
            self.move(round(center.x()-side/2),round(center.y()-side/2))
        self.close_button.setGeometry(side-28,4,24,24)
        self.close_button.setStyleSheet(f'background:{Colors.BG_CARD};color:{Colors.TEXT_LIGHT};border:1px solid {Colors.BG_LIGHT};border-radius:6px;font-size:18px;')
        self._update_hit_region()
        self.update()

    def _update_hit_region(self):
        radius = self.radius
        body = QPainterPath()
        body.moveTo(-radius, 0)
        body.arcTo(QRectF(-radius, -radius, 2*radius, 2*radius), 180, -180)
        body.closeSubpath()
        body.addEllipse(QPointF(radius+16, 0), 14, 14)
        transform = QTransform().translate(self.width()/2, self.height()/2).rotate(self.angle)
        region = QRegion(transform.map(body).toFillPolygon().toPolygon())
        self.setMask(region.united(QRegion(self.close_button.geometry())))

    def reset_position(self):
        parent = self.parentWidget()
        self.move(max(0,(parent.width()-self.width())//2),max(0,(parent.height()-self.height())//2))
        self.angle=0.0
        self._update_hit_region()
        self.update()

    def paintEvent(self, event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width()/2,self.height()/2);p.rotate(self.angle)
        radius=self.radius
        color=QColor(Colors.ACCENT_CYAN)
        fill=QColor('#F4F7FB');fill.setAlpha(200)
        p.setPen(QPen(color,1.5));p.setBrush(fill)
        p.drawPie(QRectF(-radius,-radius,2*radius,2*radius),0,180*16)
        font=p.font();font.setPixelSize(12);p.setFont(font)
        for degree in range(0,181):
            a=math.radians(degree)
            size=12 if degree%10==0 else (8 if degree%5==0 else 4)
            p.setPen(QPen(QColor('#17212B'),1))
            p.drawLine(QPointF(radius*math.cos(a),-radius*math.sin(a)),QPointF((radius-size)*math.cos(a),-(radius-size)*math.sin(a)))
            if degree%20==0 and radius>=60:
                x=(radius-25)*math.cos(a);y=-(radius-25)*math.sin(a)
                p.drawText(QRectF(x-15,y-8,30,16),Qt.AlignmentFlag.AlignCenter,str(degree))
        p.drawLine(QPointF(-radius,0),QPointF(radius,0))
        p.drawLine(QPointF(-5,0),QPointF(5,0));p.drawLine(QPointF(0,-5),QPointF(0,5))
        p.setPen(QPen(color,2));p.setBrush(QColor(Colors.BG_CARD))
        p.drawEllipse(QPointF(radius+16,0),9,9)
        p.end()

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        point=local_point(event.position(),QPointF(self.width()/2,self.height()/2),self.angle)
        self._rotating=(point-QPointF(self.radius+16,0)).manhattanLength()<26
        self._drag=event.globalPosition()
        self._origin=self.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self,event):
        if self._drag is None:return
        if self._rotating:
            point=event.position()-QPointF(self.width()/2,self.height()/2)
            self.angle=math.degrees(math.atan2(point.y(),point.x()))%360
        else:
            delta=(event.globalPosition()-self._drag).toPoint()
            pos=self._origin+delta
            parent=self.parentWidget()
            self.move(max(-self.width()//3,min(parent.width()-self.width()//2,pos.x())),max(-self.height()//3,min(parent.height()-self.height()//2,pos.y())))
        self._update_hit_region();self.update();event.accept()

    def mouseReleaseEvent(self,event):
        if self._drag is None:return
        if self._rotating:
            self.angle=snapped_angle(self.angle,bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        self._drag=None;self.unsetCursor();self._update_hit_region();self.update();event.accept()

    def wheelEvent(self,event):
        event.ignore()
