"""Connect panel. Emits `connected(Device)` when a device is opened and
`disconnected()` when the user releases it. The button toggles Connect/
Disconnect.

A serial chooser lets you point two app instances at two different ODrives:
leave the serial blank to grab the first available device, or pick/type a
serial to connect to a specific one. **Scan** lists visible serials (best-effort,
without claiming them). Connection uses core.device.connect(); failures are
shown, not raised."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel,
                               QComboBox)

from core import device as device_mod


class ConnectPanel(QWidget):
    connected = Signal(object)  # emits a core.device.Device
    disconnected = Signal()     # emitted when the user disconnects

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QHBoxLayout(self)
        self._btn = QPushButton("Connect")
        self._serial = QComboBox()
        self._serial.setEditable(True)
        self._serial.setMinimumWidth(150)
        self._serial.setToolTip(
            "ODrive serial to connect to (hex). Leave blank for the first "
            "available device. Use Scan to list connected serials. Pick "
            "different serials in two app instances to control two ODrives.")
        self._serial.lineEdit().setPlaceholderText("serial (blank = any)")
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.setToolTip("List connected ODrive serials (best-effort).")
        self._status = QLabel("Not connected")
        layout.addWidget(self._btn)
        layout.addWidget(QLabel("Serial:"))
        layout.addWidget(self._serial)
        layout.addWidget(self._scan_btn)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self._btn.clicked.connect(self._on_click)
        self._scan_btn.clicked.connect(self._on_scan)

    def _on_click(self):
        if self._dev is None:
            self._connect()
        else:
            self._disconnect()

    def _on_scan(self):
        self._status.setText("Scanning…")
        try:
            serials = device_mod.list_serials()
        except Exception as exc:  # noqa: BLE001 - never crash on scan
            self._status.setText(f"Scan failed: {exc}")
            return
        current = self._serial.currentText()
        self._serial.clear()
        self._serial.addItems(serials)
        self._serial.setCurrentText(current)
        self._status.setText(
            f"Found {len(serials)}: {', '.join(serials)}" if serials
            else "No devices found (type a serial or leave blank).")

    def _connect(self):
        serial = self._serial.currentText().strip() or None
        try:
            dev = device_mod.connect(serial=serial, timeout=15.0)
        except Exception as exc:  # noqa: BLE001 - surface any USB/find error
            self._status.setText(f"Connect failed: {exc}")
            return
        self._dev = dev
        maj, minr, rev = dev.fw_version()
        self._status.setText(f"Connected {dev.serial_hex()}  fw {maj}.{minr}.{rev}")
        self._btn.setText("Disconnect")
        self._scan_btn.setEnabled(False)
        self._serial.setEnabled(False)
        self.connected.emit(dev)

    def _disconnect(self):
        self._dev = None
        self._status.setText("Not connected")
        self._btn.setText("Connect")
        self._scan_btn.setEnabled(True)
        self._serial.setEnabled(True)
        self.disconnected.emit()
