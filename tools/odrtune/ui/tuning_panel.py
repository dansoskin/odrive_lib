"""Tuning tab: adjust every control-loop parameter independently.

Grouped inner-to-outer (the order you normally tune in): feedback (encoder
bandwidths) -> current loop + its feedforwards -> velocity loop -> position loop
-> gain scheduling -> motor model. Each field writes to the ODrive as you change
it. At the bottom, a back-and-forth sequence drives the motor between two points
so you can watch the repeated response on the (always-visible) right-hand graphs.

Parameters the connected firmware doesn't expose are shown disabled. Changes are
live in RAM; use Config -> Save to NVM to persist."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QPushButton, QDoubleSpinBox,
                               QComboBox, QCheckBox, QScrollArea)

from core import device as device_mod

# float param: (kind, key, label, suffix, decimals, max)  bool: (kind, key, label)
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

_SEQ_CHANNELS = [("Position", "pos"), ("Velocity", "vel")]
_SEQ_MODE = {
    "pos": device_mod.CONTROL_MODE_POSITION,
    "vel": device_mod.CONTROL_MODE_VELOCITY,
}


class TuningPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        self._seq_i = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        # parameter registry: key -> ("f"|"b", widget)
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

        # --- back-and-forth sequence ---
        seq_group = QGroupBox("Back-and-forth sequence")
        sform = QFormLayout(seq_group)
        self._seq_chan = QComboBox()
        for label, ch in _SEQ_CHANNELS:
            self._seq_chan.addItem(label, ch)
        self._seq_a = QDoubleSpinBox()
        self._seq_a.setRange(-100000.0, 100000.0)
        self._seq_a.setValue(0.0)
        self._seq_b = QDoubleSpinBox()
        self._seq_b.setRange(-100000.0, 100000.0)
        self._seq_b.setValue(1.0)
        self._seq_dwell = QDoubleSpinBox()
        self._seq_dwell.setRange(0.05, 3600.0)
        self._seq_dwell.setDecimals(2)
        self._seq_dwell.setValue(1.0)
        self._seq_dwell.setSuffix(" s")
        self._seq_btn = QPushButton("Start")
        self._seq_btn.setCheckable(True)
        sform.addRow("Channel:", self._seq_chan)
        sform.addRow("Point A:", self._seq_a)
        sform.addRow("Point B:", self._seq_b)
        sform.addRow("Dwell:", self._seq_dwell)
        sform.addRow("", self._seq_btn)
        root.addWidget(seq_group)

        note = QLabel("Sequence drives the motor between A and B (watch the "
                      "graphs on the right). Changes apply live in RAM; use "
                      "Config -> Save to NVM to keep them.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        root.addWidget(note)
        root.addStretch(1)

        self._seq_btn.toggled.connect(self._toggle_seq)
        self._seq_timer = QTimer(self)
        self._seq_timer.timeout.connect(self._seq_tick)
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
        for w in (self._seq_chan, self._seq_a, self._seq_b, self._seq_dwell,
                  self._seq_btn):
            w.setEnabled(True)

    # --- helpers ---
    def _set_enabled(self, on: bool):
        for _kind, w in self._widgets.values():
            w.setEnabled(on)
        for w in (self._seq_chan, self._seq_a, self._seq_b, self._seq_dwell,
                  self._seq_btn):
            w.setEnabled(on)

    def _apply(self, key, value):
        if self._dev is None:
            return
        try:
            self._dev.set_tuning(**{key: value})
        except Exception:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            pass

    # --- back-and-forth sequence ---
    def _toggle_seq(self, on: bool):
        if self._dev is None:
            self._seq_btn.setChecked(False)
            return
        if on:
            ch = self._seq_chan.currentData()
            try:
                self._dev.set_control_mode(_SEQ_MODE[ch])
                self._dev.set_closed_loop(True)
            except Exception:  # noqa: BLE001
                pass
            self._seq_i = 0
            self._send_seq()  # go to A immediately
            self._seq_timer.start(max(50, int(self._seq_dwell.value() * 1000)))
            self._seq_btn.setText("Stop")
        else:
            self._seq_timer.stop()
            self._seq_btn.setText("Start")

    def _seq_tick(self):
        self._seq_i ^= 1
        self._send_seq()

    def _send_seq(self):
        if self._dev is None:
            return
        ch = self._seq_chan.currentData()
        value = self._seq_b.value() if self._seq_i else self._seq_a.value()
        try:
            if ch == "pos":
                self._dev.set_input_pos(value)
            else:
                self._dev.set_input_vel(value)
        except Exception:  # noqa: BLE001
            pass
