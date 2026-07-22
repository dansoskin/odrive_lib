"""Control tab: command the motor and manage axis state.

Contents: a requested-state dropdown (full state control), a live current-state
readout, a control-mode selector (Position/Velocity/Torque) whose choice both
sets the ODrive control mode and picks which setpoint is sent, a setpoint box
(units follow the mode) with Send and an optional live-send, and Arm / Idle /
Stop shortcuts."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QComboBox, QDoubleSpinBox, QPushButton,
                               QCheckBox, QGroupBox, QLabel)

from core import device as device_mod
from core import settings

_CONV_TIP = ("Conversion / gear ratio. Position and velocity setpoints you "
             "enter (and 'set current position') are multiplied by this before "
             "being sent to the driver: driver_revs = your_value × conversion. "
             "e.g. a 1:3 gearbox → enter 3, so commanding 1 output revolution "
             "sends 3 motor revs. 1 = no conversion. Torque is not converted. "
             "Saved to ~/.odrtune/config.json.")

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

# ramp/trajectory parameter -> (label, unit suffix, tooltip)
_RAMP_PARAMS = {
    "vel_ramp_rate": ("Vel ramp rate", " turns/s²",
                      "Slew rate [turns/s²] applied to the velocity setpoint in "
                      "VEL_RAMP mode. Lower = gentler acceleration."),
    "torque_ramp_rate": ("Torque ramp rate", " Nm/s",
                         "Slew rate [Nm/s] applied to the torque setpoint in "
                         "TORQUE_RAMP mode. Lower = gentler torque changes."),
    "input_filter_bandwidth": ("Filter bandwidth", " 1/s",
                               "Bandwidth [1/s] of the second-order critically "
                               "damped position-input filter used by POS_FILTER "
                               "mode. Higher = less lag but passes more command "
                               "stepping and noise."),
    "trap_vel_limit": ("Traj vel limit", " turns/s",
                       "Cruise velocity limit [turns/s] for TRAP_TRAJ moves."),
    "trap_accel_limit": ("Traj accel limit", " turns/s²",
                         "Acceleration limit [turns/s²] for TRAP_TRAJ moves."),
    "trap_decel_limit": ("Traj decel limit", " turns/s²",
                         "Deceleration limit [turns/s²] for TRAP_TRAJ moves."),
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
        self._ramp_pending = {}      # debounced motion-shaping writes
        root = QVBoxLayout(self)

        # debounce motion-shaping writes (~250 ms) and config.json saves (~500 ms)
        self._ramp_debounce = QTimer(self)
        self._ramp_debounce.setSingleShot(True)
        self._ramp_debounce.setInterval(250)
        self._ramp_debounce.timeout.connect(self._flush_ramp)
        self._conv_save_timer = QTimer(self)
        self._conv_save_timer.setSingleShot(True)
        self._conv_save_timer.setInterval(500)
        self._conv_save_timer.timeout.connect(self._save_conversion)

        form = QFormLayout()
        self._req = QComboBox()
        for name, value in device_mod.AXIS_STATES.items():
            self._req.addItem(name, value)
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
        form.addRow("Control mode:", self._mode)
        form.addRow("Conversion:", self._conv)
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
        for key, (label, suffix, tip) in _RAMP_PARAMS.items():
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100000.0)
            spin.setDecimals(3)
            spin.setSuffix(suffix)
            spin.setToolTip(tip)
            spin.valueChanged.connect(lambda _v, k=key: self._queue_ramp(k))
            spin.editingFinished.connect(self._flush_ramp_now)
            self._ramp_rows[key] = spin
            self._ramp_form.addRow(label + ":", spin)
        self._ramp_status = QLabel("")
        self._ramp_status.setWordWrap(True)
        self._ramp_form.addRow(self._ramp_status)
        root.addWidget(mgroup)

        # --- back-and-forth sequence (honors the input mode above) ---
        # Unlike the Tuning-tab sequence (which forces Passthrough for clean
        # steps), this one leaves input_mode alone, so you can watch the motor
        # move under the ramp / trajectory / filter you configured above.
        seq = QGroupBox("Back-and-forth (uses the input mode above)")
        seq_form = QFormLayout(seq)
        self._cseq_a = QDoubleSpinBox()
        self._cseq_a.setRange(-1e9, 1e9)
        self._cseq_a.setDecimals(3)
        self._cseq_a.setSuffix(" units")
        self._cseq_b = QDoubleSpinBox()
        self._cseq_b.setRange(-1e9, 1e9)
        self._cseq_b.setDecimals(3)
        self._cseq_b.setSuffix(" units")
        self._cseq_b.setValue(1.0)
        self._cseq_dwell = QDoubleSpinBox()
        self._cseq_dwell.setRange(0.05, 3600.0)
        self._cseq_dwell.setDecimals(2)
        self._cseq_dwell.setValue(1.0)
        self._cseq_dwell.setSuffix(" s")
        self._cseq_btn = QPushButton("Start")
        self._cseq_btn.setCheckable(True)
        self._cseq_btn.setToolTip(
            "Drive the motor back and forth between A and B (in the current "
            "control mode + conversion units), using the configured input mode "
            "so you can inspect ramped/trajectory motion. Arms closed loop on "
            "start; Stop holds/zeroes and stays armed.")
        seq_form.addRow("Point A:", self._cseq_a)
        seq_form.addRow("Point B:", self._cseq_b)
        seq_form.addRow("Dwell:", self._cseq_dwell)
        seq_form.addRow("", self._cseq_btn)
        root.addWidget(seq)

        self._cseq_i = 0
        self._cseq_timer = QTimer(self)
        self._cseq_timer.timeout.connect(self._cseq_tick)

        btns = QHBoxLayout()
        self._arm = QPushButton("Arm (closed loop)")
        self._idle = QPushButton("Idle")
        self._stop = QPushButton("Stop (hold)")
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
        self._cseq_btn.toggled.connect(self._toggle_cseq)
        self._cseq_dwell.valueChanged.connect(self._cseq_retime)

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        self._ramp_pending.clear()
        self._ramp_debounce.stop()
        self._ramp_status.setText("")
        self._ramp_status.setStyleSheet("")
        self._cseq_cancel()                # stop any running back-and-forth
        if dev is None:                    # disconnected: disable all controls
            self._set_enabled(False)
            return
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

    def _queue_ramp(self, key):
        """Queue a motion-shaping write and (re)start the debounce timer."""
        if self._dev is None:
            return
        self._ramp_pending[key] = self._ramp_rows[key].value()
        self._ramp_debounce.start()

    def _flush_ramp_now(self):
        self._ramp_debounce.stop()
        self._flush_ramp()

    def _flush_ramp(self):
        """Write the pending motion params, then read them back and verify."""
        if self._dev is None or not self._ramp_pending:
            return
        batch = dict(self._ramp_pending)
        self._ramp_pending.clear()
        try:
            self._dev.set_motion(**batch)
        except Exception:  # noqa: BLE001 - reported via the read-back below
            pass
        try:
            mc = self._dev.get_motion_config()
        except Exception as e:  # noqa: BLE001
            self._ramp_status.setText(f"readback error: {e}")
            self._ramp_status.setStyleSheet("color: red;")
            return
        msgs = []
        ok_all = True
        for key, requested in batch.items():
            actual = mc.get(key)
            if device_mod.values_match(requested, actual):
                msgs.append(f"{key} ✓")
            else:
                ok_all = False
                msgs.append(f"{key} FAILED: readback {actual} != {requested}")
                spin = self._ramp_rows[key]
                spin.blockSignals(True)
                if actual is not None:
                    spin.setValue(actual)
                spin.blockSignals(False)
        self._ramp_status.setText("   ".join(msgs))
        self._ramp_status.setStyleSheet("" if ok_all else "color: red;")

    def _update_ramp_visibility(self):
        active = set(_MODE_PARAMS.get(self._imode.currentData(), []))
        for key, spin in self._ramp_rows.items():
            self._ramp_form.setRowVisible(spin, key in active)

    def _send_setpoint(self):
        self._send_value(self._setpoint.value())

    def _send_value(self, value):
        """Send one setpoint in the current control mode, applying the
        conversion factor (position/velocity) as user-units -> motor revs;
        torque is raw Nm. Does NOT touch input_mode, so whatever motion shaping
        is configured (ramp / trajectory / filter / passthrough) applies."""
        if self._dev is None:
            return
        mode = self._mode.currentData()
        rev = value * self._factor()
        if mode == device_mod.CONTROL_MODE_POSITION:
            self._guard(lambda: self._dev.set_input_pos(rev))
        elif mode == device_mod.CONTROL_MODE_VELOCITY:
            self._guard(lambda: self._dev.set_input_vel(rev))
        elif mode == device_mod.CONTROL_MODE_TORQUE:
            self._guard(lambda: self._dev.set_input_torque(value))  # Nm, raw

    def _on_set_abs(self):
        rev = self._abspos.value() * self._factor()
        self._guard(lambda: self._dev.set_current_position(rev))

    def _factor(self) -> float:
        c = self._conv.value()
        return c if c else 1.0

    def _on_conv_changed(self, value):
        # Debounce: save ~500 ms after the last change, not on every tick.
        self._conv_save_timer.start()

    def _save_conversion(self):
        cfg = settings.load()
        cfg["conversion"] = self._conv.value()
        settings.save(cfg)

    def _toggle_cseq(self, on: bool):
        if self._dev is None:
            self._cseq_btn.setChecked(False)
            return
        if on:
            # Ensure the control mode matches; leave input_mode as configured.
            self._guard(lambda: self._dev.set_control_mode(self._mode.currentData()))
            self._cseq_i = 0
            self._send_value(self._cseq_a.value())      # go to A first
            self._guard(lambda: self._dev.set_closed_loop(True))
            self._cseq_timer.start(max(50, int(self._cseq_dwell.value() * 1000)))
            self._cseq_btn.setText("Stop")
        else:
            self._cseq_timer.stop()
            self._cseq_btn.setText("Start")
            self._on_stop()          # mode-appropriate safe stop, stays armed

    def _cseq_tick(self):
        self._cseq_i ^= 1
        self._send_value(self._cseq_b.value() if self._cseq_i
                         else self._cseq_a.value())

    def _cseq_retime(self):
        if self._cseq_timer.isActive():
            self._cseq_timer.setInterval(
                max(50, int(self._cseq_dwell.value() * 1000)))

    def _cseq_cancel(self):
        """Quietly stop the sequence without a safe-stop or recursion (used when
        Idle / Stop / disconnect intervene and will handle the axis themselves)."""
        self._cseq_timer.stop()
        if self._cseq_btn.isChecked():
            self._cseq_btn.blockSignals(True)
            self._cseq_btn.setChecked(False)
            self._cseq_btn.blockSignals(False)
        self._cseq_btn.setText("Start")

    def _on_arm(self):
        self._guard(lambda: self._dev.set_closed_loop(True))
        self._sync_combo(self._req, device_mod.CLOSED_LOOP_CONTROL)

    def _on_idle(self):
        self._cseq_cancel()          # don't keep commanding setpoints into IDLE
        self._guard(lambda: self._dev.set_closed_loop(False))
        self._sync_combo(self._req, device_mod.IDLE)

    def _on_stop(self):
        """Command a mode-appropriate safe stop, leaving the axis armed.

        Position -> HOLD the current position: read the current motor-frame
        estimate (feedback()["pos"], already in motor revolutions / absolute
        frame) and send it raw via set_input_pos -- do NOT apply the conversion
        factor and do NOT touch the setpoint spinbox. Velocity -> zero speed;
        Torque -> zero torque. (Previously this commanded setpoint 0, which in
        position mode raced the motor to position 0.)"""
        if self._dev is None:
            return
        self._cseq_cancel()          # a manual stop also ends the sequence
        mode = self._mode.currentData()
        if mode == device_mod.CONTROL_MODE_POSITION:
            self._guard(
                lambda: self._dev.set_input_pos(self._dev.feedback()["pos"]))
        elif mode == device_mod.CONTROL_MODE_VELOCITY:
            self._guard(lambda: self._dev.set_input_vel(0.0))
        elif mode == device_mod.CONTROL_MODE_TORQUE:
            self._guard(lambda: self._dev.set_input_torque(0.0))

    # --- helpers ---
    def _update_units(self):
        for label, value, unit in _MODES:
            if value == self._mode.currentData():
                suffix = f" {unit}"
                for w in (self._setpoint, self._cseq_a, self._cseq_b):
                    w.setSuffix(suffix)
                return

    def _set_enabled(self, on: bool):
        widgets = [self._req, self._mode, self._setpoint, self._send, self._live,
                   self._abspos, self._set_abs, self._imode, self._arm,
                   self._idle, self._stop,
                   self._cseq_a, self._cseq_b, self._cseq_dwell, self._cseq_btn]
        widgets += list(self._ramp_rows.values())
        for w in widgets:
            w.setEnabled(on)

    def _guard(self, fn):
        if self._dev is None:
            return
        try:
            fn()
        except Exception:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
            pass

    @staticmethod
    def _sync_combo(combo: QComboBox, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
