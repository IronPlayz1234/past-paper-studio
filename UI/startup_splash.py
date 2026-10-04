"""Native Qt startup animation: opposing title slides and real boot progress."""
from __future__ import annotations

from typing import Optional

from Data.app_metadata import APP_NAME, APP_VERSION

from PySide6.QtCore import (
    Property, QEasingCurve, QEventLoop,
    QParallelAnimationGroup, QPauseAnimation, QPointF, QPropertyAnimation,
    QRectF, QSequentialAnimationGroup, Qt, QTimer,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid


class BetaBootSplashWindow(QDialog):
    """A bounded intro followed by a loading bar driven by startup milestones.

    Animations, loops and timers belong to the splash and stop when it closes.
    Painting in one surface avoids layout/position-animation conflicts.
    """

    TITLE = APP_NAME
    SUBTITLE = APP_VERSION

    def __init__(self, full_sequence: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("betaBootSplash")
        self.setWindowTitle(f"{self.TITLE} — {self.SUBTITLE}")
        self.setAccessibleName(f"{self.TITLE} {self.SUBTITLE}")
        self.resize(820, 440)
        self._title_progress = 0.0
        self._subtitle_progress = 0.0
        self._progress = 0.0
        self._target_progress = 0.0
        self._ambient_phase = 0.0
        self._stage_text = "Preparing your workspace"
        self._intro_finished = False
        self._intro_loop: Optional[QEventLoop] = None
        self._closed = False

        self._intro = QParallelAnimationGroup(self)
        title = QPropertyAnimation(self, b"titleProgress", self._intro)
        title.setDuration(880 if full_sequence else 640)
        title.setStartValue(0.0)
        title.setEndValue(1.0)
        title.setEasingCurve(QEasingCurve.Type.OutCubic)
        subtitle_sequence = QSequentialAnimationGroup(self._intro)
        subtitle_sequence.addAnimation(QPauseAnimation(140, subtitle_sequence))
        subtitle = QPropertyAnimation(self, b"subtitleProgress", subtitle_sequence)
        subtitle.setDuration(800 if full_sequence else 600)
        subtitle.setStartValue(0.0)
        subtitle.setEndValue(1.0)
        subtitle.setEasingCurve(QEasingCurve.Type.OutCubic)
        subtitle_sequence.addAnimation(subtitle)
        self._intro.addAnimation(title)
        self._intro.addAnimation(subtitle_sequence)
        self._intro.finished.connect(self._finish_intro)

        self._progress_animation = QPropertyAnimation(self, b"progress", self)
        self._progress_animation.setDuration(280)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._ambient_timer = QTimer(self)
        self._ambient_timer.setInterval(33)
        self._ambient_timer.timeout.connect(self._tick_ambient)
        self._intro_timeout = QTimer(self)
        self._intro_timeout.setSingleShot(True)
        self._intro_timeout.timeout.connect(self._finish_intro)

    def _get_title_progress(self) -> float:
        return self._title_progress

    def _set_title_progress(self, value: float) -> None:
        self._title_progress = max(0.0, min(1.0, float(value)))
        self.update()

    titleProgress = Property(float, _get_title_progress, _set_title_progress)

    def _get_subtitle_progress(self) -> float:
        return self._subtitle_progress

    def _set_subtitle_progress(self, value: float) -> None:
        self._subtitle_progress = max(0.0, min(1.0, float(value)))
        self.update()

    subtitleProgress = Property(float, _get_subtitle_progress, _set_subtitle_progress)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def show_centered(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(min(820, max(1, available.width() - 40)),
                        min(440, max(1, available.height() - 40)))
            self.move(available.center() - self.rect().center())
        self.show()
        self.raise_()

    def play_intro_blocking(self) -> None:
        """Wait for the short intro while Qt continues painting and dispatching events."""
        if self._intro_finished or self._closed:
            return
        loop = QEventLoop()
        self._intro_loop = loop
        self._intro_timeout.start(1600)
        self._intro.start()
        try:
            loop.exec()
        finally:
            self._intro_loop = None
            loop.deleteLater()

    def _finish_intro(self) -> None:
        self._intro_timeout.stop()
        self._intro.stop()
        self._title_progress = self._subtitle_progress = 1.0
        self._intro_finished = True
        self.update()
        if self._intro_loop is not None:
            self._intro_loop.quit()

    def set_stage(self, text: str, completed_steps: int, total_steps: int) -> None:
        if self._closed:
            return
        self._stage_text = str(text or "").strip() or "Preparing your workspace"
        # Startup milestones never roll backwards or exceed 100%.
        fraction = max(0, int(completed_steps)) / max(1, int(total_steps))
        self._target_progress = max(self._target_progress, min(1.0, fraction))
        self.setAccessibleDescription(f"{self._stage_text}, {int(self._target_progress * 100)} percent")
        self._progress_animation.stop()
        self._progress_animation.setStartValue(self._progress)
        self._progress_animation.setEndValue(self._target_progress)
        self._progress_animation.start()
        self.update()

    def finish_loading(self) -> None:
        """Let the bar visibly reach 100% before the dashboard crossfade."""
        if self._closed:
            return
        self.set_stage("Your workspace is ready", 1, 1)
        loop = QEventLoop()
        guard = QTimer(self)
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        self._progress_animation.finished.connect(loop.quit)
        self.finished.connect(loop.quit)
        try:
            guard.start(500)
            loop.exec()
            if not self._closed and isValid(self):
                self.progress = 1.0
        finally:
            if isValid(guard):
                guard.stop()
            if isValid(self):
                self._progress_animation.finished.disconnect(loop.quit)
                self.finished.disconnect(loop.quit)
            if isValid(guard):
                guard.deleteLater()
            loop.deleteLater()

    def _tick_ambient(self) -> None:
        self._ambient_phase = (self._ambient_phase + 0.016) % 1.0
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._closed:
            self._ambient_timer.start()

    def hideEvent(self, event) -> None:
        self._ambient_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._closed = True
        for timer in (self._ambient_timer, self._intro_timeout):
            timer.stop()
        for animation in (self._intro, self._progress_animation):
            animation.stop()
        if self._intro_loop is not None:
            self._intro_loop.quit()
        super().closeEvent(event)

    def _title_rect(self) -> QRectF:
        return QRectF(32, self.height() * 0.405, max(1, self.width() - 64), self.height() * 0.155)

    def _subtitle_rect(self) -> QRectF:
        return QRectF(32, self.height() * 0.565, max(1, self.width() - 64), 36)

    def _bar_rect(self) -> QRectF:
        width = min(440.0, max(1.0, self.width() - 100.0))
        return QRectF((self.width() - width) / 2, self.height() * 0.755, width, 6)

    def _draw_paper_mark(self, painter: QPainter) -> None:
        """Three offset pages resolve into one small, folded paper emblem."""
        painter.save()
        painter.translate(self.width() / 2, self.height() * 0.265)
        reveal = min(1.0, self._title_progress * 1.4)
        painter.setOpacity(reveal)
        for index, (offset, color) in enumerate(((-8, "#7276B9"), (8, "#458E92"), (0, "#9EF5DC"))):
            painter.setPen(QPen(QColor(color), 1.5))
            painter.setBrush(QColor("#101A27"))
            painter.drawRoundedRect(QRectF(-17 + offset, -24 + (2 - index) * 4, 34, 46), 5, 5)
        painter.setPen(QPen(QColor("#9EF5DC"), 1.6))
        for y, end in ((-8, 9), (0, 9), (8, 3)):
            painter.drawLine(QPointF(-9, y), QPointF(end, y))
        painter.restore()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(panel, 22, 22)
        painter.setClipPath(clip)
        background = QLinearGradient(panel.topLeft(), panel.bottomRight())
        background.setColorAt(0, QColor("#121E2D"))
        background.setColorAt(0.58, QColor("#0B1420"))
        background.setColorAt(1, QColor("#141626"))
        painter.fillPath(clip, background)
        for center, color in ((QPointF(self.width() * 0.83, 25), QColor(66, 190, 175, 28)),
                              (QPointF(50, self.height() - 15), QColor(136, 105, 210, 28))):
            glow = QRadialGradient(center, self.width() * 0.5)
            glow.setColorAt(0, color)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillPath(clip, glow)
        painter.setPen(QPen(QColor(165, 197, 220, 8), 1))
        for x in range(28, self.width(), 32):
            for y in range(28, self.height(), 32):
                painter.drawPoint(x, y)
        painter.setPen(QPen(QColor(159, 192, 213, 45), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(clip)
        self._draw_paper_mark(painter)

        title_rect = self._title_rect()
        font = QFont("Arial")
        font.setWeight(QFont.Weight.Bold)
        pixels = min(48, max(18, int(self.width() * 0.059)))
        font.setPixelSize(pixels)
        while pixels > 12 and QFontMetricsF(font).horizontalAdvance(self.TITLE) > title_rect.width() - 8:
            pixels -= 1
            font.setPixelSize(pixels)
        painter.setFont(font)
        painter.setPen(QColor("#EEF6FA"))
        title_rect.translate(self.width() * (1.0 - self._title_progress), 0)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self.TITLE)

        subtitle_rect = self._subtitle_rect()
        subtitle_rect.translate(-self.width() * (1.0 - self._subtitle_progress), 0)
        font.setPixelSize(min(22, max(15, int(self.width() * 0.027))))
        font.setWeight(QFont.Weight.Medium)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        painter.setFont(font)
        painter.setPen(QColor("#9EF5DC"))
        painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignCenter, self.SUBTITLE)

        # The bar enters after the opposing text; its fill reflects real work.
        reveal = max(0.0, min(1.0, (self._subtitle_progress - 0.45) / 0.55))
        painter.setOpacity(reveal)
        bar = self._bar_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#263442"))
        painter.drawRoundedRect(bar, 3, 3)
        if self._progress > 0:
            fill = QRectF(bar.x(), bar.y(), bar.width() * self._progress, bar.height())
            gradient = QLinearGradient(bar.topLeft(), bar.topRight())
            gradient.setColorAt(0, QColor("#9388F5"))
            gradient.setColorAt(0.5, QColor("#72D9D2"))
            gradient.setColorAt(1, QColor("#B2F5D8"))
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 3, 3)
            if self._progress < 1.0:
                fill_path = QPainterPath()
                fill_path.addRoundedRect(fill, 3, 3)
                painter.save()
                painter.setClipPath(fill_path, Qt.ClipOperation.IntersectClip)
                sweep_x = bar.x() - 80 + (bar.width() + 160) * self._ambient_phase
                sweep = QLinearGradient(sweep_x - 60, 0, sweep_x + 60, 0)
                sweep.setColorAt(0, QColor(255, 255, 255, 0))
                sweep.setColorAt(0.5, QColor(255, 255, 255, 150))
                sweep.setColorAt(1, QColor(255, 255, 255, 0))
                painter.fillRect(fill, sweep)
                painter.restore()

        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.25)
        painter.setFont(font)
        painter.setPen(QColor("#97A8BC"))
        message_rect = QRectF(bar.x(), bar.y() + 19, max(1, bar.width() - 44), 24)
        message = QFontMetricsF(font).elidedText(self._stage_text, Qt.TextElideMode.ElideRight,
                                               int(message_rect.width()))
        painter.drawText(message_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, message)
        painter.setPen(QColor("#B5C4D5"))
        painter.drawText(QRectF(bar.right() - 40, message_rect.y(), 40, 24),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         f"{int(round(self._progress * 100))}%")
        painter.end()
