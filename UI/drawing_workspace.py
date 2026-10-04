"""Compact drawing presentation; the canvas and saved answer format stay shared."""
from PySide6.QtCore import QObject, Qt, QEvent, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QPushButton, QMenu, QWidgetAction, QGridLayout, QMessageBox)
from Utils.gui_utils import Colors
from UI.theme import get_theme_manager
from UI.exam_interactions import button_style


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.layout():
            _clear(item.layout())
        elif item.widget():
            item.widget().hide()


class DrawingEditorPresentation(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        root = dialog.layout()
        _clear(root)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        dialog.setMinimumSize(660, 500)
        dialog.resize(1050, 760)
        dialog.setWindowTitle('Drawing Answer · Past Paper Studio')
        dialog.canvas.setMinimumSize(300, 260)
        dialog.canvas.setToolTip('Draw with your selected tool. Hold Space and drag, or use the mouse wheel, to pan. Pinch or Ctrl/Cmd + wheel to zoom.')
        self.toolbar = QWidget(dialog)
        self.toolbar_columns = QVBoxLayout(self.toolbar)
        self.toolbar_columns.setContentsMargins(0,0,0,0)
        top = QHBoxLayout()
        self.toolbar_columns.addLayout(top)
        self.toolbar_row = top
        top.setSpacing(6)
        dialog.tool_combo.currentTextChanged.disconnect()
        dialog.tool_combo.clear()
        dialog.tool_combo.setProperty('ppsTranslateItems', True)
        for label, tool in [('Pen','pen'),('Eraser','eraser'),('Line','line'),('Rectangle','rect'),('Ellipse','ellipse'),('Triangle','triangle'),('Arrow','arrow')]:
            dialog.tool_combo.addItem(label, tool)
        dialog.tool_combo.setMinimumContentsLength(len('Rectangle'))
        dialog.tool_combo.setSizeAdjustPolicy(dialog.tool_combo.SizeAdjustPolicy.AdjustToContents)
        dialog.tool_combo.setToolTip('Select drawing tool')
        dialog.tool_combo.currentIndexChanged.connect(lambda i: dialog.canvas.set_tool(dialog.tool_combo.itemData(i)))
        top.addWidget(dialog.tool_combo)
        width = QLabel('Width')
        top.addWidget(width)
        dialog.width_spin.setMinimumWidth(60)
        dialog.width_spin.setSuffix(' px')
        top.addWidget(dialog.width_spin)
        self.color = QPushButton('Ink color', dialog)
        self.color.setAccessibleName('Drawing ink color')
        menu = QMenu(self.color)
        panel = QWidget(menu)
        grid = QGridLayout(panel)
        grid.setContentsMargins(8, 8, 8, 8)
        names = ['Black','Red','Blue','Green','Gold','Purple','Pink','Teal']
        for i, button in enumerate(dialog._color_buttons):
            button.setToolTip(names[i]);button.setAccessibleName(names[i] + ' ink')
            button.setFixedSize(30,30)
            grid.addWidget(button, i//4, i%4);button.show()
            button.clicked.connect(menu.close)
        grid.addWidget(dialog.custom_color_btn,2,0,1,4)
        dialog.custom_color_btn.setText('Custom color…');dialog.custom_color_btn.show()
        action = QWidgetAction(menu);action.setDefaultWidget(panel);menu.addAction(action)
        self.color.setMenu(menu);top.addWidget(self.color)
        self.guides = QPushButton('Guides', dialog)
        guides = QMenu(self.guides)
        # Keep the existing buttons as the single state source for guide visibility.
        for title, button in [('Ruler',dialog.toggle_ruler_btn),('Protractor',dialog.toggle_protractor_btn)]:
            action = guides.addAction(title);action.setCheckable(True)
            action.toggled.connect(button.setChecked)
            button.toggled.connect(action.setChecked)
        guides.addSeparator()
        guides.addAction('Reset guide positions',self.reset_guides)
        self.guides.setMenu(guides);top.addWidget(self.guides)
        top.addStretch()
        self.history = QWidget()
        history_row = QHBoxLayout(self.history)
        history_row.setContentsMargins(0,0,0,0)
        history_row.setSpacing(6)
        for button in [dialog.undo_btn,dialog.redo_btn,dialog.clear_btn]:
            history_row.addWidget(button);button.show()
        top.addWidget(self.history)
        dialog.tool_combo.show();dialog.width_spin.show()
        root.addWidget(self.toolbar)
        root.addWidget(dialog.canvas,1);dialog.canvas.show()
        footer = QHBoxLayout()
        hint = QLabel('Space + drag to pan · pinch to zoom')
        hint.setWordWrap(True);footer.addWidget(hint,1)
        footer.addWidget(dialog.zoom_spin);dialog.zoom_spin.setMinimumWidth(76);dialog.zoom_spin.show()
        footer.addWidget(dialog.zoom_reset_btn);dialog.zoom_reset_btn.show()
        dialog.zoom_reset_btn.setText('Reset zoom')
        footer.addWidget(dialog.cancel_btn);dialog.cancel_btn.show()
        footer.addWidget(dialog.save_btn);dialog.save_btn.setText('Save / Done');dialog.save_btn.show()
        dialog.save_btn.setDefault(True)
        root.addLayout(footer)
        get_theme_manager().theme_changed.connect(self.refresh_theme)
        dialog.clear_btn.clicked.disconnect()
        dialog.clear_btn.clicked.connect(self.confirm_clear)
        dialog.canvas.history_changed.connect(self.update_history)
        dialog.installEventFilter(self)
        self._tool_size_timer = QTimer(self)
        self._tool_size_timer.setSingleShot(True)
        self._tool_size_timer.timeout.connect(self.reserve_tool_width)
        self.refresh_theme()
        self.update_history()

    def confirm_clear(self):
        if self.dialog.canvas._saved_ink or self.dialog.canvas.undo_stack or self.dialog.canvas.redo_stack:
            if QMessageBox.question(self.dialog,'Clear drawing','Clear the ink on this canvas? You can undo this action.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self.dialog.canvas.clear_canvas()

    def update_history(self):
        canvas = self.dialog.canvas
        self.dialog.undo_btn.setEnabled(bool(canvas.undo_stack))
        self.dialog.redo_btn.setEnabled(bool(canvas.redo_stack))

    def eventFilter(self, watched, event):
        if watched is self.dialog and event.type() in (QEvent.Type.Show, QEvent.Type.FontChange, QEvent.Type.LanguageChange):
            self._tool_size_timer.start(0)
        if watched is self.dialog and event.type()==QEvent.Type.Resize:
            if self.dialog.width()<900:
                self.toolbar_row.removeWidget(self.history)
                self.toolbar_columns.addWidget(self.history,0,Qt.AlignmentFlag.AlignRight)
            else:
                self.toolbar_columns.removeWidget(self.history)
                self.toolbar_row.addWidget(self.history)
        return False

    def reserve_tool_width(self):
        combo = self.dialog.tool_combo
        width = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count())) + 54
        combo.setFixedWidth(width)

    def reset_guides(self):
        from PySide6.QtCore import QPointF
        canvas = self.dialog.canvas
        center = QPointF(canvas.width()/2, canvas.height()/2)
        canvas.ruler.center = QPointF(center);canvas.ruler.angle=0
        canvas.protractor.center = QPointF(center);canvas.protractor.angle=0
        canvas.update()

    def refresh_theme(self, *_):
        d = self.dialog
        text = Colors.TEXT_LIGHT
        d.setStyleSheet(f'QDialog {{background:{Colors.BG_DARK};color:{text};}} QLabel {{color:{text};font-size:14px;}} QPushButton,QComboBox,QSpinBox {{background:{Colors.BG_CARD};color:{text};border:1px solid {Colors.BG_LIGHT};border-radius:6px;padding:6px;font-size:14px;min-height:26px;}} QPushButton:hover {{background:{Colors.BG_LIGHT};}} QComboBox QAbstractItemView {{background:{Colors.BG_CARD};color:{text};font-size:14px;}} QMenu {{background:{Colors.BG_CARD};color:{text};padding:4px;}} QMenu::item {{padding:6px 12px;font-size:14px;}} QMenu::item:selected {{background:{Colors.BG_LIGHT};}}')
        d.setStyleSheet(d.styleSheet()+button_style() + f'QComboBox:hover,QSpinBox:hover {{border-color:{Colors.PRIMARY};}} QComboBox:focus,QSpinBox:focus {{border-color:{Colors.PRIMARY};}}')
        d.save_btn.setStyleSheet(button_style(Colors.PRIMARY,Colors.TEXT_WHITE,primary=True))
        self._tool_size_timer.start(0)
        for button in (d.undo_btn,d.redo_btn,d.clear_btn,self.color,self.guides,d.save_btn,d.cancel_btn):
            button.setAccessibleName(button.text())
            button.setToolTip(button.text())
        for button in (d.toggle_ruler_btn,d.toggle_protractor_btn,d.zoom_reset_btn,d.custom_color_btn):
            button.setStyleSheet('')
