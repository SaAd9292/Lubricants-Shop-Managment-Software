"""Find & clean up duplicate products.

Groups active products whose names are the same or near-same (spelling/spacing
variants of the same item, created because there was no barcode to catch it) and
lets the admin deactivate the extras. Deactivating (not deleting) keeps each
product's history intact.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..controllers.product_controller import ProductController


class FindDuplicatesDialog(QDialog):
    def __init__(self, controller: ProductController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Find duplicate products")
        self.setMinimumSize(560, 520)
        self._changed = False
        self._boxes: list[tuple[int, QCheckBox]] = []
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)
        title = QLabel("Possible duplicate products")
        title.setStyleSheet("font-size:17px; font-weight:700; color:#0f172a;")
        root.addWidget(title)
        sub = QLabel("Same product entered more than once (spelling/spacing "
                     "variants). Tick the ones to deactivate — the one you keep "
                     "should usually be the row with stock. History is preserved.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#64748b; font-size:12px;")
        root.addWidget(sub)

        self._host = QWidget()
        self._host_lay = QVBoxLayout(self._host)
        self._host_lay.setContentsMargins(0, 0, 0, 0)
        self._host_lay.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Secondary")
        close.clicked.connect(self._done)
        self.apply_btn = QPushButton("Deactivate ticked")
        self.apply_btn.setObjectName("Danger")
        self.apply_btn.clicked.connect(self._apply)
        buttons.addWidget(close)
        buttons.addWidget(self.apply_btn)
        root.addLayout(buttons)

    def _clear_host(self) -> None:
        self._boxes.clear()
        while self._host_lay.count():
            item = self._host_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _reload(self) -> None:
        self._clear_host()
        groups = self.controller.find_duplicate_groups()
        if not groups:
            done = QLabel("No duplicates found. Your catalog looks clean. ✓")
            done.setStyleSheet("color:#16a34a; font-weight:600;")
            self._host_lay.addWidget(done)
            self.apply_btn.setEnabled(False)
            return
        self.apply_btn.setEnabled(True)
        fmt = self.controller.fmt
        for group in groups:
            box = QFrame()
            box.setStyleSheet("QFrame{border:1px solid #e2e8f0; border-radius:8px;}")
            bl = QVBoxLayout(box)
            head = QLabel(f"{len(group)} that look the same:")
            head.setStyleSheet("border:none; color:#334155; font-weight:600;")
            bl.addWidget(head)
            for i, p in enumerate(group):
                row = QHBoxLayout()
                cb = QCheckBox()
                cb.setChecked(i != 0)   # default: keep the first (most stock), tick the rest
                info = QLabel(f"{p['name']}   ·   stock {p['stock_qty']}   ·   {fmt(p['sale_price_minor'])}"
                              + ("   (keep)" if i == 0 else ""))
                info.setStyleSheet("border:none;")
                row.addWidget(cb)
                row.addWidget(info, 1)
                bl.addLayout(row)
                self._boxes.append((p["id"], cb))
            self._host_lay.addWidget(box)
        self._host_lay.addStretch(1)

    def _apply(self) -> None:
        to_remove = [pid for pid, cb in self._boxes if cb.isChecked()]
        if not to_remove:
            QMessageBox.information(self, "Nothing ticked",
                                    "Tick the duplicate rows you want to deactivate.")
            return
        if QMessageBox.question(
                self, "Deactivate products",
                f"Deactivate {len(to_remove)} product(s)? They'll be hidden from the "
                "list and POS but kept in the Inactive folder with their history.") \
                != QMessageBox.Yes:
            return
        failed = 0
        for pid in to_remove:
            ok, _, _ = self.controller.delete(pid)   # soft delete (deactivate)
            if ok:
                self._changed = True
            else:
                failed += 1
        if failed:
            QMessageBox.warning(self, "Some not removed",
                                f"{failed} could not be deactivated.")
        self._reload()

    def _done(self) -> None:
        self.accept() if self._changed else self.reject()
