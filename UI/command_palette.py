from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


class CommandPaletteDialog(QDialog):
    command_selected = Signal(str)

    def __init__(self, commands: List[Tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.resize(560, 380)
        self._commands = list(commands or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Type a command...")
        self.search.textChanged.connect(self._refresh_items)
        root.addWidget(self.search)

        self.list = QListWidget(self)
        self.list.itemDoubleClicked.connect(self._accept_item)
        root.addWidget(self.list, 1)

        self._refresh_items("")

    def _refresh_items(self, text: str) -> None:
        query = str(text or "").strip().lower()
        self.list.clear()
        for cmd_id, label in self._commands:
            row = f"{label}".strip()
            if query and query not in row.lower():
                continue
            item = QListWidgetItem(row)
            item.setData(Qt.ItemDataRole.UserRole, str(cmd_id))
            self.list.addItem(item)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def keyPressEvent(self, event):  # type: ignore[override]
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            item = self.list.currentItem()
            if item is not None:
                self._accept_item(item)
                return
        super().keyPressEvent(event)

    def _accept_item(self, item: QListWidgetItem) -> None:
        command_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not command_id:
            return
        self.command_selected.emit(command_id)
        self.accept()
