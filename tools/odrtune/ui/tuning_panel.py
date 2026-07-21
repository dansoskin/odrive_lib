"""Tuning tab: adjust the three control loops independently.

Grouped inner-to-outer (the order you normally tune in):
- Current loop: bandwidth + current limit.
- Velocity loop: gain, integrator gain, velocity limit, integrator limit.
- Position loop: gain.

Each field writes to the ODrive as you change it. A step-response test at the
bottom commands a position or velocity step and plots the response so you can
judge the tuning by eye."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QPushButton, QDoubleSpinBox,
                               QComboBox)

from core import device as device_mod
from core.step_response import StepResponse

# group title -> [(key, label, unit suffix, decimals, max value), ...]
_LOOPS = [
    ("Current loop", [
        ("current_control_bandwidth", "Bandwidth", " rad/s", 1, 100000.0),
        ("current_soft_max", "Current soft max", " A", 2, 1000.0),
    ]),
    ("Velocity loop", [
        ("vel_gain", "Gain", " Nm/(turn/s)", 4, 1000.0),
        ("vel_integrator_gain", "Integrator gain", " Nm/turn", 4, 1000.0),
        ("vel_limit", "Vel limit", " turns/s", 3, 100000.0),
        ("vel_integrator_limit", "Integrator limit", "", 3, 100000.0),
    ]),
    ("Position loop", [
        ("pos_gain", "Gain", " 1/s", 3, 100000.0),
    ]),
]

_STEP_CHANNELS = [("Position", "pos"), ("Velocity", "vel")]
_STEP_MODE = {
    "pos": device_mod.CONTROL_MODE_POSITION,
    "vel": device_mod.CONTROL_MODE_VELOCITY,
}


class TuningPanel(QWidget):
    def __init__(self, parent=None, interval_ms: int = 20):
        super().__init__(parent)
        self._dev = None
        self._step = None
        self._t0 = 0.0
        root = QVBoxLayout(self)

        # --- per-loop parameter groups ---
        self._spins = {}
        for title, params in _LOOPS:
            group = QGroupBox(title)
            form = QFormLayout(group)
            for key, label, suffix, decimals, maxv in params:
                spin = QDoubleSpinBox()
                spin.setRange(0.0, maxv)
                spin.setDecimals(decimals)
                spin.setSuffix(suffix)
                spin.valueChanged.connect(lambda v, k=key: self._apply(k, v))
                self._spins[key] = spin
                form.addRow(label + ":", spin)
            root.addWidget(group)

        # --- step-response test ---
        step_group = QGroupBox("Step-response test")
        sv = QVBoxLayout(step_group)
        bar = QHBoxLayout()
        self._chan = QComboBox()
        for label, ch in _STEP_CHANNELS:
            self._chan.addItem(label, ch)
        self._target = QDoubleSpinBox()
        self._target.setRange(-100000.0, 100000.0)
        self._target.setValue(1.0)
        self._btn = QPushButton("Run step")
        bar.addWidget(QLabel("Channel:"))
        bar.addWidget(self._chan)
        bar.addWidget(QLabel("Target:"))
        bar.addWidget(self._target)
        bar.addWidget(self._btn)
        sv.addLayout(bar)
        self._plot = pg.PlotWidget(title="Step response")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._curve = self._plot.plot(pen=pg.mkPen("#4fc3f7", width=2))
        self._target_line = self._plot.plot(
            pen=pg.mkPen("#ff8a65", style=Qt.PenStyle.DashLine))
        sv.addWidget(self._plot, 1)
        root.addWidget(step_group, 1)

        self._btn.clicked.connect(self._start_step)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._record)
        self._set_enabled(False)

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        values = dev.get_tuning()
        for key, spin in self._spins.items():
            spin.blockSignals(True)
            spin.setValue(values[key])
            spin.blockSignals(False)
        self._set_enabled(True)

    # --- helpers ---
    def _set_enabled(self, on: bool):
        for s in self._spins.values():
            s.setEnabled(on)
        for w in (self._chan, self._target, self._btn):
            w.setEnabled(on)

    def _apply(self, key, value):
        if self._dev is None:
            return
        try:
            self._dev.set_tuning(**{key: value})
        except Exception:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            pass

    def _start_step(self):
        if self._dev is None:
            return
        ch = self._chan.currentData()
        try:
            self._dev.set_control_mode(_STEP_MODE[ch])
            self._dev.set_closed_loop(True)
        except Exception:  # noqa: BLE001
            pass
        self._step = StepResponse(self._dev, channel=ch)
        self._step.begin(target=self._target.value())
        self._t0 = time.monotonic()
        self._timer.start()
        QTimer.singleShot(1500, self._timer.stop)  # record ~1.5 s

    def _record(self):
        if self._step is None:
            return
        try:
            self._step.record(t=time.monotonic() - self._t0)
        except Exception:  # noqa: BLE001
            return
        t, y = self._step.data()
        self._curve.setData(t, y)
        if t:
            self._target_line.setData([t[0], t[-1]],
                                      [self._step.target, self._step.target])
