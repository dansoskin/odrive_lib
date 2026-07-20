"""Connect/scan panel. Emits `connected(Device)` when a device is opened.
Connection uses core.device.connect(); failures are shown, not raised."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel)

from odrtune.core import device as device_mod


class ConnectPanel(QWidget):
    connected = Signal(object)  # emits a core.device.Device

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QHBoxLayout(self)
        self._btn = QPushButton("Connect")
        self._status = QLabel("Not connected")
        layout.addWidget(self._btn)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self._btn.clicked.connect(self._on_connect)

    def _on_connect(self):
        try:
            dev = device_mod.connect(timeout=15.0)
        except Exception as exc:  # noqa: BLE001 - surface any USB/find error
            self._status.setText(f"Connect failed: {exc}")
            return
        self._dev = dev
        maj, minr, rev = dev.fw_version()
        self._status.setText(f"Connected {dev.serial_hex()}  fw {maj}.{minr}.{rev}")
        self.connected.emit(dev)
