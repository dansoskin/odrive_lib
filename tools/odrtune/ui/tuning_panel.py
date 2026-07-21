"""Gain tuning: sliders for pos_gain, vel_gain, vel_integrator_gain (live-apply
to the device), plus a step-response test plotted with pyqtgraph.

Sliders are integer Qt widgets scaled to floats via a per-gain factor."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSlider,
                               QLabel, QPushButton, QDoubleSpinBox)

from core.step_response import StepResponse

# (name, max_value, resolution) -> slider int = value / resolution
_GAINS = [
    ("pos_gain", 200.0, 0.1),
    ("vel_gain", 5.0, 0.001),
    ("vel_integrator_gain", 10.0, 0.001),
]


class _GainRow(QWidget):
    def __init__(self, name, maxv, res, on_change):
        super().__init__()
        self._name = name
        self._res = res
        self._on_change = on_change
        row = QHBoxLayout(self)
        self._label = QLabel(name)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(int(maxv / res))
        self._value = QLabel("0.000")
        row.addWidget(self._label)
        row.addWidget(self._slider, 1)
        row.addWidget(self._value)
        self._slider.valueChanged.connect(self._changed)

    def set_value(self, v: float):
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(v / self._res)))
        self._value.setText(f"{v:.3f}")
        self._slider.blockSignals(False)

    def _changed(self, raw):
        v = raw * self._res
        self._value.setText(f"{v:.3f}")
        self._on_change(self._name, v)


class TuningPanel(QWidget):
    def __init__(self, parent=None, interval_ms: int = 20):
        super().__init__(parent)
        self._dev = None
        self._step = None
        self._t0 = 0.0
        layout = QVBoxLayout(self)

        self._rows = {}
        for name, maxv, res in _GAINS:
            row = _GainRow(name, maxv, res, self._apply_gain)
            self._rows[name] = row
            layout.addWidget(row)

        step_bar = QHBoxLayout()
        self._target = QDoubleSpinBox()
        self._target.setRange(-100.0, 100.0)
        self._target.setValue(1.0)
        self._btn = QPushButton("Step (position)")
        self._btn.setEnabled(False)
        step_bar.addWidget(QLabel("Target:"))
        step_bar.addWidget(self._target)
        step_bar.addWidget(self._btn)
        layout.addLayout(step_bar)

        self._plot = pg.PlotWidget(title="Step response")
        self._plot.showGrid(x=True, y=True)
        self._curve = self._plot.plot(pen=pg.mkPen(width=2))
        self._target_line = self._plot.plot(pen=pg.mkPen(style=Qt.DashLine))
        layout.addWidget(self._plot, 1)

        self._btn.clicked.connect(self._start_step)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._record)

    def set_device(self, dev):
        self._dev = dev
        self._btn.setEnabled(True)
        gains = dev.get_gains()
        for name, row in self._rows.items():
            row.set_value(gains[name])

    def _apply_gain(self, name, value):
        if self._dev is not None:
            self._dev.set_gains(**{name: value})

    def _start_step(self):
        if self._dev is None:
            return
        self._dev.set_closed_loop(True)
        self._step = StepResponse(self._dev, channel="pos")
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
