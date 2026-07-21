"""Tuning tab: adjust every control-loop parameter independently.

Grouped inner-to-outer (the order you normally tune in): feedback (encoder
bandwidths) -> current loop + its feedforwards -> velocity loop -> position loop
-> gain scheduling -> motor model. Each field writes to the ODrive as you change
it. A step-response test at the bottom commands a position or velocity step and
plots the response.

Parameters the connected firmware doesn't expose are shown disabled. Changes are
live in RAM; use Config -> Save to NVM to persist."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QPushButton, QDoubleSpinBox,
                               QComboBox, QCheckBox, QScrollArea)

from core import device as device_mod
from core.step_response import StepResponse

# float param: (key, label, suffix, decimals, max)   bool param: (key, label)
_F = "f"
_B = "b"


def _f(key, label, suffix, decimals, maxv):
    return (_F, key, label, suffix, decimals, maxv)


def _b(key, label):
    return (_B, key, label)


# group title -> [param spec, ...]
_GROUPS = [
    ("Feedback (encoder)", [
        _f("encoder_bandwidth", "Encoder bandwidth", " Hz", 1, 100000.0),
        _f("commutation_encoder_bandwidth", "Commutation enc bandwidth", " Hz", 1, 100000.0),
    ]),
    ("Current loop", [
        _f("current_control_bandwidth", "Bandwidth", " rad/s", 1, 100000.0),
        _f("current_soft_max", "Current soft max", " A", 2, 1000.0),
        _f("current_hard_max", "Current hard max", " A", 2, 1000.0),
        _f("current_slew_rate_limit", "Current slew limit", " A/s", 1, 1e9),
    ]),
    ("Current feedforward (high-speed tracking)", [
        _b("wL_FF_enable", "Cross-coupling (wL) FF"),
        _b("bEMF_FF_enable", "Back-EMF FF"),
        _b("dI_dt_FF_enable", "dI/dt FF"),
    ]),
    ("Velocity loop", [
        _f("vel_gain", "Gain", " Nm/(turn/s)", 4, 1000.0),
        _f("vel_integrator_gain", "Integrator gain", " Nm/turn", 4, 1000.0),
        _f("vel_integrator_limit", "Integrator limit", "", 2, 100000.0),
        _f("vel_integrator_decay_gain", "Integrator decay", "", 5, 1000.0),
        _f("vel_limit", "Vel limit", " turns/s", 3, 100000.0),
    ]),
    ("Position loop", [
        _f("pos_gain", "Gain", " 1/s", 3, 100000.0),
        _f("inertia", "Inertia (accel FF)", "", 5, 100000.0),
    ]),
    ("Gain scheduling", [
        _b("enable_gain_scheduling", "Enable gain scheduling"),
        _f("gain_scheduling_width", "Width", " turns", 4, 100000.0),
        _f("gain_scheduling_min_ratio", "Min ratio", "", 3, 1.0),
    ]),
    ("Motor model (normally from calibration)", [
        _f("torque_constant", "Torque constant", " Nm/A", 5, 100.0),
        _f("phase_resistance", "Phase resistance", " ohm", 5, 100.0),
        _f("phase_inductance", "Phase inductance", " H", 8, 10.0),
        _f("ff_pm_flux_linkage", "PM flux linkage", " Wb", 8, 100.0),
        _f("motor_model_l_d", "Model L_d", " H", 8, 10.0),
        _f("motor_model_l_q", "Model L_q", " H", 8, 10.0),
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        # widget registry: key -> ("f"|"b", widget)
        self._widgets = {}
        for title, params in _GROUPS:
            group = QGroupBox(title)
            form = QFormLayout(group)
            if title.startswith("Motor model"):
                note = QLabel("Edit only if you know the values.")
                note.setStyleSheet("color: gray;")
                form.addRow(note)
            for spec in params:
                if spec[0] == _F:
                    _, key, label, suffix, decimals, maxv = spec
                    w = QDoubleSpinBox()
                    w.setRange(0.0, maxv)
                    w.setDecimals(decimals)
                    w.setSuffix(suffix)
                    w.valueChanged.connect(lambda v, k=key: self._apply(k, v))
                    form.addRow(label + ":", w)
                    self._widgets[key] = (_F, w)
                else:
                    _, key, label = spec
                    w = QCheckBox(label)
                    w.toggled.connect(lambda v, k=key: self._apply(k, bool(v)))
                    form.addRow("", w)
                    self._widgets[key] = (_B, w)
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
        self._plot.setMinimumHeight(180)
        self._curve = self._plot.plot(pen=pg.mkPen("#4fc3f7", width=2))
        self._target_line = self._plot.plot(
            pen=pg.mkPen("#ff8a65", style=Qt.PenStyle.DashLine))
        sv.addWidget(self._plot, 1)
        root.addWidget(step_group)

        note = QLabel("Changes apply live (in RAM). Use Config -> Save to NVM "
                      "to keep them across power cycles.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        root.addWidget(note)
        root.addStretch(1)

        self._btn.clicked.connect(self._start_step)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._record)
        self._set_enabled(False)

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        values = dev.get_tuning()
        for key, (kind, w) in self._widgets.items():
            present = key in values
            w.setEnabled(present)          # grey out params this fw lacks
            if not present:
                continue
            w.blockSignals(True)
            if kind == _B:
                w.setChecked(bool(values[key]))
            else:
                w.setValue(values[key])
            w.blockSignals(False)
        for w in (self._chan, self._target, self._btn):
            w.setEnabled(True)

    # --- helpers ---
    def _set_enabled(self, on: bool):
        for _kind, w in self._widgets.values():
            w.setEnabled(on)
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
