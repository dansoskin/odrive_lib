"""Control tab: command the motor and manage axis state.

Contents: a requested-state dropdown (full state control), a live current-state
readout, a control-mode selector (Position/Velocity/Torque) whose choice both
sets the ODrive control mode and picks which setpoint is sent, a setpoint box
(units follow the mode) with Send and an optional live-send, and Arm / Idle /
Stop shortcuts."""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QComboBox, QLabel, QDoubleSpinBox, QPushButton,
                               QCheckBox)

from core import device as device_mod

# (label, control_mode value, unit) for the setpoint modes we can command
_MODES = [
    ("Position", device_mod.CONTROL_MODE_POSITION, "turns"),
    ("Velocity", device_mod.CONTROL_MODE_VELOCITY, "turns/s"),
    ("Torque", device_mod.CONTROL_MODE_TORQUE, "Nm"),
]


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
        self._setpoint = QDoubleSpinBox()
        self._setpoint.setRange(-100000.0, 100000.0)
        self._setpoint.setDecimals(3)
        self._setpoint.setSuffix(" turns")
        self._send = QPushButton("Send")
        self._live = QCheckBox("live send")

        sp_row = QHBoxLayout()
        sp_row.addWidget(self._setpoint, 1)
        sp_row.addWidget(self._send)

        self._abspos = QDoubleSpinBox()
        self._abspos.setRange(-100000.0, 100000.0)
        self._abspos.setDecimals(3)
        self._abspos.setSuffix(" turns")
        self._set_abs = QPushButton("Set current position")
        abs_row = QHBoxLayout()
        abs_row.addWidget(self._abspos, 1)
        abs_row.addWidget(self._set_abs)

        form.addRow("Requested state:", self._req)
        form.addRow("Current state:", self._cur)
        form.addRow("Control mode:", self._mode)
        form.addRow("Setpoint:", sp_row)
        form.addRow("", self._live)
        form.addRow("Set current pos:", abs_row)
        root.addLayout(form)

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
        self._send.clicked.connect(self._send_setpoint)
        self._setpoint.valueChanged.connect(self._on_value_changed)
        self._set_abs.clicked.connect(self._on_set_abs)
        self._arm.clicked.connect(self._on_arm)
        self._idle.clicked.connect(self._on_idle)
        self._stop.clicked.connect(self._on_stop)

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        self._sync_combo(self._req, dev.get_requested_state())
        self._sync_combo(self._mode, dev.get_control_mode())
        self._update_units()
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

    def _send_setpoint(self):
        if self._dev is None:
            return
        mode = self._mode.currentData()
        value = self._setpoint.value()
        if mode == device_mod.CONTROL_MODE_POSITION:
            self._guard(lambda: self._dev.set_input_pos(value))
        elif mode == device_mod.CONTROL_MODE_VELOCITY:
            self._guard(lambda: self._dev.set_input_vel(value))
        elif mode == device_mod.CONTROL_MODE_TORQUE:
            self._guard(lambda: self._dev.set_input_torque(value))

    def _on_set_abs(self):
        self._guard(lambda: self._dev.set_current_position(self._abspos.value()))

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
        for w in (self._req, self._mode, self._setpoint, self._send, self._live,
                  self._abspos, self._set_abs, self._arm, self._idle, self._stop):
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
