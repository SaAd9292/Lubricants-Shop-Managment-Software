"""Reusable "choose columns to print" dialog.

Shown before any report is exported/printed. Lets the user tick exactly which
columns to include, with a "Select all" master toggle and saveable named
presets (per report) so a preferred column set can be re-picked instantly.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from ..services.column_presets import ColumnPresetStore


class ColumnSelectDialog(QDialog):
    def __init__(self, parent, columns: list[dict], report_key: str,
                 store: ColumnPresetStore) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose columns to print")
        self.setMinimumWidth(340)
        self.columns = [c for c in columns if c.get("key")]
        self.report_key = report_key
        self.store = store
        self._boxes: dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Tick the columns to include in this printout:"))

        # -- preset row --
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Preset:"))
        self.preset = QComboBox()
        self.preset.addItem("All columns", None)          # built-in
        for name in self.store.presets(report_key):
            self.preset.addItem(name, name)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        prow.addWidget(self.preset, 1)
        save_btn = QPushButton("Save as…")
        save_btn.setObjectName("Secondary")
        save_btn.clicked.connect(self._save_preset)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("Secondary")
        del_btn.clicked.connect(self._delete_preset)
        prow.addWidget(save_btn)
        prow.addWidget(del_btn)
        root.addLayout(prow)

        # -- select all --
        self.all_box = QCheckBox("Select all")
        self.all_box.setChecked(True)
        self.all_box.stateChanged.connect(self._toggle_all)
        root.addWidget(self.all_box)

        # -- one checkbox per column (scrollable for long reports) --
        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(14, 0, 0, 0)
        hl.setSpacing(3)
        for c in self.columns:
            cb = QCheckBox(c.get("label") or c["key"])
            cb.setChecked(True)
            cb.stateChanged.connect(self._sync_all_box)
            self._boxes[c["key"]] = cb
            hl.addWidget(cb)
        hl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Print / Export")
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # -- selection helpers --------------------------------------------
    def selected_keys(self) -> list[str]:
        """Chosen column keys, kept in the report's original column order."""
        return [c["key"] for c in self.columns if self._boxes[c["key"]].isChecked()]

    def _toggle_all(self, _state) -> None:
        on = self.all_box.isChecked()
        for cb in self._boxes.values():
            cb.blockSignals(True)
            cb.setChecked(on)
            cb.blockSignals(False)

    def _sync_all_box(self) -> None:
        all_on = all(cb.isChecked() for cb in self._boxes.values())
        self.all_box.blockSignals(True)
        self.all_box.setChecked(all_on)
        self.all_box.blockSignals(False)

    # -- presets ------------------------------------------------------
    def _apply_preset(self) -> None:
        data = self.preset.currentData()
        if data is None:                       # "All columns"
            for cb in self._boxes.values():
                cb.blockSignals(True)
                cb.setChecked(True)
                cb.blockSignals(False)
        else:
            keys = set(self.store.presets(self.report_key).get(data, []))
            for k, cb in self._boxes.items():
                cb.blockSignals(True)
                cb.setChecked(k in keys)
                cb.blockSignals(False)
        self._sync_all_box()

    def _save_preset(self) -> None:
        keys = self.selected_keys()
        if not keys:
            QMessageBox.information(self, "Nothing selected",
                                    "Tick at least one column first.")
            return
        name, ok = QInputDialog.getText(self, "Save preset",
                                        "Name this column set:")
        name = (name or "").strip()
        if not ok or not name:
            return
        self.store.save(self.report_key, name, keys)
        if self.preset.findData(name) < 0:
            self.preset.addItem(name, name)
        self.preset.setCurrentIndex(self.preset.findData(name))

    def _delete_preset(self) -> None:
        data = self.preset.currentData()
        if data is None:
            QMessageBox.information(self, "Built-in",
                                    "The 'All columns' option can't be deleted.")
            return
        self.store.delete(self.report_key, data)
        self.preset.removeItem(self.preset.currentIndex())

    def _accept(self) -> None:
        if not self.selected_keys():
            QMessageBox.information(self, "No columns",
                                    "Tick at least one column to continue.")
            return
        self.accept()

    # -- convenience --------------------------------------------------
    @staticmethod
    def pick(parent, columns: list[dict], report_key: str,
             store: ColumnPresetStore) -> list[str] | None:
        """Show the dialog; return the chosen column keys, or None if cancelled."""
        dlg = ColumnSelectDialog(parent, columns, report_key, store)
        if dlg.exec() != QDialog.Accepted:
            return None
        return dlg.selected_keys()
