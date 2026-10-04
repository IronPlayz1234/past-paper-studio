"""Theme-aware startup presentation over the existing opposing-slide choreography."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication

from UI.font_system import discover_available_ui_fonts
from UI.startup_splash import BetaBootSplashWindow
from UI.startup_motion import reduced_motion_requested
from UI.static_theme_surface import StaticThemeSurface
from UI.theme import ThemeManager, get_theme_manager


class StudioBootSplashWindow(BetaBootSplashWindow):
    """One wordmark and one cached environment, with no per-theme splash variants."""

    def __init__(self, full_sequence=True, parent=None, *, reduced_motion=None):
        super().__init__(full_sequence, parent)
        self.reduced_motion = reduced_motion_requested() if reduced_motion is None else bool(reduced_motion)
        self._stage_text = "Loading Studio"
        self._artwork = StaticThemeSurface(self, application_canvas=True)
        self._artwork.hide()
        self._display_family = self._choose_display_family()
        # The existing timer only sweeps the progress fill. Theme art stays cached.
        if self.reduced_motion:
            self._ambient_timer.stop()

    @staticmethod
    def _choose_display_family():
        manager = get_theme_manager()
        configured = manager.global_font_family()
        if configured and configured != "Default":
            return configured
        fonts = discover_available_ui_fonts()
        for family in ("Avenir Next", "Geist", "Inter", "Segoe UI", "Helvetica Neue"):
            if family in fonts:
                return family
        return QApplication.font().family()

    def start_intro(self):
        """Keep initialization moving instead of waiting for decorative slides."""
        if self._closed or self._intro_finished:
            return
        if self.reduced_motion:
            self._finish_intro()
        else:
            self._intro_timeout.start(1600)
            self._intro.start()

    def play_intro_blocking(self):
        if self.reduced_motion:
            self._finish_intro()
        else:
            super().play_intro_blocking()

    def set_stage(self, text, completed_steps, total_steps):
        super().set_stage(text, completed_steps, total_steps)
        if self.reduced_motion and not self._closed:
            self._progress_animation.stop()
            self.progress = self._target_progress

    def finish_loading(self):
        """Ready means ready: hand off without a minimum hold or bar-completion wait."""
        if self._closed:
            return
        self._finish_intro()
        self.set_stage("Ready", 1, 1)
        self._progress_animation.stop()
        self.progress = 1.0

    def showEvent(self, event):
        super().showEvent(event)
        if self.reduced_motion:
            self._ambient_timer.stop()

    def _title_rect(self):
        return QRectF(30, self.height() * .27, max(1, self.width() - 60), self.height() * .32)

    def _subtitle_rect(self):
        return QRectF(30, self.height() * .64, max(1, self.width() - 60), self.height() * .075)

    def _bar_rect(self):
        width = min(360.0, max(1.0, self.width() - 100))
        return QRectF((self.width() - width) / 2, self.height() * .805, width, 4)

    def _font(self, pixels, weight=QFont.Weight.Medium, spacing=0):
        font = QFont(self._display_family)
        font.setPixelSize(max(8, int(pixels)))
        font.setWeight(weight)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        return font

    def _fit_font(self, text, pixels, width, weight, spacing=0):
        font = self._font(pixels, weight, spacing)
        while font.pixelSize() > 8 and QFontMetricsF(font).horizontalAdvance(text) > width:
            font.setPixelSize(font.pixelSize() - 1)
        return font

    def paintEvent(self, event):
        manager = get_theme_manager()
        tokens = manager.get_theme_tokens(manager.current_theme())
        bg = tokens["BG_DARK"]
        text = ThemeManager._ensure_text_contrast(tokens["TEXT_WHITE"], bg)
        muted = ThemeManager._ensure_text_contrast(tokens["TEXT_GRAY"], bg)
        accent = ThemeManager._ensure_text_contrast(tokens["PRIMARY"], bg)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(panel, 18, 18)
        painter.setClipPath(clip)
        painter.fillPath(clip, QColor(bg))
        self._artwork.resize(self.size())
        artwork = self._artwork.background_pixmap()
        if artwork is not None:
            painter.drawPixmap(0, 0, artwork)

        # A quiet center keeps the wordmark clear without boxing it in a card.
        veil = QRadialGradient(panel.center(), self.width() * .48)
        center = QColor(bg)
        center.setAlpha(220)
        veil.setColorAt(0, center)
        center.setAlpha(130)
        veil.setColorAt(.55, center)
        center.setAlpha(0)
        veil.setColorAt(1, center)
        painter.fillPath(clip, veil)
        border = QColor(tokens["PRIMARY"])
        border.setAlpha(85)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(clip)

        # Two tiny page-registration marks frame the composition like a study sheet.
        painter.setPen(QPen(border, 1.3))
        for x, y, direction in ((24, 24, 1), (self.width()-24, self.height()-24, -1)):
            painter.drawLine(x, y, x+direction*16, y)
            painter.drawLine(x, y, x, y+direction*16)

        title = self._title_rect()
        title.translate(0 if self.reduced_motion else self.width() * (1-self.titleProgress), 0)
        label_rect = QRectF(title.x(), title.y(), title.width(), title.height() * .28)
        studio_rect = QRectF(title.x(), title.y()+title.height()*.28, title.width(), title.height()*.72)
        scale = min(self.width()/820, self.height()/440)
        painter.setPen(QColor(text))
        painter.setFont(self._fit_font("PAST PAPER", 23*scale, title.width(), QFont.Weight.DemiBold, 3*scale))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "PAST PAPER")
        painter.setFont(self._fit_font("Studio", 76*scale, title.width(), QFont.Weight.DemiBold, -1*scale))
        painter.drawText(studio_rect, Qt.AlignmentFlag.AlignCenter, "Studio")

        subtitle = self._subtitle_rect()
        subtitle.translate(0 if self.reduced_motion else -self.width() * (1-self.subtitleProgress), 0)
        painter.setFont(self._font(14*scale, QFont.Weight.Medium, 1.5*scale))
        painter.setPen(QColor(accent))
        painter.drawText(subtitle, Qt.AlignmentFlag.AlignCenter, self.SUBTITLE)

        reveal = 1 if self.reduced_motion else max(0, min(1, (self.subtitleProgress-.45)/.55))
        painter.setOpacity(reveal)
        bar = self._bar_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ThemeManager._mix_hex(bg, tokens["TEXT_LIGHT"], .14)))
        painter.drawRoundedRect(bar, 2, 2)
        if self.progress > 0:
            fill = QRectF(bar.x(), bar.y(), bar.width()*self.progress, bar.height())
            gradient = QLinearGradient(bar.topLeft(), bar.topRight())
            gradient.setColorAt(0, QColor(accent))
            gradient.setColorAt(1, QColor(tokens["SECONDARY"]))
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 2, 2)
            if not self.reduced_motion and self.progress < 1:
                sweep = QColor(text)
                sweep.setAlpha(95)
                painter.setBrush(sweep)
                painter.drawRoundedRect(QRectF(bar.x() + max(0, fill.width()-24)*self._ambient_phase, bar.y(), min(24, fill.width()), 4), 2, 2)

        font = self._font(max(10, 11*scale), QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(muted))
        message_rect = QRectF(bar.x(), bar.y()+12, max(1, bar.width()-45), 20)
        message = QFontMetricsF(font).elidedText(self._stage_text, Qt.TextElideMode.ElideRight, int(message_rect.width()))
        painter.drawText(message_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, message)
        painter.drawText(QRectF(bar.right()-40, message_rect.y(), 40, 20),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{round(self.progress*100)}%")
        painter.end()
