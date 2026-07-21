"""Tuning tab: adjust every control-loop parameter independently.

Grouped inner-to-outer (the order you normally tune in): feedback (encoder
bandwidths) -> current loop + its feedforwards -> velocity loop -> position loop
-> gain scheduling -> motor model. Each field writes to the ODrive as you change
it. At the bottom, a back-and-forth sequence drives the motor between two points
so you can watch the repeated response on the (always-visible) right-hand graphs.

Parameters the connected firmware doesn't expose are shown disabled. Changes are
live in RAM; use Config -> Save to NVM to persist."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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

# hover hints: what each parameter does and how it affects the loop
_TIPS = {
    "encoder_bandwidth":
        "Bandwidth (Hz) of the position/velocity estimator feeding every loop. "
        "Higher = less lag / snappier feedback but noisier, and it caps how high "
        "the loop gains can go. Lower for coarse feedback (hall sensors ~10–100 Hz).",
    "commutation_encoder_bandwidth":
        "Estimator bandwidth (Hz) for the commutation encoder (motor commutation). "
        "Higher = cleaner commutation at speed; lower if the signal is noisy.",
    "current_control_bandwidth":
        "Bandwidth (rad/s) of the inner current/torque PI loop. Actual Iq gains are "
        "derived from this plus phase R/L. Higher = faster torque response but more "
        "noise; limited by the control sample rate. ~1000 is typical.",
    "current_soft_max":
        "Continuous current limit (A) — your torque ceiling in normal operation. "
        "Raise toward the motor's safe continuous current for more torque.",
    "current_hard_max":
        "Absolute over-current cutoff (A, hardware protection). Keep above the soft "
        "max and within the motor/board rating.",
    "current_slew_rate_limit":
        "Max rate of change of the current command (A/s). Raise for snappier torque "
        "steps; lower to soften current transients.",
    "wL_FF_enable":
        "Cross-coupling (ωL) feedforward: compensates d/q coupling that grows with "
        "speed → much better current tracking at high RPM. Needs valid L_d / L_q.",
    "bEMF_FF_enable":
        "Back-EMF feedforward: cancels the motor's back-EMF so the current loop stays "
        "accurate at high speed. Needs a valid PM flux linkage.",
    "dI_dt_FF_enable":
        "di/dt feedforward: anticipates the voltage needed for fast current changes → "
        "better transient current tracking.",
    "vel_gain":
        "Velocity-loop proportional gain (Nm per turn/s): velocity error → torque. The "
        "main stiffness knob for speed. Raise until you hear whine / see vibration, "
        "then back off ~2×.",
    "vel_integrator_gain":
        "Velocity-loop integral gain (Nm per turn): removes steady-state velocity error "
        "and holds against load. Too high → low-frequency hunting/overshoot. Rule of "
        "thumb ≈ 0.5 × bandwidth(Hz) × vel_gain.",
    "vel_integrator_limit":
        "Anti-windup clamp on the velocity integrator's output. Bounds windup during "
        "saturation; often tied to the current limit.",
    "vel_integrator_decay_gain":
        "Leaky-integrator decay: bleeds the integrator toward zero when error is small, "
        "reducing post-move overshoot while still allowing a high integrator gain. "
        "0 disables.",
    "vel_limit":
        "Maximum commanded speed (turns/s). Also clamps the velocity the position loop "
        "may request. Set to your true max operating speed.",
    "pos_gain":
        "Position-loop proportional gain (1/s): position error → velocity setpoint "
        "(position loop is P-only). Tune after the velocity loop; raise until "
        "overshoot/ringing, then back off.",
    "inertia":
        "Acceleration feedforward: torque_ff = inertia × commanded accel. Set to the "
        "reflected system inertia to improve tracking during fast accelerations. "
        "0 disables.",
    "enable_gain_scheduling":
        "Automatically reduces pos/vel gains as the position error shrinks near the "
        "target — lets you run higher gains for aggressive moves without buzzing at "
        "standstill.",
    "gain_scheduling_width":
        "Position-error window (turns) over which the gains ramp down to the minimum "
        "ratio. Wider = gentler reduction over a larger range.",
    "gain_scheduling_min_ratio":
        "Minimum fraction (0–1) the gains scale to at zero error. Lower = quieter at "
        "rest but softer holding stiffness.",
    "torque_constant":
        "Motor torque constant (Nm/A ≈ 8.27 / KV). Scales current↔torque and the torque "
        "estimate. Must be correct or torque-mode commands and feedforwards are wrong.",
    "phase_resistance":
        "Measured motor phase resistance (Ω); the current-loop gains derive from it. "
        "Normally set by calibration — don't guess.",
    "phase_inductance":
        "Measured motor phase inductance (H); sets current-loop gains with resistance. "
        "Normally from calibration.",
    "ff_pm_flux_linkage":
        "Permanent-magnet flux linkage (Wb) used by the back-EMF feedforward. Must be "
        "valid for bEMF FF to work.",
    "motor_model_l_d":
        "d-axis inductance (H) for the cross-coupling feedforward (accounts for "
        "saliency). From calibration/identification.",
    "motor_model_l_q":
        "q-axis inductance (H) for the cross-coupling feedforward. From "
        "calibration/identification.",
}

_GUIDE_HTML = (
    "<b>Tuning guide</b>"
    "<p><i>ODrive guidelines:</i></p>"
    "<ul>"
    "<li>Calibrate motor &amp; encoder first — a valid motor model (R, L, flux) is required.</li>"
    "<li>Tune inner → outer: encoder bandwidth → current → velocity → position.</li>"
    "<li><b>Velocity:</b> raise <tt>vel_gain</tt> until the motor whines/vibrates, then cut ~2×. "
    "Start <tt>vel_integrator_gain</tt> ≈ 0.5 × bandwidth(Hz) × <tt>vel_gain</tt> (or simply = vel_gain).</li>"
    "<li><b>Position:</b> raise <tt>pos_gain</tt> until you see overshoot/oscillation, then back off.</li>"
    "<li>For low-resolution feedback (hall sensors) keep <tt>encoder_bandwidth</tt> low (~10–100 Hz).</li>"
    "</ul>"
    "<p><i>Tips:</i></p>"
    "<ul>"
    "<li>Use the <b>Back-and-forth sequence</b> below + the graph <b>Pause</b> to capture and inspect a step.</li>"
    "<li>Watch <b>actual</b> vs <b>ideal</b> on the graphs: <i>ideal</i> is what the controller commands each "
    "instant; <i>actual</i> should track it with minimal lag/overshoot. Lagging → raise gains; ringing → lower.</li>"
    "<li>For high-speed / high-dynamics rigs, push <tt>current_control_bandwidth</tt> up and enable the FF terms.</li>"
    "<li>Buzzing at standstill? Lower <tt>encoder_bandwidth</tt> or enable gain scheduling before dropping gains.</li>"
    "<li>Changes are live in RAM — <b>Config → Save to NVM</b> once you're happy.</li>"
    "</ul>"
)

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

        # --- tuning guide (collapsible) ---
        guide = QGroupBox("Tuning guide")
        guide.setCheckable(True)
        guide.setChecked(False)          # collapsed by default to save space
        gl = QVBoxLayout(guide)
        self._guide_body = QLabel(_GUIDE_HTML)
        self._guide_body.setWordWrap(True)
        self._guide_body.setTextFormat(Qt.RichText)
        self._guide_body.setVisible(False)
        gl.addWidget(self._guide_body)
        guide.toggled.connect(self._guide_body.setVisible)
        root.addWidget(guide)

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
                    w.setToolTip(_TIPS.get(key, ""))
                    w.valueChanged.connect(lambda v, k=key: self._apply(k, v))
                    lbl = QLabel(label + ":")
                    lbl.setToolTip(_TIPS.get(key, ""))
                    form.addRow(lbl, w)
                    self._widgets[key] = (_F, w)
                else:
                    _, key, label = spec
                    w = QCheckBox(label)
                    w.setToolTip(_TIPS.get(key, ""))
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
