"""Backup config to JSON, restore from JSON, save to NVM, and view/clear errors.
File dialogs are wrapped so tests can drive backup/restore with explicit paths."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QFileDialog)

from odrtune.core.config_io import backup, restore, save_to_nvm


class ConfigPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._backup_btn = QPushButton("Backup to JSON…")
        self._restore_btn = QPushButton("Restore from JSON…")
        self._save_btn = QPushButton("Save to NVM")
        for b in (self._backup_btn, self._restore_btn, self._save_btn):
            b.setEnabled(False)
            bar.addWidget(b)
        layout.addLayout(bar)
        self._status = QLabel("Connect a device.")
        layout.addWidget(self._status)
        layout.addStretch(1)

        self._backup_btn.clicked.connect(self._backup_dialog)
        self._restore_btn.clicked.connect(self._restore_dialog)
        self._save_btn.clicked.connect(self._save)

    def set_device(self, dev):
        self._dev = dev
        for b in (self._backup_btn, self._restore_btn, self._save_btn):
            b.setEnabled(True)
        self._status.setText("Ready.")

    # --- testable core actions (no dialogs) ---
    def backup_to(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup(self._dev), f, indent=2)
        self._status.setText(f"Backed up to {path}")

    def restore_from(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            restore(self._dev, json.load(f))
        self._status.setText(f"Restored from {path}")

    def _save(self):
        if self._dev is None:
            return
        save_to_nvm(self._dev)
        self._status.setText("Saved to NVM.")

    # --- dialog wrappers ---
    def _backup_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Backup config",
                                              "odrive_config.json", "JSON (*.json)")
        if path:
            self.backup_to(path)

    def _restore_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore config",
                                              "", "JSON (*.json)")
        if path:
            self.restore_from(path)
