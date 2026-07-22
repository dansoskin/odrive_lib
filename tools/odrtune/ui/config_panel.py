"""Config tab.

Backup writes a schema-2 JSON snapshot (tuning + motion + control mode +
identity). Restore reads a snapshot, diffs it against the live device, and shows
a selective-apply dialog: non-sensitive changes are checked by default, while
current limits / motor-model parameters land in a separate section that is
unchecked and carries a hardware-damage warning. A separate row offers ODrive's
host-side *native* full-device backup/restore (whole config tree), which needs
the odrive package + a real device and degrades gracefully otherwise.

File dialogs are wrapped so tests can drive everything with explicit paths:
``backup_to(path)`` and ``restore_from(path, interactive=False)`` run headless."""
from __future__ import annotations

import inspect
import json
import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QFileDialog, QDialog, QGroupBox,
                               QCheckBox, QDialogButtonBox)

from core.config_io import (backup, build_restore_plan, apply_restore,
                            save_to_nvm, _fmt_value)

_log = logging.getLogger(__name__)


class RestoreDialog(QDialog):
    """Selective-restore dialog. Lists only *changed* items as checkboxes,
    grouped into a normal section (checked by default) and a sensitive section
    (unchecked, with a red warning). Built without exec_() so tests can tick
    boxes and read :meth:`checked_items` directly."""

    def __init__(self, changed_items, warnings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore config")
        layout = QVBoxLayout(self)
        # (QCheckBox, RestoreItem) for every row, in display order.
        self.entries: list = []

        for w in warnings or []:
            wl = QLabel(w)
            wl.setWordWrap(True)
            wl.setStyleSheet("color: #b26a00;")  # amber, informational
            layout.addWidget(wl)

        normal = [it for it in changed_items if not it.sensitive]
        sensitive = [it for it in changed_items if it.sensitive]

        if normal:
            grp = QGroupBox("Changes")
            gl = QVBoxLayout(grp)
            for it in normal:
                cb = QCheckBox(self._label(it))
                cb.setChecked(True)
                gl.addWidget(cb)
                self.entries.append((cb, it))
            layout.addWidget(grp)

        if sensitive:
            grp = QGroupBox("Sensitive (verify before applying)")
            gl = QVBoxLayout(grp)
            warn = QLabel("Current limits / motor model — wrong values can "
                          "damage hardware.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: red; font-weight: bold;")
            gl.addWidget(warn)
            for it in sensitive:
                cb = QCheckBox(self._label(it))
                cb.setChecked(False)  # opt-in
                gl.addWidget(cb)
                self.entries.append((cb, it))
            layout.addWidget(grp)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _label(it) -> str:
        return (f"{it.key} [{it.section}]: "
                f"{_fmt_value(it.current)} → {_fmt_value(it.target)}")

    def checked_items(self) -> list:
        return [it for cb, it in self.entries if cb.isChecked()]


class ConfigPanel(QWidget):
    # Emitted after a successful reboot request: the USB link drops, so the
    # window tears sampling down and releases the device exactly as a disconnect.
    rebooted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self._backup_btn = QPushButton("Backup to JSON…")
        self._restore_btn = QPushButton("Restore from JSON…")
        self._save_btn = QPushButton("Save to NVM")
        for b in (self._backup_btn, self._restore_btn, self._save_btn):
            bar.addWidget(b)
        layout.addLayout(bar)

        native = QHBoxLayout()
        self._native_backup_btn = QPushButton("Full backup (native)…")
        self._native_restore_btn = QPushButton("Full restore (native)…")
        for b in (self._native_backup_btn, self._native_restore_btn):
            bar_tip = ("Whole-device config via the ODrive host package "
                       "(needs the odrive package + a real device).")
            b.setToolTip(bar_tip)
            native.addWidget(b)
        self._reboot_btn = QPushButton("Reboot device")
        self._reboot_btn.setToolTip(
            "Reboot the ODrive. The USB connection drops — you'll need to "
            "reconnect.")
        native.addWidget(self._reboot_btn)
        native.addStretch(1)
        layout.addLayout(native)

        self._all_btns = (self._backup_btn, self._restore_btn, self._save_btn,
                          self._native_backup_btn, self._native_restore_btn,
                          self._reboot_btn)
        for b in self._all_btns:
            b.setEnabled(False)

        self._status = QLabel("Connect a device.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch(1)

        self._backup_btn.clicked.connect(self._backup_dialog)
        self._restore_btn.clicked.connect(self._restore_dialog)
        self._save_btn.clicked.connect(self._save)
        self._native_backup_btn.clicked.connect(self._native_backup_dialog)
        self._native_restore_btn.clicked.connect(self._native_restore_dialog)
        self._reboot_btn.clicked.connect(self._reboot)

    def set_device(self, dev):
        self._dev = dev
        if dev is None:                    # disconnected
            for b in self._all_btns:
                b.setEnabled(False)
            self._status.setText("Connect a device.")
            self._status.setStyleSheet("")
            return
        for b in self._all_btns:
            b.setEnabled(True)
        self._status.setText("Ready.")
        self._status.setStyleSheet("")

    # --- testable core actions (no dialogs) ---
    def backup_to(self, path: str):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(backup(self._dev), f, indent=2)
        except Exception as exc:  # noqa: BLE001 - bad path shouldn't crash the UI
            self._status.setText(f"Backup failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        self._status.setText(f"Backed up to {path}")
        self._status.setStyleSheet("")

    def restore_from(self, path: str, interactive: bool = True):
        """Read a snapshot and restore from it.

        Interactive: show the selective dialog and apply the checked items.
        Headless (``interactive=False``): apply all changed *non-sensitive*
        items without a dialog (sensitive params are left untouched)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        except Exception as exc:  # noqa: BLE001 - bad path shouldn't crash the UI
            self._status.setText(f"Restore failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        try:
            items, warnings = build_restore_plan(self._dev, snapshot)
        except Exception as exc:  # noqa: BLE001
            self._status.setText(f"Restore failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        changed = [it for it in items if it.changed]
        if not changed:
            note = "  (" + "; ".join(warnings) + ")" if warnings else ""
            self._status.setText("Nothing to restore — device already matches."
                                 + note)
            self._status.setStyleSheet("")
            return
        if not interactive:
            self._apply_items([it for it in changed if not it.sensitive])
            return
        dlg = RestoreDialog(changed, warnings, self)
        if dlg.exec():
            self._apply_items(dlg.checked_items())

    def _apply_items(self, items):
        if not items:
            self._status.setText("Restore: nothing selected.")
            self._status.setStyleSheet("")
            return
        try:
            results = apply_restore(self._dev, items)
        except Exception as exc:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            self._status.setText(f"Restore failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        n_ok = sum(1 for ok, _ in results.values() if ok)
        fails = [f"{k}: {msg}" for k, (ok, msg) in results.items() if not ok]
        if fails:
            self._status.setText(
                f"{n_ok} applied, {len(fails)} failed: " + "; ".join(fails))
            self._status.setStyleSheet("color: red;")
        else:
            self._status.setText(f"{n_ok} applied.")
            self._status.setStyleSheet("")

    def _save(self):
        if self._dev is None:
            return
        # fw 0.6.x refuses to save unless the axis is IDLE, and saving reboots
        # the device. Gate on IDLE (clear guidance) and tear down afterwards.
        if not self._dev.is_idle():
            self._status.setText(
                "Save to NVM needs the axis in IDLE — Disarm (top bar) first.")
            self._status.setStyleSheet("color: red;")
            return
        self._status.setText("Saving to NVM… device will reboot & disconnect.")
        self._status.setStyleSheet("")
        try:
            save_to_nvm(self._dev)      # writes flash, then the ODrive reboots
        except Exception as exc:  # noqa: BLE001
            self._status.setText(f"Save failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        # The device rebooted out from under us — release + reset like a reboot.
        self.rebooted.emit()

    def _reboot(self):
        if self._dev is None:
            return
        self._status.setText("Rebooting… (device will disconnect)")
        self._status.setStyleSheet("")
        try:
            self._dev.reboot()
        except Exception as exc:  # noqa: BLE001 - USB drops on reboot
            self._status.setText(f"Reboot failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        self.rebooted.emit()

    # --- native (host-side) full-device backup/restore ---
    def native_backup_to(self, path: str):
        self._native_op("backup", path)

    def native_restore_from(self, path: str):
        self._native_op("restore", path)

    def _native_op(self, op: str, path: str):
        """Call the ODrive host package's whole-device backup/restore. The
        odrive package + a real device are required; anything missing/failing
        is reported in the status label instead of raising."""
        if self._dev is None:
            return
        try:
            from odrive.configuration import backup_config, restore_config
            fn = backup_config if op == "backup" else restore_config
            logger = logging.getLogger("odrtune.native")
            call_args = [self._dev.raw, path]
            try:
                nparams = len(inspect.signature(fn).parameters)
            except (TypeError, ValueError):
                nparams = 2
            if nparams >= 3:              # pass a logger when it accepts one
                call_args.append(logger)
            fn(*call_args)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully in dev
            self._status.setText(f"Native {op} unavailable/failed: {exc}")
            self._status.setStyleSheet("color: red;")
            return
        self._status.setText(f"Native {op} complete: {path}")
        self._status.setStyleSheet("")

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

    def _native_backup_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Full device backup", "odrive_full_config.json",
            "JSON (*.json)")
        if path:
            self.native_backup_to(path)

    def _native_restore_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Full device restore", "", "JSON (*.json)")
        if path:
            self.native_restore_from(path)
