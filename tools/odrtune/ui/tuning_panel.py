"""Tuning tab: adjust the key control-loop parameters independently.

Grouped inner-to-outer (the order you normally tune in): feedback (encoder
bandwidths) -> current loop + its feedforwards -> velocity loop -> position loop
-> gain scheduling -> motor model. Edits are debounced then written to the
ODrive and verified by read-back (✓ or an error in the status line). At the
bottom, a back-and-forth sequence drives the motor between two points so you can
watch the repeated response on the (always-visible) right-hand graphs.

Parameters the connected firmware doesn't expose are shown disabled. Changes are
live in RAM; use Config -> Save to NVM to persist."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QPushButton, QToolButton,
                               QDoubleSpinBox, QComboBox, QCheckBox, QScrollArea)

from core import device as device_mod

_F = "f"
_B = "b"


@dataclass
class FloatSpec:
    key: str
    label: str
    suffix: str
    decimals: int
    maxv: float
    minv: float = 0.0
    allow_inf: bool = False
    requires_idle: bool = False
    kind: str = _F


@dataclass
class BoolSpec:
    key: str
    label: str
    kind: str = _B


def _f(key, label, suffix, decimals, maxv, *, minv=0.0,
       allow_inf=False, requires_idle=False):
    return FloatSpec(key, label, suffix, decimals, maxv, minv,
                     allow_inf, requires_idle)


def _b(key, label):
    return BoolSpec(key, label)


def _is_inf(value) -> bool:
    try:
        return math.isinf(float(value))
    except (TypeError, ValueError):
        return False


# group title -> [param spec, ...]
_GROUPS = [
    ("Feedback (encoder)", [
        _f("encoder_bandwidth", "Encoder bandwidth", " 1/s", 1, 100000.0),
        _f("commutation_encoder_bandwidth", "Commutation enc bandwidth", " 1/s", 1, 100000.0),
    ]),
    ("Current loop", [
        _f("current_control_bandwidth", "Bandwidth", " 1/s", 1, 100000.0),
        _f("current_soft_max", "Current soft max", " A", 2, 1000.0),
        _f("current_hard_max", "Current hard max", " A", 2, 1000.0, requires_idle=True),
        _f("current_slew_rate_limit", "Current slew limit", " A/s", 3, 1e9, minv=0.001),
    ]),
    ("Current feedforward (high-speed tracking)", [
        _b("wL_FF_enable", "Cross-coupling (wL) FF"),
        _b("bEMF_FF_enable", "Back-EMF FF"),
        _b("dI_dt_FF_enable", "dI/dt FF"),
    ]),
    ("Velocity loop", [
        _f("vel_gain", "Gain", " Nm/(turn/s)", 4, 1000.0),
        _f("vel_integrator_gain", "Integrator gain", " Nm/turn", 4, 1000.0),
        _f("vel_integrator_limit", "Integrator limit", " Nm", 2, 100000.0, allow_inf=True),
        _f("vel_integrator_decay_gain", "Integrator decay", "", 5, 1.0, minv=0.0),
        _f("vel_limit", "Vel limit", " turns/s", 3, 100000.0, allow_inf=True),
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
        _f("phase_resistance", "Phase resistance", " ohm", 5, 100.0, requires_idle=True),
        _f("phase_inductance", "Phase inductance", " H", 8, 10.0, requires_idle=True),
        _f("ff_pm_flux_linkage", "PM flux linkage", " Wb", 8, 100.0),
        _f("motor_model_l_d", "Model L_d", " H", 8, 10.0),
        _f("motor_model_l_q", "Model L_q", " H", 8, 10.0),
    ]),
]

# hover hints: what each parameter does and how it affects the loop
_TIPS = {
    "encoder_bandwidth":
        "Bandwidth [1/s] of the load-encoder position/velocity estimator feeding "
        "the loops. Higher = less lag but passes more quantization/measurement "
        "noise, capping usable loop gains. When the same encoder serves load and "
        "commutation it normally also sets the commutation estimator bandwidth. "
        "For coarse feedback (hall sensors) use low values (~10-100).",
    "commutation_encoder_bandwidth":
        "Bandwidth [1/s] of the separate commutation-encoder estimator. Higher "
        "reduces lag but increases noise sensitivity. Ignored when the load and "
        "commutation encoders are the same (or when this value is NaN).",
    "current_control_bandwidth":
        "Requested -3 dB bandwidth [1/s] of the critically damped D/Q current PI "
        "loops; ODrive derives the PI gains from phase resistance and inductance. "
        "Higher = faster torque response but less noise/stability margin. Increase "
        "only after verifying R/L calibration and the current response, gradually.",
    "current_soft_max":
        "Maximum commanded motor current [A] - clamps available torque. This is not "
        "automatically the motor's thermally safe continuous current, and the "
        "effective limit can be lower due to inverter, temperature, voltage or "
        "measurement constraints.",
    "current_hard_max":
        "Maximum measured motor current [A] before a CURRENT_LIMIT_VIOLATION error. "
        "Changing it may reconfigure low-level current measurement when the axis "
        "next enters IDLE and can delay re-arming. Requires IDLE + Apply.",
    "current_slew_rate_limit":
        "Maximum current-setpoint slew [A/s]. Must be strictly positive. Lower "
        "values soften torque transitions but can limit outer-loop response.",
    "wL_FF_enable":
        "Feedforward of the resistive (R) and rotational (wL) voltage terms - "
        "improves current tracking at speed. Uses phase_inductance unless valid "
        "separate L_d/L_q are enabled (motor_model_l_dq_valid).",
    "bEMF_FF_enable":
        "Back-EMF feedforward - keeps the current loop accurate at high speed. "
        "ODrive derives flux linkage from torque constant and pole pairs by "
        "default; an explicit ff_pm_flux_linkage is used only when "
        "ff_pm_flux_linkage_valid is true.",
    "dI_dt_FF_enable":
        "Adds the voltage predicted from the requested current slew and motor "
        "inductance. Improves rapid current transitions; accuracy depends on the "
        "inductance model.",
    "vel_gain":
        "Velocity-loop proportional gain (Nm per turn/s): velocity error → torque. The "
        "main stiffness knob for speed. Raise until you hear whine / see vibration, "
        "then back off ~2×.",
    "vel_integrator_gain":
        "Velocity integral gain [Nm/turn]. Removes steady-state velocity error under "
        "friction or constant load. Too high causes slow oscillation and overshoot. "
        "Start around the same numeric value as vel_gain, then tune experimentally.",
    "vel_integrator_limit":
        "Maximum torque contribution from the velocity integrator [Nm]. Infinity "
        "disables the clamp. Set relative to available motor torque and expected "
        "sustained load.",
    "vel_integrator_decay_gain":
        "When the velocity controller output is saturated, the accumulated integrator "
        "torque is multiplied by this value every control tick (anti-windup). Range 0–1: "
        "1.0 disables the decay; smaller values unwind the integrator faster while "
        "saturated.",
    "vel_limit":
        "Velocity limit [turn/s]. Infinity disables the numeric limit. Actual "
        "enforcement depends on enable_vel_limit and, in torque mode, "
        "enable_torque_mode_vel_limit.",
    "pos_gain":
        "Position-loop proportional gain (1/s): position error → velocity setpoint "
        "(position loop is P-only). Tune after the velocity loop; raise until "
        "overshoot/ringing, then back off.",
    "inertia":
        "Estimated reflected inertia [Nm/(turn/s^2)] used for acceleration torque "
        "feedforward in filtered, ramped and trajectory modes. 0 disables. Update it "
        "when the reflected load inertia changes substantially.",
    "enable_gain_scheduling":
        "Experimental anti-hunt feature that scales down pos_gain, vel_gain and "
        "vel_integrator_gain near the setpoint. Operates on position error in "
        "position mode and velocity error in velocity mode.",
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
        "Normally set by calibration — don't guess. Requires IDLE + Apply.",
    "phase_inductance":
        "Measured motor phase inductance (H); sets current-loop gains with resistance. "
        "Normally from calibration. Requires IDLE + Apply.",
    "ff_pm_flux_linkage":
        "Optional explicit permanent-magnet flux linkage [Wb]. ODrive normally derives "
        "this from torque constant and pole pairs; this value overrides the derived one "
        "only when ff_pm_flux_linkage_valid is true.",
    "motor_model_l_d":
        "Optional d-axis inductance [H] for feedforward and field weakening. Used only "
        "when motor_model_l_dq_valid is true; otherwise phase_inductance is used. Does "
        "not change the current PI gains.",
    "motor_model_l_q":
        "Optional q-axis inductance [H] for feedforward and field weakening. Used only "
        "when motor_model_l_dq_valid is true; otherwise phase_inductance is used. Does "
        "not change the current PI gains.",
}

_GUIDE_HTML = (
    "<b>Tuning guide</b>"
    "<p><i>ODrive tuning flow:</i></p>"
    "<ol>"
    "<li>Calibrate motor+encoder first (valid R/L/flux).</li>"
    "<li>Verify no current/torque/bus/velocity/modulation limit is active.</li>"
    "<li>Tune in Passthrough input mode.</li>"
    "<li>Set <tt>vel_integrator_gain</tt> to 0.</li>"
    "<li>Raise <tt>vel_gain</tt> ~30% per step until vibration/whine, then halve it.</li>"
    "<li>In position mode raise <tt>pos_gain</tt> until overshoot appears, then back off.</li>"
    "<li>Raise <tt>vel_integrator_gain</tt> until the response gets underdamped, then halve it.</li>"
    "<li>Only then re-enable filters, ramps, trajectories and feedforward.</li>"
    "</ol>"
    "<p><i>Diagnosis tips:</i></p>"
    "<ul>"
    "<li>If the response lags, FIRST check that no ramp, filter, current, torque, "
    "bus, velocity or modulation limit is active - then raise the relevant gain.</li>"
    "<li>Buzzing: identify the source first (too-high gains, encoder quantization "
    "noise, mechanical resonance, commutation error, current-loop instability) - "
    "lower encoder bandwidth only if estimator noise is the cause.</li>"
    "<li>Raise <tt>current_control_bandwidth</tt> gradually and only after verifying "
    "phase R/L and the current response.</li>"
    "<li>Watch actual vs ideal on the graphs: ideal is what the controller commands "
    "each instant; actual should track it with minimal lag and no ringing.</li>"
    "<li>Use the back-and-forth sequence + Pause to capture a step.</li>"
    "<li>Changes are live in RAM - Config -> Save to NVM to persist.</li>"
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
        self._seq_saved = {}     # axis state saved on sequence Start, restored on Stop
        self._specs = {}         # key -> FloatSpec | BoolSpec
        self._inf_btns = {}      # key -> QToolButton (allow_inf fields)
        self._apply_btns = {}    # key -> QPushButton (requires_idle fields)
        self._pending = {}       # debounced float writes {key: value}

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

        # debounced float writes: restarted on each valueChanged, flushed on
        # editingFinished; a single batch is written and read back per fire.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._flush)

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
                self._specs[spec.key] = spec
                tip = _TIPS.get(spec.key, "")
                if spec.kind == _F:
                    key = spec.key
                    w = QDoubleSpinBox()
                    w.setDecimals(spec.decimals)
                    w.setRange(spec.minv, spec.maxv)
                    w.setSuffix(spec.suffix)
                    w.setToolTip(tip)
                    lbl = QLabel(spec.label + ":")
                    lbl.setToolTip(tip)
                    self._widgets[key] = (_F, w)
                    # Row = spinbox [+ inf toggle] [+ Apply].
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(w, 1)
                    if spec.allow_inf:
                        inf = QToolButton()
                        inf.setText("∞")
                        inf.setCheckable(True)
                        inf.setToolTip("Set this value to infinity (disable the limit).")
                        inf.toggled.connect(
                            lambda on, k=key: self._on_inf_toggled(k, on))
                        self._inf_btns[key] = inf
                        row.addWidget(inf)
                    if spec.requires_idle:
                        # No auto-write: only the Apply button writes, and only
                        # when the axis is IDLE.
                        apply_btn = QPushButton("Apply")
                        apply_btn.setToolTip(
                            "Write this value. Requires the axis in IDLE.")
                        apply_btn.clicked.connect(
                            lambda _=False, k=key: self._apply_idle(k))
                        self._apply_btns[key] = apply_btn
                        row.addWidget(apply_btn)
                    else:
                        w.valueChanged.connect(
                            lambda _v, k=key: self._queue(k))
                        w.editingFinished.connect(self._flush_now)
                    form.addRow(lbl, row)
                else:
                    key = spec.key
                    w = QCheckBox(spec.label)
                    w.setToolTip(tip)
                    # Bools apply immediately (no debounce) but still verify.
                    w.toggled.connect(lambda v, k=key: self._on_bool(k, bool(v)))
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

        # write status: shows "key ✓" or "key FAILED: ..." (red) after each batch
        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        note = QLabel("Sequence drives the motor between A and B (watch the "
                      "graphs on the right). Changes apply live in RAM; use "
                      "Config -> Save to NVM to keep them.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        root.addWidget(note)
        root.addStretch(1)

        self._seq_btn.toggled.connect(self._toggle_seq)
        self._seq_dwell.valueChanged.connect(self._on_dwell_changed)
        self._seq_timer = QTimer(self)
        self._seq_timer.timeout.connect(self._seq_tick)
        self._set_enabled(False)

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        self._pending.clear()
        self._debounce.stop()
        self._status.setText("")
        self._status.setStyleSheet("")
        if dev is None:                    # disconnected: disable all controls
            self._set_enabled(False)
            return
        values = dev.get_tuning()
        for key, (kind, w) in self._widgets.items():
            present = key in values
            w.setEnabled(present)          # grey out params this fw lacks
            inf = self._inf_btns.get(key)
            if inf is not None:
                inf.setEnabled(present)
            apply_btn = self._apply_btns.get(key)
            if apply_btn is not None:
                apply_btn.setEnabled(present)
            if present:
                self._load_key(key, values[key])
        for w in (self._seq_chan, self._seq_a, self._seq_b, self._seq_dwell,
                  self._seq_btn):
            w.setEnabled(True)

    # --- helpers ---
    def _set_enabled(self, on: bool):
        for _kind, w in self._widgets.values():
            w.setEnabled(on)
        for btn in self._inf_btns.values():
            btn.setEnabled(on)
        for btn in self._apply_btns.values():
            btn.setEnabled(on)
        for w in (self._seq_chan, self._seq_a, self._seq_b, self._seq_dwell,
                  self._seq_btn):
            w.setEnabled(on)

    def _load_key(self, key, value):
        """Push a device value into its widget without emitting write signals.

        For allow_inf fields an infinite value checks the ∞ toggle and disables
        the spinbox; a finite value unchecks it and shows the number."""
        kind, w = self._widgets[key]
        if kind == _B:
            w.blockSignals(True)
            w.setChecked(bool(value))
            w.blockSignals(False)
            return
        inf = self._inf_btns.get(key)
        if inf is not None:
            is_inf = _is_inf(value)
            inf.blockSignals(True)
            inf.setChecked(is_inf)
            inf.blockSignals(False)
            w.setEnabled(not is_inf)
            if not is_inf:
                w.blockSignals(True)
                w.setValue(value)
                w.blockSignals(False)
            return
        w.blockSignals(True)
        w.setValue(value)
        w.blockSignals(False)

    # --- write path (debounce + read-back verification) ---
    def _queue(self, key):
        """Queue an auto-write float and (re)start the debounce timer."""
        if self._dev is None:
            return
        self._pending[key] = self._widgets[key][1].value()
        self._debounce.start()

    def _flush_now(self):
        """Flush the debounce immediately (editingFinished)."""
        self._debounce.stop()
        self._flush()

    def _flush(self):
        if self._dev is None or not self._pending:
            return
        batch = dict(self._pending)
        self._pending.clear()
        self._write_and_verify(batch)

    def _on_bool(self, key, value):
        # Bools bypass the debounce but are still verified.
        if self._dev is None:
            return
        self._write_and_verify({key: value})

    def _on_inf_toggled(self, key, checked):
        w = self._widgets[key][1]
        w.setEnabled(not checked and self._dev is not None)
        if self._dev is None:
            return
        self._write_and_verify({key: float("inf") if checked else w.value()})

    def _apply_idle(self, key):
        """Apply a requires-IDLE field: refuse unless the axis is in IDLE."""
        if self._dev is None:
            return
        try:
            in_idle = self._dev.current_state() == device_mod.IDLE
        except Exception:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            in_idle = False
        if not in_idle:
            self._status.setText(
                f"{key} requires IDLE — put the axis in Idle first")
            self._status.setStyleSheet("color: red;")
            return
        self._write_and_verify({key: self._widgets[key][1].value()})

    def _write_and_verify(self, batch):
        """Write a batch, show per-key ✓/FAILED, and revert failed widgets."""
        try:
            results = self._dev.set_tuning(**batch)
        except Exception as e:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            results = {k: (False, f"write error: {e}") for k in batch}
        msgs = []
        ok_all = True
        for key, (ok, info) in results.items():
            if ok:
                msgs.append(f"{key} ✓")
            else:
                ok_all = False
                msgs.append(f"{key} FAILED: {info}")
                self._revert(key)
        self._status.setText("   ".join(msgs))
        self._status.setStyleSheet("" if ok_all else "color: red;")

    def _revert(self, key):
        """Restore a widget to the device's actual value after a failed write."""
        if self._dev is None or key not in self._widgets:
            return
        try:
            values = self._dev.get_tuning()
        except Exception:  # noqa: BLE001
            return
        if key in values:
            self._load_key(key, values[key])

    # --- back-and-forth sequence ---
    def _toggle_seq(self, on: bool):
        if self._dev is None:
            self._seq_btn.setChecked(False)
            return
        if on:
            ch = self._seq_chan.currentData()
            # Save what we're about to change so Stop can put it all back.
            try:
                self._seq_saved = {
                    "control_mode": self._dev.get_control_mode(),
                    "input_mode": self._dev.get_motion_config()["input_mode"],
                    "requested_state": self._dev.get_requested_state(),
                }
            except Exception:  # noqa: BLE001 - a USB hiccup mustn't crash the UI
                self._seq_saved = {}
            try:
                self._dev.set_input_mode(1)              # PASSTHROUGH: clean steps
                self._dev.set_control_mode(_SEQ_MODE[ch])
            except Exception:  # noqa: BLE001
                pass
            self._seq_i = 0
            self._send_seq()                             # point A = safe initial setpoint
            try:
                self._dev.set_closed_loop(True)          # arm only after a setpoint exists
            except Exception:  # noqa: BLE001
                pass
            self._seq_timer.start(max(50, int(self._seq_dwell.value() * 1000)))
            self._seq_btn.setText("Stop")
        else:
            self._seq_timer.stop()
            self._stop_seq_safe()
            self._seq_btn.setText("Start")

    def _stop_seq_safe(self):
        """Command a mode-appropriate safe stop, then restore the saved modes.

        Velocity -> zero speed; position -> hold the current position. Then
        restore input_mode and control_mode, and if the axis was IDLE when the
        sequence started, request IDLE again. Every device call is guarded so a
        USB hiccup during teardown can't crash the UI."""
        if self._dev is None:
            return
        ch = self._seq_chan.currentData()
        try:
            if ch == "vel":
                self._dev.set_input_vel(0.0)
            else:
                self._dev.set_input_pos(self._dev.feedback()["pos"])
        except Exception:  # noqa: BLE001
            pass
        saved = self._seq_saved or {}
        try:
            if "input_mode" in saved:
                self._dev.set_input_mode(saved["input_mode"])
        except Exception:  # noqa: BLE001
            pass
        try:
            if "control_mode" in saved:
                self._dev.set_control_mode(saved["control_mode"])
        except Exception:  # noqa: BLE001
            pass
        try:
            if saved.get("requested_state") == device_mod.IDLE:
                self._dev.set_requested_state(device_mod.IDLE)
        except Exception:  # noqa: BLE001
            pass

    def _on_dwell_changed(self, value):
        """Retime a running sequence when the dwell spinbox changes."""
        if self._seq_timer.isActive():
            self._seq_timer.setInterval(max(50, int(value * 1000)))

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
