"""Top-level window.

Layout: a connect bar across the top, then a horizontal splitter with the
feature tabs (Control, Calibration, Tuning, Config) on the LEFT and a persistent
plots column on the RIGHT. The plots column (window control + bus-voltage/FET
monitors + position/velocity/Iq/torque graphs) stays visible on every tab.

MainWindow owns the single Sampler and the single QTimer that drives it, so
every graph shares one time base. All graphs are X-linked to a master, and each
tick sets the master's X range to the most recent `window` seconds — a rolling
view that keeps every graph aligned."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QTabWidget, QSplitter)

from core.sampler import Sampler
from ui.connect_panel import ConnectPanel
from ui.plots_column import PlotsColumn
from ui.time_plot import TimePlot
from ui.control_panel import ControlPanel
from ui.calibration_panel import CalibrationPanel
from ui.tuning_panel import TuningPanel
from ui.config_panel import ConfigPanel


class MainWindow(QMainWindow):
    def __init__(self, parent=None, interval_ms: int = 50):
        super().__init__(parent)
        self.setWindowTitle("odrtune")
        self._sampler = None
        self._t0 = 0.0
        self._device_listeners = []

        central = QWidget()
        root = QVBoxLayout(central)

        # Top bar: connect controls + the small bus-voltage / FET-temp monitors.
        top = QHBoxLayout()
        self._connect = ConnectPanel()
        self._connect.connected.connect(self._set_device)
        top.addWidget(self._connect, 0)
        self._bus = TimePlot("Bus voltage (V)", [("bus_voltage", "")], compact=True)
        self._fet = TimePlot("FET temp (°C)", [("fet_temp", "")], compact=True)
        for p in (self._bus, self._fet):
            p.setMinimumWidth(220)
            top.addWidget(p, 1)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)

        # LEFT: feature tabs
        self._tabs = QTabWidget()
        self._control = ControlPanel()
        self._add_listener_tab("Control", self._control)
        self._add_listener_tab("Calibration", CalibrationPanel())
        self._add_listener_tab("Tuning", TuningPanel())
        self._add_listener_tab("Config", ConfigPanel())
        split.addWidget(self._tabs)

        # RIGHT: persistent plots column
        self._plots = PlotsColumn()
        split.addWidget(self._plots)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 720])

        root.addWidget(split, 1)
        self.setCentralWidget(central)

        # Share one time axis across every graph (top monitors + main column):
        # link them all to a master.
        self._live_plots = [self._bus, self._fet] + list(self._plots.plots)
        self._master = self._live_plots[0].plot_item
        for p in self._live_plots[1:]:
            p.plot_item.setXLink(self._master)

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def _add_listener_tab(self, title, panel):
        self._tabs.addTab(panel, title)
        self._device_listeners.append(panel)

    def _set_device(self, dev):
        self._sampler = Sampler(dev, maxlen=6000)
        self._t0 = time.monotonic()
        for p in self._device_listeners:
            p.set_device(dev)
        self._timer.start()

    def _tick(self):
        if self._sampler is None:
            return
        self._control.update_state()   # keep the state readout live even when paused
        if self._plots.paused():
            return                     # freeze graphs/sampling for inspection
        t = time.monotonic() - self._t0
        try:
            self._sampler.sample(t=t)
        except Exception:  # noqa: BLE001 - a USB hiccup shouldn't kill the UI
            return
        self._bus.refresh(self._sampler)
        self._fet.refresh(self._sampler)
        self._plots.refresh(self._sampler)
        window = self._plots.window_seconds()
        self._master.setXRange(max(0.0, t - window), t, padding=0)
