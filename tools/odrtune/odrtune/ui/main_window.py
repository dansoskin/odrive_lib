"""Top-level window: a connect bar plus a tab per feature. Panels are given
the active Device when the connect panel reports a connection.

Panels are added in later tasks; this shell wires the connect signal to a
set_device() fan-out so adding a panel is one line."""
from __future__ import annotations

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget)

from odrtune.ui.connect_panel import ConnectPanel


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("odrtune")
        self._device = None
        self._device_listeners = []

        central = QWidget()
        root = QVBoxLayout(central)
        self._connect = ConnectPanel()
        self._connect.connected.connect(self._set_device)
        self._tabs = QTabWidget()
        root.addWidget(self._connect)
        root.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

    def add_panel(self, title, panel):
        """Add a feature tab. If the panel has set_device(), it is registered
        to receive the active Device on connect."""
        self._tabs.addTab(panel, title)
        if hasattr(panel, "set_device"):
            self._device_listeners.append(panel)
            if self._device is not None:
                panel.set_device(self._device)

    def _set_device(self, dev):
        self._device = dev
        for p in self._device_listeners:
            p.set_device(dev)
