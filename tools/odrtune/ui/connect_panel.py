"""Connect panel. Emits `connected(Device)` when a device is opened and
`disconnected()` when the user releases it. The button toggles Connect/
Disconnect. Connection uses core.device.connect(); failures are shown, not
raised."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel)

from core import device as device_mod


class ConnectPanel(QWidget):
    connected = Signal(object)  # emits a core.device.Device
    disconnected = Signal()     # emitted when the user disconnects

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QHBoxLayout(self)
        self._btn = QPushButton("Connect")
        self._status = QLabel("Not connected")
        layout.addWidget(self._btn)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self._btn.clicked.connect(self._on_click)

    def _on_click(self):
        if self._dev is None:
            self._connect()
        else:
            self._disconnect()

    def _connect(self):
        try:
            dev = device_mod.connect(timeout=15.0)
        except Exception as exc:  # noqa: BLE001 - surface any USB/find error
            self._status.setText(f"Connect failed: {exc}")
            return
        self._dev = dev
        maj, minr, rev = dev.fw_version()
        self._status.setText(f"Connected {dev.serial_hex()}  fw {maj}.{minr}.{rev}")
        self._btn.setText("Disconnect")
        self.connected.emit(dev)

    def _disconnect(self):
        self._dev = None
        self._status.setText("Not connected")
        self._btn.setText("Connect")
        self.disconnected.emit()
