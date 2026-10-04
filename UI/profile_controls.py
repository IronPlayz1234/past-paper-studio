"""Local profile preferences and theme-aware vector branding."""
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Qt, QSize, QRectF, QTimer, QBuffer, QIODevice
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QFont, QImageReader, QPixmap
from PySide6.QtWidgets import (QWidget, QPushButton, QLabel, QLineEdit, QHBoxLayout,
    QVBoxLayout, QGridLayout, QMenu, QWidgetAction, QFileDialog, QMessageBox, QSizePolicy)
from Utils.gui_utils import ConfigManager, Colors
from UI.theme import get_theme_manager, ThemeManager
from UI.localization import get_locale_manager, tr
from Core.runtime_paths import user_data_path
from Core.atomic_storage import atomic_write_bytes
from Data.app_metadata import APP_VERSION


class Profile(QObject):
    changed = Signal()

    def name(self):
        return str(ConfigManager.get_value('profile.display_name', '') or '').strip()[:80]

    def image_path(self):
        return str(ConfigManager.get_value('profile.avatar_path', '') or '')

    def set_name(self, name):
        ConfigManager.set_value('profile.display_name', str(name).strip()[:80])
        self.changed.emit()

    def set_image(self, source):
        reader = QImageReader(str(source)); reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise ValueError(tr('This image could not be opened. Choose another image.'))
        image = image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, 'PNG'):
            raise ValueError(tr('This image could not be opened. Choose another image.'))
        path = str(user_data_path('profile_avatar.png'))
        atomic_write_bytes(path, bytes(buffer.data()))
        ConfigManager.set_value('profile.avatar_path', path)
        self.changed.emit()

    def remove_image(self):
        ConfigManager.set_value('profile.avatar_path', '')
        self.changed.emit()
        # Only delete our managed copy; never the user's original image.
        Path(user_data_path('profile_avatar.png')).unlink(missing_ok=True)


_profile = None

def get_profile():
    global _profile
    if _profile is None:
        from PySide6.QtWidgets import QApplication
        _profile = Profile(QApplication.instance())
    return _profile


