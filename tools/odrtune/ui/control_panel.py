"""Control tab: command the motor and manage axis state.

Contents: a requested-state dropdown (full state control), a live current-state
readout, a control-mode selector (Position/Velocity/Torque) whose choice both
sets the ODrive control mode and picks which setpoint is sent, a setpoint box
(units follow the mode) with Send and an optional live-send, and Arm / Idle /
Stop shortcuts."""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QComboBox, QLabel, QDoubleSpinBox, QPushButton,
                               QCheckBox, QGroupBox)

from core import device as device_mod
from core import settings

_CONV_TIP = ("Units per motor revolution. Enter position/velocity setpoints "
             "(and 'set current position') in your own units; the GUI divides "
             "by this to send revolutions to the ODrive. Torque is not "
             "converted. e.g. 360 to command degrees, or your gear/leadscrew "
             "ratio. Saved to ~/.odrtune/config.json.")

# (label, control_mode value, unit) for the setpoint modes we can command.
# Position/velocity are shown as generic "units" because the conversion factor
# maps them to motor revolutions; torque is always raw Nm.
_MODES = [
    ("Position", device_mod.CONTROL_MODE_POSITION, "units"),
    ("Velocity", device_mod.CONTROL_MODE_VELOCITY, "units/s"),
    ("Torque", device_mod.CONTROL_MODE_TORQUE, "Nm"),
]

# Input modes (fw 0.6.x InputMode enum) offered in the motion-shaping selector.
_INPUT_MODES = [
    ("Passthrough", 1),
    ("Velocity ramp", 2),
    ("Position filter", 3),
    ("Trajectory (trap)", 5),
    ("Torque ramp", 6),
]

# ramp/trajectory parameter -> (label, unit suffix)
_RAMP_PARAMS = {
    "vel_ramp_rate": ("Vel ramp rate", " turns/s²"),
    "torque_ramp_rate": ("Torque ramp rate", " Nm/s"),
    "input_filter_bandwidth": ("Filter bandwidth", " Hz"),
    "trap_vel_limit": ("Traj vel limit", " turns/s"),
    "trap_accel_limit": ("Traj accel limit", " turns/s²"),
    "trap_decel_limit": ("Traj decel limit", " turns/s²"),
}

# which ramp params are relevant for each input mode value
_MODE_PARAMS = {
    1: [],                                                   # passthrough
    2: ["vel_ramp_rate"],                                    # velocity ramp
    3: ["input_filter_bandwidth"],                           # position filter
    5: ["trap_vel_limit", "trap_accel_limit", "trap_decel_limit"],  # trap traj
    6: ["torque_ramp_rate"],                                 # torque ramp
}


class ControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        root = QVBoxLayout(self)

        form = QFormLayout()
        self._req = QComboBox()
        for name, value in device_mod.AXIS_STATES.items():
            self._req.addItem(name, value)
        self._cur = QLabel("—")
        self._mode = QComboBox()
        for label, value, _unit in _MODES:
            self._mode.addItem(label, value)
        self._conv = QDoubleSpinBox()
        self._conv.setRange(1e-6, 1e9)
        self._conv.setDecimals(6)
        self._conv.setValue(settings.load().get("conversion", 1.0))
        self._conv.setToolTip(_CONV_TIP)
        self._setpoint = QDoubleSpinBox()
        self._setpoint.setRange(-1e9, 1e9)
        self._setpoint.setDecimals(3)
        self._setpoint.setSuffix(" units")
        self._send = QPushButton("Send")
        self._live = QCheckBox("live send")

        sp_row = QHBoxLayout()
        sp_row.addWidget(self._setpoint, 1)
        sp_row.addWidget(self._send)

        self._abspos = QDoubleSpinBox()
        self._abspos.setRange(-1e9, 1e9)
        self._abspos.setDecimals(3)
        self._abspos.setSuffix(" units")
        self._set_abs = QPushButton("Set current position")
        abs_row = QHBoxLayout()
        abs_row.addWidget(self._abspos, 1)
        abs_row.addWidget(self._set_abs)

        form.addRow("Requested state:", self._req)
        form.addRow("Current state:", self._cur)
        form.addRow("Control mode:", self._mode)
        form.addRow("Units per rev:", self._conv)
        form.addRow("Setpoint:", sp_row)
        form.addRow("", self._live)
        form.addRow("Set current pos:", abs_row)
        root.addLayout(form)

        # --- motion shaping (input mode + ramp/trajectory limits) ---
        mgroup = QGroupBox("Motion shaping (ramp / trajectory)")
        self._ramp_form = QFormLayout(mgroup)
        self._imode = QComboBox()
        for label, value in _INPUT_MODES:
            self._imode.addItem(label, value)
        self._ramp_form.addRow("Input mode:", self._imode)
        self._ramp_rows = {}
        for key, (label, suffix) in _RAMP_PARAMS.items():
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100000.0)
            spin.setDecimals(3)
            spin.setSuffix(suffix)
            spin.valueChanged.connect(lambda v, k=key: self._on_ramp(k, v))
            self._ramp_rows[key] = spin
            self._ramp_form.addRow(label + ":", spin)
        root.addWidget(mgroup)

        btns = QHBoxLayout()
        self._arm = QPushButton("Arm (closed loop)")
        self._idle = QPushButton("Idle")
        self._stop = QPushButton("Stop (0)")
        for b in (self._arm, self._idle, self._stop):
            btns.addWidget(b)
        root.addLayout(btns)
        root.addStretch(1)

        self._set_enabled(False)
        self._req.activated.connect(self._on_req)
        self._mode.activated.connect(self._on_mode)
        self._imode.activated.connect(self._on_imode)
        self._send.clicked.connect(self._send_setpoint)
        self._setpoint.valueChanged.connect(self._on_value_changed)
        self._set_abs.clicked.connect(self._on_set_abs)
        self._arm.clicked.connect(self._on_arm)
        self._idle.clicked.connect(self._on_idle)
        self._stop.clicked.connect(self._on_stop)
        self._conv.valueChanged.connect(self._on_conv_changed)

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        self._sync_combo(self._req, dev.get_requested_state())
        self._sync_combo(self._mode, dev.get_control_mode())
        self._update_units()
        mc = dev.get_motion_config()
        self._sync_combo(self._imode, mc["input_mode"])
        for key, spin in self._ramp_rows.items():
            spin.blockSignals(True)
            spin.setValue(mc[key])
            spin.blockSignals(False)
        self._update_ramp_visibility()
        self._set_enabled(True)

    def update_state(self) -> None:
        """Called each tick by MainWindow to refresh the current-state readout."""
        if self._dev is None:
            return
        try:
            self._cur.setText(self._state_name(self._dev.current_state()))
        except Exception:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            pass

    # --- handlers ---
    def _on_req(self):
        self._guard(lambda: self._dev.set_requested_state(self._req.currentData()))

    def _on_mode(self):
        self._update_units()
        self._guard(lambda: self._dev.set_control_mode(self._mode.currentData()))

    def _on_value_changed(self):
        if self._live.isChecked():
            self._send_setpoint()

    def _on_imode(self):
        self._update_ramp_visibility()
        self._guard(lambda: self._dev.set_input_mode(self._imode.currentData()))

    def _on_ramp(self, key, value):
        self._guard(lambda: self._dev.set_motion(**{key: value}))

    def _update_ramp_visibility(self):
        active = set(_MODE_PARAMS.get(self._imode.currentData(), []))
        for key, spin in self._ramp_rows.items():
            self._ramp_form.setRowVisible(spin, key in active)

    def _send_setpoint(self):
        if self._dev is None:
            return
        mode = self._mode.currentData()
        value = self._setpoint.value()
        rev = value / self._factor()   # user units -> revolutions
        if mode == device_mod.CONTROL_MODE_POSITION:
            self._guard(lambda: self._dev.set_input_pos(rev))
        elif mode == device_mod.CONTROL_MODE_VELOCITY:
            self._guard(lambda: self._dev.set_input_vel(rev))
        elif mode == device_mod.CONTROL_MODE_TORQUE:
            self._guard(lambda: self._dev.set_input_torque(value))  # Nm, raw

    def _on_set_abs(self):
        rev = self._abspos.value() / self._factor()
        self._guard(lambda: self._dev.set_current_position(rev))

    def _factor(self) -> float:
        c = self._conv.value()
        return c if c else 1.0

    def _on_conv_changed(self, value):
        cfg = settings.load()
        cfg["conversion"] = value
        settings.save(cfg)

    def _on_arm(self):
        self._guard(lambda: self._dev.set_closed_loop(True))
        self._sync_combo(self._req, device_mod.CLOSED_LOOP_CONTROL)

    def _on_idle(self):
        self._guard(lambda: self._dev.set_closed_loop(False))
        self._sync_combo(self._req, device_mod.IDLE)

    def _on_stop(self):
        """Command zero setpoint for the active mode (leaves the axis armed)."""
        if self._dev is None:
            return
        self._setpoint.setValue(0.0)
        self._send_setpoint()

    # --- helpers ---
    def _update_units(self):
        for label, value, unit in _MODES:
            if value == self._mode.currentData():
                self._setpoint.setSuffix(f" {unit}")
                return

    def _set_enabled(self, on: bool):
        widgets = [self._req, self._mode, self._setpoint, self._send, self._live,
                   self._abspos, self._set_abs, self._imode, self._arm,
                   self._idle, self._stop]
        widgets += list(self._ramp_rows.values())
        for w in widgets:
            w.setEnabled(on)

    def _guard(self, fn):
        if self._dev is None:
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            self._cur.setText(f"error: {exc}")

    @staticmethod
    def _sync_combo(combo: QComboBox, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    @staticmethod
    def _state_name(value: int) -> str:
        for name, v in device_mod.AXIS_STATES.items():
            if v == value:
                return name
        return str(value)
