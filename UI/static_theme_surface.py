"""Cached, still theme backgrounds. No timers, animation or input overlays."""
import math
import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QWidget


DECORATED_THEMES = frozenset({'Cipher Green', 'Cipher Red', 'Cipher Purple', 'Aurora Borealis',
                              'Matcha Latte', 'Old Library', 'Coffee Shop',
                              'Archive Blue', "Synthwave '84", 'Carbon Fiber', 'Violet Afterburn', 'Crimson Meridian'})
SEARCH_CANVAS_THEMES = frozenset({'Archive Blue', "Synthwave '84", 'Carbon Fiber', 'Violet Afterburn', 'Crimson Meridian'})


class StaticThemeSurface(QWidget):
    """Paint behind normal child widgets; keep text, controls and PDFs unobstructed."""

    def __init__(self, parent=None, *, search_canvas=False, application_canvas=False):
        super().__init__(parent)
        self._search_canvas = bool(search_canvas or application_canvas)
        self._application_canvas = bool(application_canvas)
        self._decorations_enabled = True
        self._background = None
        self._background_key = None
        self._render_count = 0
        from UI.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self._invalidate_background)

    def set_decorations_enabled(self, enabled):
        """Disable a nested canvas when artwork is owned by the application shell."""
        self._decorations_enabled = bool(enabled)
        self._invalidate_background()

    def _invalidate_background(self, *_):
        self._background = self._background_key = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        background = self.background_pixmap()
        if background is None:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, background)
        painter.end()

    def background_pixmap(self):
        """Reuse the bounded theme artwork in other native Qt presentations."""
        from UI.theme import get_theme_manager
        manager = get_theme_manager()
        theme = manager.current_theme()
        if (not self._decorations_enabled or theme not in DECORATED_THEMES or (theme in SEARCH_CANVAS_THEMES and not self._search_canvas)
                or self.width() <= 0 or self.height() <= 0):
            self._background = self._background_key = None
            return None
        # One bounded image per surface, regenerated only for size/theme/DPI changes.
        scale = min(float(self.devicePixelRatioF()), 2.0,
                    math.sqrt(4_000_000 / max(1, self.width() * self.height())))
        key = (theme, self.width(), self.height(), scale)
        if key != self._background_key:
            self._background = self._render_background(manager.get_theme_tokens(theme), theme, scale)
            self._background_key = key
        return self._background

    def _render_background(self, tokens, theme, scale):
        pixmap = QPixmap(max(1, int(self.width() * scale)), max(1, int(self.height() * scale)))
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(QColor(tokens['BG_DARK']))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rng = random.Random(750)  # Stable artwork; repainting never changes the pattern.
        if theme.startswith('Cipher '):
            self._paint_cipher(painter, rng, tokens)
        elif theme == 'Aurora Borealis':
            self._paint_aurora(painter, rng)
        elif theme == 'Matcha Latte':
            self._paint_matcha(painter, tokens)
        elif theme == 'Old Library':
            self._paint_library(painter, tokens)
        elif theme == 'Coffee Shop':
            self._paint_coffee(painter, tokens)
        elif theme == 'Archive Blue':
            self._paint_archive(painter, tokens)
        elif theme == "Synthwave '84":
            self._paint_synthwave(painter, rng, tokens)
        elif theme == 'Carbon Fiber':
            self._paint_carbon(painter, tokens)
        elif theme == 'Violet Afterburn':
            self._paint_afterburn(painter, tokens)
        elif theme == 'Crimson Meridian':
            self._paint_meridian(painter, tokens)
        painter.end()
        self._render_count += 1
        return pixmap

    def _paint_cipher(self, painter, rng, tokens):
        font = QFont('Menlo')
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(13)
        painter.setFont(font)
        alphabet = '01<>/{}[]:=+*ｱｲｳｴｵｶｷｸｹｺ'
        for x in range(12, self.width(), 24):
            head = rng.randrange(0, max(1, self.height()))
            length = rng.randint(8, 28)
            # Strongest at the sides; a calmer center protects the empty-state text.
            edge = abs(x / max(1, self.width()) - 0.5) * 2
            for index in range(length):
                y = head - index * 18
                if y < -18 or y > self.height():
                    continue
                color = QColor(tokens['PRIMARY_HOVER'] if index == 0 else tokens['PRIMARY'])
                opacity = (0.30 if index == 0 else 0.16 * (1 - index / length)) * (0.45 + 0.55 * edge)
                color.setAlphaF(opacity)
                painter.setPen(color)
                painter.drawText(x, y, rng.choice(alphabet))
        # Still scan lines: subtle texture, never flickering or scrolling.
        painter.setPen(QPen(QColor(255, 255, 255, 4), 1))
        for y in range(0, self.height(), 5):
            painter.drawLine(0, y, self.width(), y)

    def _paint_aurora(self, painter, rng):
        width, height = self.width(), self.height()
        # Soft frozen ribbons below the stars, confined mostly to the edges.
        for shift, color in ((0, QColor(43, 211, 158, 26)), (0.10, QColor(105, 101, 242, 24)),
                             (0.22, QColor(40, 173, 229, 26))):
            ribbon = QPainterPath()
            ribbon.moveTo(-50, height * (0.18 + shift))
            ribbon.cubicTo(width * .3, -height * .18, width * .58, height * .45, width + 50, height * (.1 + shift))
            ribbon.lineTo(width + 50, height * (.3 + shift))
            ribbon.cubicTo(width * .55, height * .64, width * .24, height * .02, -50, height * (.34 + shift))
            ribbon.closeSubpath()
            gradient = QLinearGradient(0, 0, width, height * .6)
            gradient.setColorAt(0, color)
            gradient.setColorAt(.5, QColor(color.red(), color.green(), color.blue(), 9))
            gradient.setColorAt(1, color)
            painter.fillPath(ribbon, gradient)
        count = min(400, max(45, width * height // 5000))
        for _ in range(count):
            x, y = rng.random() * width, rng.random() * height
            radius = rng.choice((0.5, 0.65, 0.8, 1.1))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(200, 225, 255, rng.randint(40, 115)))
            painter.drawEllipse(QRectF(x, y, radius * 2, radius * 2))

    @staticmethod
    def _ink(tokens, role, alpha):
        color = QColor(tokens[role])
        color.setAlpha(alpha)
        return color

    def _paint_meridian(self, painter, tokens):
        """An engraved celestial meridian: compass rose and atlas arcs at the edges."""
        width, height = self.width(), self.height()
        # Atlas contour lines and a plotted route make this a whole chart rather
        # than a single corner icon. Fine lines remain below the UI's contrast.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(9):
            contour = QPainterPath()
            contour.moveTo(width * .36, height + 35 + index * 15)
            contour.cubicTo(width * .47, height * .63 + index * 13,
                            width * .70, height * .91 - index * 17,
                            width + 25, height * .35 + index * 16)
            painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 12 + index % 3 * 3), .8))
            painter.drawPath(contour)
        painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 20), 1, Qt.PenStyle.DashLine))
        route = QPainterPath()
        route.moveTo(width * .56, height * .88)
        route.cubicTo(width * .69, height * .54, width * .82, height * .66,
                      width * .97, height * .25)
        painter.drawPath(route)
        for x, y in ((.56, .88), (.72, .65), (.88, .48), (.97, .25)):
            painter.drawEllipse(QRectF(width*x-3, height*y-3, 6, 6))
        painter.save()
        painter.translate(width * .89, height * .79)
        radius = min(width, height) * .23
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Engraved degree scales and alternating compass points.
        for factor in (.69, .90, 1.02):
            painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 24), .8))
            painter.drawEllipse(QRectF(-radius*factor, -radius*factor, radius*factor*2, radius*factor*2))
        for angle in range(0, 360, 5):
            painter.save(); painter.rotate(angle)
            painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 32 if angle % 30 == 0 else 19), .8))
            painter.drawLine(0, int(-radius*1.02), 0, int(-radius*(.94 if angle % 30 == 0 else .98)))
            painter.restore()
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 25), 1))
        for tilt in (-28, 28):
            painter.save(); painter.rotate(tilt)
            painter.drawEllipse(QRectF(-radius * .40, -radius, radius * .80, radius * 2))
            painter.restore()
        painter.drawEllipse(QRectF(-radius, -radius * .28, radius * 2, radius * .56))
        painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 29), 1))
        for angle in range(0, 360, 45):
            painter.save(); painter.rotate(angle)
            tip = radius * (.85 if angle % 90 == 0 else .54)
            rose = QPainterPath(); rose.moveTo(0, -tip)
            rose.lineTo(radius * .055, 0); rose.lineTo(0, radius * .16)
            rose.lineTo(-radius * .055, 0); rose.closeSubpath()
            painter.fillPath(rose, self._ink(tokens, 'PRIMARY', 13))
            painter.drawPath(rose); painter.restore()
        painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 38), .8))
        font = QFont('Georgia'); font.setPixelSize(max(9, int(radius*.06)))
        painter.setFont(font)
        for label, x, y in (('N', -.035, -1.10), ('E', 1.07, .025), ('S', -.03, 1.15), ('W', -1.16, .025)):
            painter.drawText(QRectF(radius*x, radius*y-12, 20, 20), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()
        # Small atlas grid fragments stay at the opposite edge, leaving the center quiet.
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 18), 1))
        for i in range(5):
            x = 20 + i * 22
            painter.drawLine(x, 22, x, 116)
            painter.drawLine(20, 28 + i * 22, 116, 28 + i * 22)
        rng = random.Random(104)
        for _ in range(48):
            x, y = rng.uniform(width*.40, width), rng.uniform(0, height)
            if abs(x-width*.64) < width*.13 and abs(y-height*.46) < height*.20:
                continue
            painter.setPen(QPen(self._ink(tokens, 'SECONDARY', rng.randint(12, 32)), .8))
            painter.drawLine(int(x-2), int(y), int(x+2), int(y))
            painter.drawLine(int(x), int(y-2), int(x), int(y+2))

    def _paint_matcha(self, painter, tokens):
        # An edge-anchored tea bowl, concentric tea swirls and rising steam.
        # Coordinates are bounded in logical pixels, so small windows keep a calm center.
        width, height = self.width(), self.height()
        # A frozen brush of tea follows the lower canvas, with individual
        # bristle marks and a leaf branch to echo a matcha preparation tray.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(12):
            stroke = QPainterPath()
            stroke.moveTo(width*.24, height*(.91+index*.006))
            stroke.cubicTo(width*.46, height*(.74+index*.007), width*.66,
                           height*(.82+index*.007), width*1.05, height*(.61+index*.009))
            painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 11 + index % 4), 1.0))
            painter.drawPath(stroke)
        self._paint_leaf_branch(painter, tokens, width*.88, height*.44,
                                min(width, height)*.22, -24)
        size = min(240.0, width * .29, height * .36)
        painter.save()
        painter.translate(width - size * .65, height - size * .35)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 32), 1.5))
        bowl = QPainterPath()
        bowl.moveTo(-size * .62, -size * .28)
        bowl.cubicTo(-size * .55, size * .48, size * .55, size * .48, size * .62, -size * .28)
        painter.drawPath(bowl)
        for factor in (1.0, .72, .43):
            painter.drawEllipse(QRectF(-size * .62 * factor, -size * (.28 + .11 * factor),
                                      size * 1.24 * factor, size * .22 * factor))
        painter.setPen(QPen(self._ink(tokens, 'TEXT_LIGHT', 20), 2))
        for offset in (-.25, .03, .3):
            steam = QPainterPath()
            steam.moveTo(size * offset, -size * .49)
            steam.cubicTo(size * (offset - .28), -size * .86,
                          size * (offset + .32), -size * 1.06, size * offset, -size * 1.5)
            painter.drawPath(steam)
        painter.restore()
        # Bamboo whisk: bound handle, fine curved tines and a warm-gold rim.
        painter.save()
        painter.translate(width-size*1.25, height-size*.16)
        painter.rotate(-22)
        painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 26), 1))
        painter.drawRoundedRect(QRectF(-size*.035, -size*.49, size*.07, size*.32), 3, 3)
        for index in range(-5, 6):
            tine = QPainterPath()
            tine.moveTo(index*size*.004, -size*.18)
            tine.cubicTo(index*size*.024, -size*.10, index*size*.03,
                         size*.15, index*size*.014, size*.17)
            painter.drawPath(tine)
        for y in (-.22, -.20, -.18):
            painter.drawLine(int(-size*.04), int(size*y), int(size*.04), int(size*y))
        painter.restore()
        # A small seigaiha-inspired fan pattern rather than a full-screen texture.
        painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 15), 1))
        for row in range(3):
            for column in range(5):
                x = column * 34 - (17 if row % 2 else 0)
                y = 15 + row * 19
                for radius in (9, 14, 19):
                    painter.drawArc(QRectF(x-radius, y-radius, radius*2, radius*2), 0, 180*16)
        # Two broad frozen tea strokes at the opposite edge.
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 17), 2))
        for offset in (0, 24):
            swirl = QPainterPath()
            swirl.moveTo(-30, height * .65 + offset)
            swirl.cubicTo(width * .18, height * .52 + offset, width * .19,
                          height * .9 + offset, -30, height * .87 + offset)
            painter.drawPath(swirl)

    def _paint_leaf_branch(self, painter, tokens, x, y, size, angle):
        """Fine tea leaves, with veins, using only existing palette colors."""
        painter.save(); painter.translate(x, y); painter.rotate(angle)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 27), 1))
        stem = QPainterPath(); stem.moveTo(0, size*.5)
        stem.cubicTo(-size*.08, 0, size*.1, -size*.25, 0, -size*.5)
        painter.drawPath(stem)
        for index in range(5):
            cy = size*(.35-index*.16)
            side = -1 if index % 2 else 1
            leaf = QPainterPath(); leaf.moveTo(0, cy)
            leaf.cubicTo(size*.08*side, cy-size*.18, size*.26*side, cy-size*.14,
                         size*.31*side, cy-size*.20)
            leaf.cubicTo(size*.28*side, cy+size*.03, size*.08*side, cy+size*.07, 0, cy)
            painter.fillPath(leaf, self._ink(tokens, 'PRIMARY', 8))
            painter.drawPath(leaf)
            vein = QPainterPath(); vein.moveTo(0, cy)
            vein.quadTo(size*.18*side, cy-size*.05, size*.31*side, cy-size*.20)
            painter.drawPath(vein)
        painter.restore()

    def _paint_library(self, painter, tokens):
        width, height = self.width(), self.height()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Tall bookcases, wood rails and varied leather volumes give the room
        # depth. Shelves live at the right, rather than under the central text.
        left = width*.79
        right = width-18
        painter.setPen(QPen(self._ink(tokens, 'WARNING', 19), 1))
        painter.drawRoundedRect(QRectF(left-12, height*.19, right-left+22, height*.76), 5, 5)
        for x in (left-8, left-3, right+3, right+8):
            painter.drawLine(int(x), int(height*.20), int(x), int(height*.95))
        rng = random.Random(814)
        for row in range(4):
            bottom = height*(.36+row*.19)
            painter.setPen(QPen(self._ink(tokens, 'WARNING', 24), 1))
            for dy in (0, 5, 8):
                painter.drawLine(int(left-8), int(bottom+dy), int(right+8), int(bottom+dy))
            x = left+2
            while x < right-14:
                spine_width = rng.uniform(12, 23)
                spine_height = min(height*.15, rng.uniform(height*.09, height*.16))
                painter.setPen(QPen(self._ink(tokens, 'WARNING', rng.randint(17, 28)), .8))
                painter.drawRoundedRect(QRectF(x, bottom-spine_height, spine_width-2, spine_height), 2, 2)
                for y in (bottom-spine_height+7, bottom-spine_height+11, bottom-8):
                    painter.drawLine(int(x+3), int(y), int(x+spine_width-5), int(y))
                if spine_width > 17:
                    painter.drawEllipse(QRectF(x+spine_width/2-2, bottom-spine_height*.60, 4, 9))
                x += spine_width
        # An open book on a reading table, pages fanning out along the bottom.
        painter.save(); painter.translate(width*.62, height*.94)
        size = min(width*.18, height*.19)
        painter.setPen(QPen(self._ink(tokens, 'TEXT_LIGHT', 18), .9))
        for offset in (0, 4, 8):
            pages = QPainterPath(); pages.moveTo(0, offset)
            pages.cubicTo(-size*.3, -size*.28+offset, -size*.7, -size*.22+offset, -size, -size*.08+offset)
            pages.lineTo(-size*.95, -size*.52+offset)
            pages.cubicTo(-size*.6, -size*.66+offset, -size*.3, -size*.58+offset, 0, -size*.4+offset)
            pages.cubicTo(size*.3, -size*.58+offset, size*.6, -size*.66+offset, size*.95, -size*.52+offset)
            pages.lineTo(size, -size*.08+offset)
            pages.cubicTo(size*.7, -size*.22+offset, size*.3, -size*.28+offset, 0, offset)
            painter.drawPath(pages)
        painter.drawLine(0, int(-size*.4), 0, 0)
        painter.setPen(QPen(self._ink(tokens, 'WARNING', 12), .8))
        for row in range(4):
            for side in (-1, 1):
                line = QPainterPath(); line.moveTo(side*size*.12, -size*(.31+row*.055))
                line.quadTo(side*size*.48, -size*(.46+row*.055), side*size*.80, -size*(.31+row*.055))
                painter.drawPath(line)
        painter.restore()
        # A faint bookplate corner and paper grain near the margins.
        painter.setPen(QPen(self._ink(tokens, 'TEXT_GRAY', 13), 1))
        for inset in (16, 22):
            painter.drawLine(inset, 12, inset, 95)
            painter.drawLine(inset, inset, 155, inset)
        for y in range(120, height - 40, 28):
            painter.drawLine(8, y, 35 + (y % 17), y)

    def _paint_coffee(self, painter, tokens):
        width, height = self.width(), self.height()
        # A sweeping, irregular splash crosses the middle like spilled espresso.
        # Transparent coffee/crema layers stay underneath result cards and text.
        splash = QPainterPath()
        splash.moveTo(-35, height*.67)
        splash.cubicTo(width*.11, height*.73, width*.17, height*.34, width*.30, height*.50)
        splash.cubicTo(width*.43, height*.64, width*.53, height*.36, width*.65, height*.42)
        splash.cubicTo(width*.78, height*.49, width*.85, height*.30, width+35, height*.36)
        splash.lineTo(width+35, height*.43)
        splash.cubicTo(width*.82, height*.38, width*.76, height*.59, width*.64, height*.51)
        splash.cubicTo(width*.54, height*.44, width*.42, height*.75, width*.29, height*.58)
        splash.cubicTo(width*.16, height*.43, width*.13, height*.84, -35, height*.75)
        splash.closeSubpath()
        coffee = QLinearGradient(0, height*.7, width, height*.38)
        coffee.setColorAt(0, self._ink(tokens, 'PRIMARY', 19))
        coffee.setColorAt(.45, self._ink(tokens, 'WARNING', 10))
        coffee.setColorAt(.7, self._ink(tokens, 'PRIMARY', 22))
        coffee.setColorAt(1, self._ink(tokens, 'WARNING', 17))
        painter.fillPath(splash, coffee)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._ink(tokens, 'WARNING', 10), 1))
        painter.drawPath(splash)
        # Thin jets pull away from the main spill in uneven fingers; these are
        # liquid silhouettes rather than another set of abstract wave bands.
        for x, y, direction in ((.26, .55, -1), (.64, .47, -1), (.79, .46, 1)):
            jet = QPainterPath(); jet.moveTo(width*x, height*y)
            jet.cubicTo(width*(x+.045), height*(y+direction*.025), width*(x+.03),
                        height*(y+direction*.13), width*(x+.085), height*(y+direction*.105))
            jet.cubicTo(width*(x+.045), height*(y+direction*.15), width*(x+.065),
                        height*(y+direction*.055), width*(x+.025), height*(y+.015))
            jet.closeSubpath()
            painter.fillPath(jet, self._ink(tokens, 'PRIMARY', 14))
        # Detached teardrops and crema threads avoid the old circular stains.
        rng = random.Random(208)
        for _ in range(34):
            x = rng.uniform(.04, .99)*width
            y = height*(.69-.32*x/max(1,width)+rng.uniform(-.10,.08))
            length = rng.uniform(3, 11)
            painter.save(); painter.translate(x, y); painter.rotate(rng.uniform(-70, -30))
            drop = QPainterPath(); drop.moveTo(0, -length)
            drop.cubicTo(length*.65, 0, length*.45, length*.48, 0, length*.48)
            drop.cubicTo(-length*.45, length*.48, -length*.65, 0, 0, -length)
            painter.fillPath(drop, self._ink(tokens, 'WARNING', rng.randint(10, 19)))
            painter.restore()
        for offset in (0, 9, 18):
            crema = QPainterPath(); crema.moveTo(width*.70, height*.50+offset)
            crema.cubicTo(width*.80, height*.57+offset, width*.86, height*.34+offset,
                          width+20, height*.41+offset)
            painter.setPen(QPen(self._ink(tokens, 'TEXT_LIGHT', 13), .9))
            painter.drawPath(crema)
        scale = min(1.0, width / 850.0, height / 560.0)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # A small ceramic mug on a saucer, tucked into the lower-right margin.
        painter.translate(width - 210 * scale, height - 155 * scale)
        painter.scale(scale, scale)
        painter.setPen(QPen(self._ink(tokens, 'WARNING', 26), 1.5))
        mug = QPainterPath()
        mug.moveTo(24, 49)
        mug.lineTo(29, 115)
        mug.cubicTo(30, 140, 120, 140, 123, 115)
        mug.lineTo(128, 49)
        painter.drawPath(mug)
        painter.drawEllipse(QRectF(24, 40, 104, 18))
        handle = QPainterPath()
        handle.moveTo(128, 60)
        handle.cubicTo(180, 45, 176, 111, 124, 109)
        handle.moveTo(133, 72)
        handle.cubicTo(158, 65, 160, 95, 129, 96)
        painter.drawPath(handle)
        saucer = QPainterPath()
        saucer.moveTo(7, 135)
        saucer.cubicTo(15, 152, 145, 155, 164, 135)
        saucer.moveTo(12, 134)
        saucer.cubicTo(44, 141, 123, 142, 158, 134)
        painter.drawPath(saucer)
        # Gentle, frozen steam strokes; no timer or changing geometry.
        painter.setPen(QPen(self._ink(tokens, 'TEXT_LIGHT', 18), 1.5))
        for x, rise in ((49, 0), (77, -12), (105, 5)):
            steam = QPainterPath()
            steam.moveTo(x, 27)
            steam.cubicTo(x - 17, 4, x + 18, -17, x, -44 + rise)
            painter.drawPath(steam)
        painter.restore()

        # Hand-placed little beans echo the mug without covering the results area.
        for x, y, angle in ((32, 38, -28), (69, 58, 24), (106, 32, -12),
                            (33, height - 35, 18), (66, height - 54, -35)):
            painter.save()
            painter.translate(x * scale, y if y > height / 2 else y * scale)
            painter.rotate(angle)
            painter.scale(scale, scale)
            painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 30), 1.3))
            bean = QPainterPath()
            bean.moveTo(0, -11)
            bean.cubicTo(14, -10, 14, 10, 0, 11)
            bean.cubicTo(-13, 10, -13, -10, 0, -11)
            seam = QPainterPath()
            seam.moveTo(1, -8)
            seam.cubicTo(-5, -2, 5, 2, -1, 8)
            painter.drawPath(bean)
            painter.drawPath(seam)
            painter.restore()

    def _paint_archive(self, painter, tokens):
        width, height = self.width(), self.height()
        scale = min(1.0, width / 850.0, height / 560.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Echo the original app's simple document rows and desktop panel borders.
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 16), 1))
        for inset in (14, 20):
            painter.drawLine(inset, 16, inset, 90)
            painter.drawLine(inset, inset, 150, inset)
        painter.save()
        painter.translate(width - 160 * scale, height - 155 * scale)
        painter.scale(scale, scale)
        page = QPainterPath()
        page.moveTo(16, 0)
        page.lineTo(83, 0)
        page.lineTo(108, 25)
        page.lineTo(108, 126)
        page.lineTo(16, 126)
        page.closeSubpath()
        page.moveTo(83, 0)
        page.lineTo(83, 25)
        page.lineTo(108, 25)
        painter.drawPath(page)
        painter.drawLine(8, 12, 8, 134)
        painter.drawLine(8, 134, 97, 134)
        for y, length in ((47, 62), (60, 48), (73, 58), (94, 35)):
            painter.drawLine(31, y, 31 + length, y)
        painter.restore()

    def _paint_synthwave(self, painter, rng, tokens):
        width, height = self.width(), self.height()
        horizon = height * .76
        # A frozen perspective plane. The quiet upper canvas protects results.
        painter.setPen(QPen(self._ink(tokens, 'ACCENT_CYAN', 20), 1))
        for offset in range(-6, 7):
            painter.drawLine(int(width * .64), int(horizon), int(width * .64 + offset * width / 6), height)
        for depth in (.03, .09, .18, .31, .49, .73, 1.0):
            y = horizon + (height - horizon) * depth
            painter.drawLine(0, int(y), width, int(y))
        radius = min(95.0, width * .13, height * .15)
        cx, cy = width * .79, horizon - radius * .58
        painter.save()
        disc = QPainterPath()
        disc.addEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
        painter.setClipPath(disc)
        sunset = QLinearGradient(0, cy - radius, 0, cy + radius)
        sunset.setColorAt(0, self._ink(tokens, 'SECONDARY', 23))
        sunset.setColorAt(.55, self._ink(tokens, 'ACCENT_PINK', 25))
        sunset.setColorAt(1, self._ink(tokens, 'PRIMARY', 14))
        # Thin missing bands become wider toward the bottom of the sunset.
        painter.fillRect(QRectF(cx-radius, cy-radius, radius*2, radius*.82), sunset)
        y = cy - radius * .18
        while y < cy + radius:
            painter.fillRect(QRectF(cx-radius, y, radius*2, radius*.10), sunset)
            y += radius * .17
        painter.restore()
        mountains = QPainterPath()
        mountains.moveTo(0, horizon)
        for x, y in ((.08, .72), (.16, .75), (.23, .69), (.32, .75), (.42, .73), (.52, .76),
                     (.66, .72), (.71, .75), (.86, .70), (.94, .74), (1, .72)):
            mountains.lineTo(width * x, height * y)
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 23), 1))
        painter.drawPath(mountains)
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(min(65, max(18, width * height // 19000))):
            x, y = rng.random() * width, rng.random() * height * .3
            painter.setBrush(self._ink(tokens, 'TEXT_LIGHT', rng.randint(20, 45)))
            painter.drawEllipse(QRectF(x, y, 1.2, 1.2))

    def _paint_carbon(self, painter, tokens):
        # One tiny 2-over/2-under twill tile, rotated to make diagonal carbon bundles.
        # Each bundle has individual filaments and a soft bevel, not flat checkers.
        unit = 8
        tile = QPixmap(unit * 4, unit * 4)
        tile.fill(QColor(tokens['BG_DARK']))
        weave = QPainter(tile)
        weave.setRenderHint(QPainter.RenderHint.Antialiasing)
        for row in range(4):
            for column in range(4):
                vertical = (row - column) % 4 < 2
                x, y = column * unit, row * unit
                gradient = QLinearGradient(x, y, x + (unit if vertical else 0), y + (0 if vertical else unit))
                gradient.setColorAt(0, QColor('#101010'))
                gradient.setColorAt(.42, QColor('#1A1A1A'))
                gradient.setColorAt(1, QColor('#0E0E0E'))
                weave.fillRect(QRectF(x, y, unit, unit), gradient)
                weave.setPen(QPen(QColor(255, 255, 255, 7), .65))
                for filament in (2, 4, 6):
                    if vertical:
                        weave.drawLine(x + filament, y, x + filament, y + unit)
                    else:
                        weave.drawLine(x, y + filament, x + unit, y + filament)
        weave.end()
        brush = QBrush(tile)
        brush.setTransform(QTransform().rotate(45))
        painter.fillRect(self.rect(), brush)
        painter.setPen(QPen(self._ink(tokens, 'TEXT_LIGHT', 12), 1))
        for x in (14, self.width() - 14):
            painter.drawLine(x, self.height() - 50, x, self.height() - 14)
        painter.drawLine(self.width() - 64, self.height() - 14, self.width() - 14, self.height() - 14)

    def _paint_afterburn(self, painter, tokens):
        width, height = self.width(), self.height()
        # Layered ion-plume filaments curve out of an engraved engine throat.
        # Speed streaks and pressure contours make the motif recognizably kinetic,
        # even though every pixel is static and cached.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(18):
            filament = QPainterPath()
            filament.moveTo(width*.20, height*(1.03-index*.003))
            filament.cubicTo(width*.48, height*(.94-index*.004), width*.63,
                             height*(.51+index*.013), width*.92, height*(.59+index*.009))
            painter.setPen(QPen(self._ink(tokens, 'PRIMARY' if index%3 else 'SECONDARY', 13+index%4*3), .8))
            painter.drawPath(filament)
        painter.save(); painter.translate(width*.92, height*.67); painter.rotate(-12)
        size = min(width, height)*.14
        painter.setPen(QPen(self._ink(tokens, 'ACCENT_PURPLE', 37), 1))
        for offset in (0, 7, 14):
            painter.drawEllipse(QRectF(-size*.20+offset, -size*.55, size*.38, size*1.10))
        for angle in range(0, 360, 30):
            radians = math.radians(angle)
            x, y = math.cos(radians)*size*.20, math.sin(radians)*size*.55
            painter.drawLine(int(x), int(y), int(x+size*.5), int(y*.74))
        painter.drawEllipse(QRectF(size*.5-size*.14, -size*.4, size*.28, size*.8))
        painter.restore()
        for index in range(7):
            cx, cy = width*(.84-index*.066), height*(.69+index*.025)
            radius = min(width,height)*(.027-index*.0017)
            shock = QPainterPath(); shock.moveTo(cx-radius*1.6, cy)
            shock.lineTo(cx, cy-radius*.55); shock.lineTo(cx+radius*1.6, cy)
            shock.lineTo(cx, cy+radius*.55); shock.closeSubpath()
            painter.fillPath(shock, self._ink(tokens, 'SECONDARY', 8))
            painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 25-index*2), .9))
            painter.drawPath(shock)
        rng = random.Random(884)
        for _ in range(46):
            x, y = rng.uniform(.40, 1)*width, rng.uniform(.10, .94)*height
            if abs(x-width*.65)<width*.14 and abs(y-height*.46)<height*.17:
                continue
            painter.setPen(QPen(self._ink(tokens, 'ACCENT_PURPLE', rng.randint(12, 30)), .8))
            painter.drawLine(int(x), int(y), int(x+rng.uniform(3, 18)), int(y-3))
        # Thin, tapered exhaust ribbons hug the lower-right edge and fade inward.
        gradient = QLinearGradient(width * .5, height * .85, width, height * .7)
        gradient.setColorAt(0, self._ink(tokens, 'PRIMARY', 0))
        gradient.setColorAt(.45, self._ink(tokens, 'ACCENT_PURPLE', 15))
        gradient.setColorAt(.8, self._ink(tokens, 'PRIMARY', 24))
        gradient.setColorAt(1, self._ink(tokens, 'SECONDARY', 28))
        for shift in (0, .055, .11):
            ribbon = QPainterPath()
            ribbon.moveTo(width * .44, height * (.95 - shift))
            ribbon.cubicTo(width * .70, height * (.99 - shift), width * .77,
                           height * (.63 - shift), width + 30, height * (.72 - shift))
            ribbon.lineTo(width + 30, height * (.79 - shift))
            ribbon.cubicTo(width * .77, height * (.72 - shift), width * .72,
                           height * (1.01 - shift), width * .44, height * (.95 - shift))
            painter.fillPath(ribbon, gradient)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._ink(tokens, 'SECONDARY', 19), 1))
        # Small shock-diamond contours suggest exhaust pressure rather than flames.
        for index in range(4):
            cx = width - 30 - index * 46
            cy = height * .8 + index * 13
            radius = 18 - index * 2
            diamond = QPainterPath()
            diamond.moveTo(cx - radius, cy)
            diamond.quadTo(cx, cy - radius * .6, cx + radius, cy)
            diamond.quadTo(cx, cy + radius * .6, cx - radius, cy)
            painter.drawPath(diamond)
        painter.setPen(QPen(self._ink(tokens, 'PRIMARY', 18), 1.2))
        for shift in (0, 12):
            wisp = QPainterPath()
            wisp.moveTo(-15, height * .18 + shift)
            wisp.cubicTo(width * .08, height * .02 + shift, width * .15,
                         height * .18 + shift, width * .24, height * .08 + shift)
            painter.drawPath(wisp)
