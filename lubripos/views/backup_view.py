"""Backup & Restore page (admin).

Lists every backup (auto/manual/pre-restore) with its size and location, and
lets the admin: take a manual backup now, change the backup folder (e.g. to a
USB stick or synced cloud drive), restore a selected backup, or restore from an
arbitrary file. Restores are destructive, so the service takes a safety backup
first. All heavy lifting lives in BackupService; this is just the UI."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from pathlib import Path

from ..controllers.backup_controller import BackupController

COLUMNS = ["When", "Type", "Size", "Location"]


class BackupView(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.controller = BackupController(ctx)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(14)

        title = QLabel("Backup & Restore")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        # backup folder row
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Backup folder:"))
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        folder_row.addWidget(self.folder, 1)
        change = QPushButton("Change…")
        change.setObjectName("Secondary")
        change.clicked.connect(self._change_folder)
        reset = QPushButton("Use default")
        reset.setObjectName("Secondary")
        reset.clicked.connect(self._reset_folder)
        folder_row.addWidget(change)
        folder_row.addWidget(reset)
        root.addLayout(folder_row)

        tip = QLabel("Tip: point this at a USB drive or a synced cloud folder "
                     "(Google Drive/OneDrive) so backups survive disk failure or theft.")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        root.addWidget(tip)

        actions = QHBoxLayout()
        backup_btn = QPushButton("Back up now")
        backup_btn.clicked.connect(self._backup_now)
        restore_sel = QPushButton("Restore selected")
        restore_sel.setObjectName("Secondary")
        restore_sel.clicked.connect(self._restore_selected)
        restore_file = QPushButton("Restore from file…")
        restore_file.setObjectName("Secondary")
        restore_file.clicked.connect(self._restore_from_file)
        actions.addWidget(backup_btn)
        actions.addWidget(restore_sel)
        actions.addWidget(restore_file)
        actions.addStretch(1)
        root.addLayout(actions)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

    # -- data ---------------------------------------------------------
    def _reload(self) -> None:
        self.folder.setText(self.controller.backup_dir())
        rows = self.controller.list()
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            size_kb = f"{(b.get('file_size_bytes') or 0) / 1024:.0f} KB"
            location = b["file_path"] if b.get("exists") else b["file_path"] + "  (missing)"
            values = [(b.get("created_at") or "")[:16], b.get("backup_type") or "",
                      size_kb, location]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 0:
                    item.setData(Qt.UserRole, b["file_path"])
                    item.setData(Qt.UserRole + 1, bool(b.get("exists")))
                self.table.setItem(r, c, item)

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole), item.data(Qt.UserRole + 1)

    # -- actions ------------------------------------------------------
    def _change_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose backup folder", self.folder.text())
        if not d:
            return
        ok, msg, _ = self.controller.set_backup_dir(d)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Could not set folder", msg)

    def _reset_folder(self) -> None:
        ok, msg, _ = self.controller.set_backup_dir(None)
        if ok:
            self._reload()
        else:
            QMessageBox.warning(self, "Error", msg)

    def _backup_now(self) -> None:
        from datetime import datetime
        suggested = str(Path(self.folder.text()) /
                        f"lubripos_manual_{datetime.now():%Y%m%d_%H%M%S}.db")
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save backup as", suggested, "Backup files (*.db)")
        if not chosen:
            return   # user cancelled
        ok, msg, path = self.controller.create(dest_path=chosen)
        if ok:
            QMessageBox.information(self, "Backed up", f"Backup saved to:\n{path}")
            self._reload()
        else:
            QMessageBox.warning(self, "Backup failed", msg)

    def _restore_selected(self) -> None:
        path, exists = self._selected()
        if path is None:
            QMessageBox.information(self, "Select a backup", "Please select a backup row first.")
            return
        if not exists:
            QMessageBox.warning(self, "Missing file", "That backup file no longer exists.")
            return
        self._do_restore(path)

    def _restore_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a backup database", self.folder.text(),
            "SQLite database (*.db);;All files (*.*)")
        if path:
            self._do_restore(path)

    def _do_restore(self, path: str) -> None:
        confirm = QMessageBox.warning(
            self, "Restore database",
            "This will REPLACE all current data with the selected backup.\n\n"
            "A safety backup of the current data is taken first. The app should "
            "be restarted afterwards.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        ok, msg, safety = self.controller.restore(path)
        if not ok:
            QMessageBox.warning(self, "Restore failed", msg)
            return
        QMessageBox.information(
            self, "Restore complete",
            f"Data restored.\nA safety backup of the previous data was saved to:\n{safety}\n\n"
            "Please close and reopen the application now.",
        )
        self._reload()