class Avatar(QWidget):
    def __init__(self, parent=None, size=36):
        super().__init__(parent); self.setFixedSize(size, size)
        self._pixmap = QPixmap()
        get_profile().changed.connect(self.reload)
        get_theme_manager().theme_changed.connect(self.update)
        self.reload()

    def reload(self):
        path = get_profile().image_path()
        self._pixmap = QPixmap.fromImage(QImageReader(path).read()) if path else QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath(); clip.addEllipse(rect)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(Colors.BG_LIGHT))
        if not self._pixmap.isNull():
            pixmap = self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width()-pixmap.width())//2, (self.height()-pixmap.height())//2, pixmap)
        else:
            initials = ''.join(part[0] for part in get_profile().name().split()[:2]).upper() or 'S'
            painter.setPen(QColor(ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, Colors.BG_LIGHT)))
            painter.setFont(QFont('Arial', max(12, self.height()//3), QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initials)
        painter.setClipping(False); painter.setPen(QPen(QColor(Colors.PRIMARY), 1))
        painter.drawEllipse(rect)


class StudioLogo(QWidget):
    """Resolution-independent paper monogram and wordmark drawn in active tokens."""
    def __init__(self, parent=None):
        super().__init__(parent); self.setMinimumSize(150, 46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName('Past Paper Studio'); self.setToolTip('Past Paper Studio')
        get_theme_manager().theme_changed.connect(self.update)

    def sizeHint(self):
        return QSize(350, 54)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width()/420, self.height()/64)
        p.translate(0, (self.height()-64*scale)/2); p.scale(scale, scale)
        ink = QColor(ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, Colors.BG_CARD))
        accent = QColor(ThemeManager._ensure_text_contrast(Colors.PRIMARY, Colors.BG_CARD, min_ratio=3.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        for x, y, angle in ((5,18,-12),(11,13,-5)):
            p.save(); p.translate(x,y); p.rotate(angle); p.drawRoundedRect(QRectF(0,0,5,43),2,2); p.restore()
        path = QPainterPath(); path.moveTo(20,58); path.lineTo(20,12)
        path.quadTo(20,5,27,5); path.lineTo(46,5); path.lineTo(62,22)
        path.lineTo(62,33); path.quadTo(62,44,49,44); path.lineTo(30,44)
        path.lineTo(30,54); path.quadTo(30,58,26,58); path.closeSubpath()
        p.setBrush(ink); p.drawPath(path)
        p.setBrush(accent); p.drawRoundedRect(QRectF(31,35,27,8),3,3)
        p.drawRoundedRect(QRectF(31,48,20,7),3,3)
        for y in (24,30): p.drawRoundedRect(QRectF(33,y,17,3),1.5,1.5)
        fold = QPainterPath(); fold.moveTo(46,5); fold.lineTo(62,22); fold.lineTo(51,22); fold.quadTo(46,22,46,17); fold.closeSubpath(); p.drawPath(fold)
        font = QFont('Arial', 26, QFont.Weight.Bold); font.setPixelSize(34); p.setFont(font)
        p.setPen(ink); p.drawText(74,43,'Past Paper')
        offset = p.fontMetrics().horizontalAdvance('Past Paper ')
        p.setPen(accent); p.drawText(74+offset,43,'Studio')


class ProfileEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(10)
        label = QLabel(tr('Name (optional)')); layout.addWidget(label)
        self.name_input = QLineEdit(get_profile().name()); self.name_input.setMaxLength(80)
        self.name_input.setProperty('ppsNoTranslation', True)
        self.name_input.setAccessibleName(tr('Name (optional)'))
        self.name_input.setPlaceholderText(tr('Your name')); layout.addWidget(self.name_input)
        row = QHBoxLayout(); self.avatar = Avatar(self, 52); row.addWidget(self.avatar)
        row.addWidget(QLabel(tr('Profile picture'))); row.addStretch()
        self.change = QPushButton(tr('Change')); self.remove = QPushButton(tr('Remove'))
        row.addWidget(self.change); row.addWidget(self.remove); layout.addLayout(row)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(180)
        self.timer.timeout.connect(self.save_name)
        self.name_input.textEdited.connect(lambda _: self.timer.start())
        self.name_input.editingFinished.connect(self.save_name)
        self.change.clicked.connect(self.choose_image); self.remove.clicked.connect(self.remove_image)
        get_profile().changed.connect(self.sync)
        get_locale_manager().language_changed.connect(self.retranslate)
        self.sync()

    def retranslate(self, *_):
        self.name_input.setPlaceholderText(tr('Your name'))
        self.name_input.setAccessibleName(tr('Name (optional)'))

    def save_name(self):
        self.timer.stop()
        if self.name_input.text().strip() == get_profile().name(): return
        try: get_profile().set_name(self.name_input.text())
        except OSError as error: QMessageBox.warning(self, tr('Profile'), str(error))

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Choose profile picture'), '', 'Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not path: return
        try: get_profile().set_image(path)
        except (ValueError, OSError) as error: QMessageBox.warning(self, tr('Profile'), str(error))

    def remove_image(self):
        try: get_profile().remove_image()
        except OSError as error: QMessageBox.warning(self, tr('Profile'), str(error))

    def sync(self):
        if not self.name_input.hasFocus(): self.name_input.setText(get_profile().name())
        self.remove.setEnabled(bool(get_profile().image_path()))


class ProfileHeader(QWidget):
    def __init__(self, main):
        super().__init__(main.header_card); self.main = main
        self.layout = QGridLayout(self); self.layout.setContentsMargins(0,0,0,0); self.layout.setSpacing(12)
        self.logo = StudioLogo(self); self.layout.addWidget(self.logo,0,0)
        self.layout.addWidget(main.level_selector_card,0,1,Qt.AlignmentFlag.AlignCenter)
        right = QWidget(); box = QHBoxLayout(right); box.setContentsMargins(0,0,0,0); box.addStretch()
        self.control = QPushButton(); self.control.setObjectName('profileControl'); self.control.setCursor(Qt.CursorShape.PointingHandCursor)
        self.control.setFixedSize(180, 48)
        content = QHBoxLayout(self.control); content.setContentsMargins(9,4,9,4); content.setSpacing(8)
        self.avatar = Avatar(self.control); self.avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        content.addWidget(self.avatar)
        self.name_label = QLabel(); self.name_label.setTextFormat(Qt.TextFormat.PlainText); self.name_label.setProperty('ppsNoTranslation',True)
        self.name_label.setMaximumWidth(105); self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        content.addWidget(self.name_label); content.addWidget(QLabel('▾'))
        box.addWidget(self.control); self.layout.addWidget(right,0,2)
        self.layout.setColumnStretch(0,1); self.layout.setColumnStretch(2,1)
        self.menu = QMenu(self.control)
        self.identity_action = QWidgetAction(self.menu)
        identity = QWidget(); details = QVBoxLayout(identity); details.setContentsMargins(12,10,12,10)
        details.addWidget(Avatar(identity,48)); self.menu_name = QLabel(); self.menu_name.setTextFormat(Qt.TextFormat.PlainText); self.menu_name.setProperty('ppsNoTranslation',True)
        details.addWidget(self.menu_name); details.addWidget(QLabel(APP_VERSION))
        self.identity_action.setDefaultWidget(identity); self.menu.addAction(self.identity_action)
        self.settings_action = self.menu.addAction(tr('Open Settings'), main._show_settings_window)
        self.control.clicked.connect(lambda: self.menu.popup(self.control.mapToGlobal(self.control.rect().bottomLeft())))
        get_profile().changed.connect(self.refresh)
        get_theme_manager().theme_changed.connect(self.refresh)
        get_locale_manager().language_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        name = get_profile().name() or tr('Student')
        self.name_label.setText(name if len(name)<=13 else name[:12]+'…')
        self.menu_name.setText(name); self.control.setAccessibleName(tr('Profile')+': '+name)
        self.control.setToolTip(name); self.settings_action.setText(tr('Open Settings'))
        text = ThemeManager._ensure_text_contrast(Colors.TEXT_LIGHT, Colors.BG_CARD)
        self.control.setStyleSheet(f'QPushButton#profileControl {{background:{Colors.BG_LIGHT};color:{text};border:1px solid {Colors.PRIMARY};border-radius:8px;padding:0;min-width:178px;max-width:178px;min-height:46px;max-height:46px;}} QPushButton#profileControl:hover {{background:{Colors.BG_MEDIUM};}} QLabel {{color:{text};background:transparent;border:none;}}')
        self.menu.setStyleSheet(f'QMenu {{background:{Colors.BG_CARD};color:{text};border:1px solid {Colors.PRIMARY};padding:6px;}} QMenu::item {{padding:9px 14px;}} QMenu::item:selected {{background:{Colors.BG_LIGHT};}} QWidget {{background:{Colors.BG_CARD};color:{text};}}')


def install_profile_header(main):
    shell = getattr(main,'_experimental_shell',None)
    header = main.header_card.layout()
    while header.count():
        item = header.takeAt(0)
        if item.widget() and item.widget() is not main.level_selector_card:
            item.widget().hide()
    main.settings_btn.hide()
    if shell:
        shell.title.hide(); shell.header_actions.hide()
    main._profile_header = ProfileHeader(main)
    header.addWidget(main._profile_header)
    header.setDirection(header.Direction.LeftToRight)
