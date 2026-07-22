"""Tuning tab: adjust the key control-loop parameters independently.

Grouped inner-to-outer (the order you normally tune in): feedback (encoder
bandwidths) -> current loop + its feedforwards -> velocity loop -> position loop
-> gain scheduling -> motor model. Edits are debounced then written to the
ODrive and verified by read-back (✓ or an error in the status line). Drive the
motor with the back-and-forth sequence in the Control panel (left, always
visible) and watch the repeated response on the right-hand graphs.

Parameters the connected firmware doesn't expose are shown disabled. Changes are
live in RAM; use Config -> Save to NVM to persist."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QPushButton, QToolButton,
                               QLineEdit, QCheckBox, QScrollArea)


def _fmt_num(v) -> str:
    """Compact but precise text for a float field (trims trailing zeros,
    keeps small values like 2e-05 readable)."""
    try:
        return f"{float(v):.10g}"
    except (TypeError, ValueError):
        return str(v)


class FloatEdit(QLineEdit):
    """A free-text numeric field that stands in for QDoubleSpinBox: type any
    number (no step arrows, no fixed decimals). Exposes value()/setValue() and a
    valueChanged(float) signal so the panel's debounce / read-back / ∞ / Apply
    wiring is unchanged. Invalid text reverts to the last valid value on commit;
    the value is clamped to [minv, maxv] on editing-finished. The unit is shown
    in the row label, not the field."""

    valueChanged = Signal(float)

    def __init__(self, minv, maxv, parent=None):
        super().__init__(parent)
        self._min = minv
        self._max = maxv
        self._value = 0.0
        self.textEdited.connect(self._on_text_edited)
        self.editingFinished.connect(self._reformat)

    def _parse(self):
        try:
            return float(self.text().strip())
        except ValueError:
            return None

    def _on_text_edited(self, _t):
        v = self._parse()
        if v is not None:                 # emit only on a parseable value
            self._value = v
            self.valueChanged.emit(v)

    def _reformat(self):
        v = self._parse()
        if v is None:
            v = self._value              # revert to last valid
        v = max(self._min, min(self._max, v))
        self._value = v
        self._set_text(v)

    def value(self) -> float:
        return self._value

    def setValue(self, v):
        try:
            self._value = float(v)
        except (TypeError, ValueError):
            return
        self._set_text(self._value)

    def _set_text(self, v):
        self.blockSignals(True)
        self.setText(_fmt_num(v))
        self.blockSignals(False)

from core import device as device_mod

_F = "f"
_B = "b"

# Appended to a parameter's tooltip when the connected firmware lacks it.
_NA_SUFFIX = " — n/a on this firmware"


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
    inf_negative: bool = False   # ∞ toggle writes -inf (min-side limits)
    kind: str = _F


@dataclass
class BoolSpec:
    key: str
    label: str
    kind: str = _B


def _f(key, label, suffix, decimals, maxv, *, minv=0.0,
       allow_inf=False, requires_idle=False, inf_negative=False):
    return FloatSpec(key, label, suffix, decimals, maxv, minv,
                     allow_inf, requires_idle, inf_negative)


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
    ("Velocity & overspeed limits", [
        _b("enable_vel_limit", "Enforce vel limit"),
        _b("enable_torque_mode_vel_limit", "Torque-mode vel limit"),
        _f("vel_limit_tolerance", "Vel limit tolerance", "", 3, 100.0, minv=1.0),
        _b("enable_overspeed_error", "Overspeed error"),
    ]),
    ("Torque & bus limits", [
        _f("torque_soft_min", "Torque soft min", " Nm", 3, 0.0,
           minv=-100000.0, allow_inf=True, inf_negative=True),
        _f("torque_soft_max", "Torque soft max", " Nm", 3, 100000.0, allow_inf=True),
        _f("I_bus_soft_min", "Bus current soft min", " A", 2, 0.0,
           minv=-100000.0, allow_inf=True, inf_negative=True),
        _f("I_bus_soft_max", "Bus current soft max", " A", 2, 100000.0, allow_inf=True),
        _f("P_bus_soft_min", "Bus power soft min", " W", 1, 0.0,
           minv=-100000.0, allow_inf=True, inf_negative=True),
        _f("P_bus_soft_max", "Bus power soft max", " W", 1, 100000.0, allow_inf=True),
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
        _b("phase_resistance_valid", "Phase resistance valid"),
        _f("phase_inductance", "Phase inductance", " H", 8, 10.0, requires_idle=True),
        _b("phase_inductance_valid", "Phase inductance valid"),
        _f("ff_pm_flux_linkage", "PM flux linkage", " Wb", 8, 100.0),
        _b("ff_pm_flux_linkage_valid", "PM flux linkage valid"),
        _f("motor_model_l_d", "Model L_d", " H", 8, 10.0),
        _f("motor_model_l_q", "Model L_q", " H", 8, 10.0),
        _b("motor_model_l_dq_valid", "Model L_d/L_q valid"),
    ]),
    ("Report filtering", [
        _f("I_measured_report_filter_k", "Iq/Id report filter k", "", 4, 1.0, minv=0.0),
        _f("power_torque_report_filter_bandwidth", "Power/torque report bw",
           " 1/s", 1, 100000.0),
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
    "phase_resistance_valid":
        "Marks the manually entered value as valid so the firmware uses it. Normally "
        "set by calibration.",
    "phase_inductance_valid":
        "Marks the manually entered value as valid so the firmware uses it. Normally "
        "set by calibration.",
    "ff_pm_flux_linkage_valid":
        "When true, the explicit ff_pm_flux_linkage overrides the value derived from "
        "torque constant and pole pairs.",
    "motor_model_l_dq_valid":
        "When true, the current feedforward uses motor_model_l_d/l_q instead of "
        "phase_inductance.",
    "enable_vel_limit":
        "Enforce vel_limit in velocity/position control.",
    "enable_torque_mode_vel_limit":
        "In torque mode, reduce commanded torque as speed approaches vel_limit. When "
        "active this can look like poor torque tuning.",
    "vel_limit_tolerance":
        "Multiple of vel_limit at which the overspeed error trips (e.g. 1.2 = 20% "
        "over). Used with enable_overspeed_error.",
    "enable_overspeed_error":
        "Disarm with VELOCITY_LIMIT_VIOLATION when speed exceeds vel_limit x tolerance.",
    "torque_soft_min":
        "Independent negative/positive torque clamp [Nm]. ±Infinity disables.",
    "torque_soft_max":
        "Independent negative/positive torque clamp [Nm]. ±Infinity disables.",
    "I_bus_soft_min":
        "DC bus current clamp [A]; when hit ODrive folds back motoring/braking torque "
        "— can masquerade as bad tuning.",
    "I_bus_soft_max":
        "DC bus current clamp [A]; when hit ODrive folds back motoring/braking torque "
        "— can masquerade as bad tuning.",
    "P_bus_soft_min":
        "DC bus power clamp [W]; when hit ODrive folds back motoring/braking torque — "
        "can masquerade as bad tuning.",
    "P_bus_soft_max":
        "DC bus power clamp [W]; when hit ODrive folds back motoring/braking torque — "
        "can masquerade as bad tuning.",
    "I_measured_report_filter_k":
        "Low-pass gain applied to *reported* Iq/Id values only — the control loop is "
        "unaffected. 1 = unfiltered. Filtered reporting can hide ripple that still "
        "exists.",
    "power_torque_report_filter_bandwidth":
        "Filter bandwidth for reported power/torque values only; does not affect "
        "control.",
}

# read-only diagnostics: key -> (label, suffix, tooltip)
_DIAG = [
    ("effective_current_lim", "Effective current limit", " A",
     "Actual dynamic current limit after motor/inverter/temperature/voltage "
     "constraints — compare with current_soft_max."),
    ("effective_torque_setpoint", "Effective torque setpoint", " Nm",
     "Final torque request out of the controller after all limiting (incl. "
     "torque-mode vel limit)."),
    ("vel_integrator_torque", "Vel integrator torque", " Nm",
     "Current torque contribution of the velocity integrator — watch for windup."),
]

_GUIDE_HTML = (
    "<b>Tuning guide &mdash; read me first</b>"
    "<p>Tune from the <b>inside out</b>: feedback &rarr; current &rarr; velocity "
    "&rarr; position, then feedforward / shaping. Each inner loop must be solid "
    "before you tune the outer one. The motor <b>will move</b> &mdash; keep it "
    "free to spin and keep the top-bar <b>Disarm (IDLE)</b> within reach.</p>"

    "<p><b>Which tool does what</b></p>"
    "<ul>"
    "<li><b>Control panel</b> (left, always visible) &mdash; command the motor: "
    "requested state (including <b>Full calibration</b> &mdash; do this first), "
    "control mode, setpoints, and motion shaping. Its <b>Back-and-forth "
    "sequence</b> drives repeated A&harr;B steps in whatever input mode you pick, "
    "so you can drive the motor while watching these parameters and the graphs; "
    "hit <b>Pause</b> to freeze and inspect a step.</li>"
    "<li><b>This Tuning tab</b> &mdash; set every loop parameter.</li>"
    "<li><b>Capture tab</b> &mdash; 8&nbsp;kHz onboard-scope capture, the only tool "
    "fast enough to see the <i>current loop</i>. Use it to verify the current loop "
    "and to see fine step detail on any loop.</li>"
    "<li><b>Top bar</b> &mdash; live State / Result / Error; <b>Clear errors</b> "
    "after a fault; <b>Config &rarr; Save to NVM</b> to persist when done.</li>"
    "</ul>"

    "<p><b>0. Prerequisites</b></p>"
    "<ul>"
    "<li>Run the full <b>Calibration</b> (Control panel &rarr; requested state "
    "&rarr; <b>Full calibration</b>) &mdash; you need valid phase R/L, flux "
    "linkage and encoder offset. Confirm the top bar shows <b>Result: SUCCESS</b> "
    "and no error (use <b>Clear errors</b> if needed).</li>"
    "<li>Set safe limits before spinning: <tt>current_soft_max</tt> / "
    "<tt>current_hard_max</tt>, <tt>vel_limit</tt>, and a correct "
    "<tt>torque_constant</tt> (&asymp; 8.27 / KV).</li>"
    "</ul>"

    "<p><b>1. Feedback &mdash; encoder bandwidth</b></p>"
    "<ul>"
    "<li>Set <tt>encoder_bandwidth</tt> to match your encoder: high-resolution "
    "encoders tolerate high values; hall sensors need low (~10&ndash;100). It "
    "filters the position/velocity estimate and <i>caps how high the loop gains "
    "can go</i>, so set it before tuning gains. Higher = less lag but more noise.</li>"
    "</ul>"

    "<p><b>2. Current (torque) loop &mdash; set bandwidth, verify with Capture</b></p>"
    "<ul>"
    "<li>You do <i>not</i> hand-tune the current PI gains &mdash; ODrive derives "
    "them from <tt>current_control_bandwidth</tt> plus phase R/L. Leave the default "
    "(~1000&nbsp;1/s) unless you have a reason to change it.</li>"
    "<li><b>Verify:</b> Capture tab &rarr; preset <b>Current loop (Iq)</b>, tick the "
    "step stimulus (a small torque step), Capture. <tt>Iq_measured</tt> should "
    "track <tt>Iq_setpoint</tt> with a fast rise, little overshoot and no ringing.</li>"
    "<li>Only if you need faster torque <i>and</i> R/L are trustworthy: raise "
    "<tt>current_control_bandwidth</tt> gradually (e.g. 1000 &rarr; 1500 &rarr; "
    "2000), re-capturing each time. Stop at the first overshoot, ringing or "
    "audible noise. Never push it blindly toward the 8&nbsp;kHz loop rate.</li>"
    "</ul>"

    "<p><b>3. Velocity loop</b></p>"
    "<ul>"
    "<li>Use <b>Velocity</b> control mode, and set <b>Passthrough</b> in the "
    "Control panel's Motion-shaping selector for clean step responses (the "
    "Back-and-forth sequence honors whatever input mode you choose).</li>"
    "<li>Set <tt>vel_integrator_gain</tt> = 0 (tune P before I).</li>"
    "<li>Raise <tt>vel_gain</tt> ~30% per step until you hear whine / see vibration "
    "on the velocity graph, then back off to about half.</li>"
    "<li>Raise <tt>vel_integrator_gain</tt> (start near the numeric value of "
    "<tt>vel_gain</tt>) until a velocity step is slightly underdamped, then halve "
    "it. It removes steady-state error under load.</li>"
    "<li>Drive steps with the Control panel's <b>Back-and-forth sequence</b> "
    "(Velocity, points A/B) and compare <b>actual</b> vs <b>ideal</b> on the "
    "velocity graph.</li>"
    "</ul>"

    "<p><b>4. Position loop</b></p>"
    "<ul>"
    "<li>Switch the Control panel to <b>Position</b> mode. Raise <tt>pos_gain</tt> "
    "until a position step just begins to overshoot / ring, then back off until it "
    "disappears. The position loop is P-only; its output is a velocity command "
    "clamped by <tt>vel_limit</tt>.</li>"
    "</ul>"

    "<p><b>5. Feedforward &amp; motion shaping (last)</b></p>"
    "<ul>"
    "<li><tt>inertia</tt> (acceleration feedforward) improves tracking during fast "
    "accelerations.</li>"
    "<li>Current feedforward (<tt>wL</tt> / <tt>bEMF</tt> / <tt>dI_dt</tt>) improves "
    "current tracking at high speed.</li>"
    "<li>Command shaping (velocity ramp, trajectory, position filter) lives in the "
    "<b>Control</b> panel &mdash; add it only after the loops are tuned in Passthrough.</li>"
    "<li>Enable <b>gain scheduling</b> if high gains buzz at standstill.</li>"
    "</ul>"

    "<p><b>Diagnosis</b></p>"
    "<ul>"
    "<li><b>actual vs ideal:</b> ideal is what the controller commands each instant; "
    "actual should track it with minimal lag and no ringing. Lagging &rarr; check "
    "limits first, then raise the relevant gain. Ringing / overshoot &rarr; lower it.</li>"
    "<li>If the response lags, first rule out an active limit (current, torque, bus, "
    "velocity or modulation) before touching gains.</li>"
    "<li>Buzzing: find the cause (too-high gains, encoder quantization noise, "
    "mechanical resonance, commutation error, current-loop instability) &mdash; lower "
    "encoder bandwidth only if estimator noise is the cause.</li>"
    "<li>Watch the top-bar <b>Result</b>: a rejected closed-loop request stays in "
    "Idle with e.g. <tt>NOT_CALIBRATED</tt>.</li>"
    "</ul>"

    "<p><b>Finish:</b> changes are live in RAM &mdash; <b>Config &rarr; Save to NVM</b> "
    "to keep them across power cycles.</p>"
)


class TuningPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        self._specs = {}         # key -> FloatSpec | BoolSpec
        self._inf_btns = {}      # key -> QToolButton (allow_inf fields)
        self._apply_btns = {}    # key -> QPushButton (requires_idle fields)
        self._pending = {}       # debounced float writes {key: value}
        self._diag_labels = {}   # key -> QLabel (read-only diagnostics)

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

        # --- live read-only diagnostics (effective limits) ---
        diag_group = QGroupBox("Diagnostics (read-only)")
        diag_form = QFormLayout(diag_group)
        for key, label, _suffix, tip in _DIAG:
            lbl = QLabel("—")
            lbl.setToolTip(tip)
            cap = QLabel(label + ":")
            cap.setToolTip(tip)
            diag_form.addRow(cap, lbl)
            self._diag_labels[key] = lbl
        root.addWidget(diag_group)

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
                    w = FloatEdit(spec.minv, spec.maxv)
                    w.setToolTip(tip)
                    unit = spec.suffix.strip()
                    lbl = QLabel(f"{spec.label} ({unit}):" if unit
                                 else f"{spec.label}:")
                    lbl.setToolTip(tip)
                    self._widgets[key] = (_F, w)
                    # Row = text field [+ inf toggle] [+ Apply].
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(w, 1)
                    if spec.allow_inf:
                        inf = QToolButton()
                        inf.setText("-∞" if spec.inf_negative else "∞")
                        inf.setCheckable(True)
                        inf.setToolTip(
                            "Set this value to -infinity (disable the limit)."
                            if spec.inf_negative
                            else "Set this value to infinity (disable the limit).")
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
                        w.editingFinished.connect(
                            lambda k=key: self._commit(k))
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

        # write status: shows "key ✓" or "key FAILED: ..." (red) after each batch
        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        note = QLabel("Drive the motor with the back-and-forth sequence in the "
                      "Control panel (left) and watch the graphs on the right. "
                      "Changes apply live in RAM; use Config -> Save to NVM to "
                      "keep them.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        root.addWidget(note)
        root.addStretch(1)

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
            for lbl in self._diag_labels.values():
                lbl.setText("—")
            return
        values = dev.get_tuning()
        for key, (kind, w) in self._widgets.items():
            present = key in values
            w.setEnabled(present)          # grey out params this fw lacks
            # Rebuild the tooltip from _TIPS each time (never append twice) and
            # flag params this firmware doesn't expose.
            tip = _TIPS.get(key, "")
            if not present:
                tip = (tip + _NA_SUFFIX) if tip else _NA_SUFFIX.strip()
            w.setToolTip(tip)
            inf = self._inf_btns.get(key)
            if inf is not None:
                inf.setEnabled(present)
            apply_btn = self._apply_btns.get(key)
            if apply_btn is not None:
                apply_btn.setEnabled(present)
            if present:
                self._load_key(key, values[key])

    def update_diagnostics(self, diag: dict) -> None:
        """Refresh the read-only diagnostics labels from Device.diagnostics().
        A missing/NaN value shows as an em dash."""
        for key, label, suffix, _tip in _DIAG:
            lbl = self._diag_labels.get(key)
            if lbl is None:
                continue
            val = diag.get(key)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                lbl.setText("—")
            else:
                lbl.setText(f"{val:.4g}{suffix}")

    # --- helpers ---
    def _set_enabled(self, on: bool):
        for _kind, w in self._widgets.values():
            w.setEnabled(on)
        for btn in self._inf_btns.values():
            btn.setEnabled(on)
        for btn in self._apply_btns.values():
            btn.setEnabled(on)

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

    def _commit(self, key):
        """On editing-finished: queue the field's current value, then flush now
        (the FloatEdit has already clamped/reformatted it)."""
        self._queue(key)
        self._flush_now()

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

    def _inf_value(self, key):
        """The infinity a key's ∞ toggle writes: -inf for min-side limits."""
        spec = self._specs.get(key)
        if spec is not None and getattr(spec, "inf_negative", False):
            return float("-inf")
        return float("inf")

    def _on_inf_toggled(self, key, checked):
        w = self._widgets[key][1]
        w.setEnabled(not checked and self._dev is not None)
        if self._dev is None:
            return
        self._write_and_verify(
            {key: self._inf_value(key) if checked else w.value()})

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
