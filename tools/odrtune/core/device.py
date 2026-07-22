"""Wrapper over the odrive USB object tree. All firmware-specific attribute
paths live here so a version change touches one file. Accepts either a real
odrive device or a duck-typed fake."""
from __future__ import annotations

# AxisState ints (fw 0.6.x)
IDLE = 1
FULL_CALIBRATION_SEQUENCE = 3
CLOSED_LOOP_CONTROL = 8

# ControlMode ints (fw 0.6.x)
CONTROL_MODE_VOLTAGE = 0
CONTROL_MODE_TORQUE = 1
CONTROL_MODE_VELOCITY = 2
CONTROL_MODE_POSITION = 3

# Human-readable option maps for the GUI dropdowns (label -> firmware int).
AXIS_STATES = {
    "Idle": IDLE,
    "Closed loop control": CLOSED_LOOP_CONTROL,
    "Full calibration": FULL_CALIBRATION_SEQUENCE,
    "Motor calibration": 4,
    "Encoder offset calibration": 7,
    "Encoder index search": 6,
}
CONTROL_MODES = {
    "Position": CONTROL_MODE_POSITION,
    "Velocity": CONTROL_MODE_VELOCITY,
    "Torque": CONTROL_MODE_TORQUE,
    "Voltage": CONTROL_MODE_VOLTAGE,
}


def state_name(value: int) -> str:
    """Human-readable name for an AxisState int."""
    for name, v in AXIS_STATES.items():
        if v == value:
            return name
    return str(value)


# ODriveError bitmask (used by axis.active_errors and axis.disarm_reason).
# This table targets the firmware line below; if a connected device reports a
# different major.minor, decoded names are flagged as unverified.
ERROR_DECODE_FW = (0, 6)

ODRIVE_ERRORS = {
    0x00000001: "INITIALIZING",
    0x00000002: "SYSTEM_LEVEL",
    0x00000004: "TIMING_ERROR",
    0x00000008: "MISSING_ESTIMATE",
    0x00000010: "BAD_CONFIG",
    0x00000020: "DRV_FAULT",
    0x00000040: "MISSING_INPUT",
    0x00000100: "DC_BUS_OVER_VOLTAGE",
    0x00000200: "DC_BUS_UNDER_VOLTAGE",
    0x00000400: "DC_BUS_OVER_CURRENT",
    0x00000800: "DC_BUS_OVER_REGEN_CURRENT",
    0x00001000: "CURRENT_LIMIT_VIOLATION",
    0x00002000: "MOTOR_OVER_TEMP",
    0x00004000: "INVERTER_OVER_TEMP",
    0x00008000: "VELOCITY_LIMIT_VIOLATION",
    0x00010000: "POSITION_LIMIT_VIOLATION",
    0x01000000: "WATCHDOG_TIMER_EXPIRED",
    0x02000000: "ESTOP_REQUESTED",
    0x04000000: "SPINOUT_DETECTED",
    0x08000000: "BRAKE_RESISTOR_DISARMED",
    0x10000000: "THERMISTOR_DISCONNECTED",
    0x40000000: "CALIBRATION_ERROR",
}


def decode_error(value: int) -> str:
    """Decode an ODriveError bitmask into 'NAME | NAME' (or 'none'). Unmapped
    bits are reported as UNKNOWN(0x..)."""
    if not value:
        return "none"
    names = []
    remaining = int(value)
    for bit, name in ODRIVE_ERRORS.items():
        if value & bit:
            names.append(name)
            remaining &= ~bit
    if remaining:
        names.append(f"UNKNOWN(0x{remaining:X})")
    return " | ".join(names)


def _get(obj, attr):
    """Read an attribute, returning NaN if this firmware doesn't expose it
    (so an absent effective-setpoint just shows a gap instead of crashing)."""
    try:
        return getattr(obj, attr)
    except Exception:  # noqa: BLE001
        return float("nan")


def connect(timeout: float = 15.0):
    """Find and return the first ODrive over USB. Raises on timeout."""
    import odrive
    return Device(odrive.find_any(timeout=timeout))


def scan(timeout: float = 5.0):
    """Return a list of Device wrappers for all ODrives found."""
    import odrive
    return [Device(d) for d in odrive.find_all(timeout=timeout)]


class Device:
    def __init__(self, raw, axis_index: int = 0):
        self._raw = raw
        self._axis = getattr(raw, f"axis{axis_index}")

    # --- identity ---
    def fw_version(self) -> tuple[int, int, int]:
        return (self._raw.fw_version_major, self._raw.fw_version_minor,
                self._raw.fw_version_revision)

    def serial_hex(self) -> str:
        return f"0x{self._raw.serial_number:X}"

    def fw_matches_error_decode(self) -> bool:
        """True if the device firmware major.minor matches the error-decode table."""
        major, minor, _rev = self.fw_version()
        return (major, minor) == ERROR_DECODE_FW

    # --- feedback snapshot ---
    def feedback(self) -> dict:
        a = self._axis
        ct = a.controller
        # For each channel: measured (actual), target (raw command you gave),
        # and ref (the controller's effective setpoint = where the motor should
        # be right now, after ramp/filter/trajectory). pos uses pos_abs (the
        # absolute frame the controller and set_abs_pos operate in).
        return {
            "pos": a.pos_vel_mapper.pos_abs,
            "pos_target": ct.input_pos,
            "pos_ref": _get(ct, "pos_setpoint"),
            "vel": a.pos_vel_mapper.vel,
            "vel_target": ct.input_vel,
            "vel_ref": _get(ct, "vel_setpoint"),
            "iq_setpoint": a.motor.foc.Iq_setpoint,
            "iq_measured": a.motor.foc.Iq_measured,
            "torque_target": ct.input_torque,
            "torque_ref": _get(ct, "torque_setpoint"),
            "torque_estimate": a.motor.torque_estimate,
            "fet_temp": a.motor.fet_thermistor.temperature,
            "motor_temp": a.motor.motor_thermistor.temperature,
            "bus_voltage": self._raw.vbus_voltage,
            "bus_current": self._raw.ibus,
        }

    # --- state / setpoints ---
    def set_requested_state(self, state: int) -> None:
        self._axis.requested_state = state

    def get_requested_state(self) -> int:
        return self._axis.requested_state

    def current_state(self) -> int:
        return self._axis.current_state

    def get_control_mode(self) -> int:
        return self._axis.controller.config.control_mode

    def set_control_mode(self, mode: int) -> None:
        self._axis.controller.config.control_mode = mode

    def procedure_result(self) -> int:
        return self._axis.procedure_result

    def errors(self) -> dict:
        return {"active_errors": self._axis.active_errors,
                "disarm_reason": self._axis.disarm_reason}

    def set_closed_loop(self, enable: bool) -> None:
        self.set_requested_state(CLOSED_LOOP_CONTROL if enable else IDLE)

    def estop(self) -> None:
        """Emergency stop: immediately disarm the motor by requesting IDLE."""
        self._axis.requested_state = IDLE

    def set_input_pos(self, pos: float) -> None:
        self._axis.controller.input_pos = pos

    def set_input_vel(self, vel: float) -> None:
        self._axis.controller.input_vel = vel

    def set_input_torque(self, torque: float) -> None:
        self._axis.controller.input_torque = torque

    def set_current_position(self, pos: float) -> None:
        """Redefine the axis's current absolute position (homing / zeroing).
        USB equivalent of the CAN Set_Absolute_Position command."""
        self._axis.set_abs_pos(pos)

    # --- gains ---
    def get_gains(self) -> dict:
        c = self._axis.controller.config
        return {"pos_gain": c.pos_gain, "vel_gain": c.vel_gain,
                "vel_integrator_gain": c.vel_integrator_gain}

    def set_gains(self, pos_gain=None, vel_gain=None,
                  vel_integrator_gain=None) -> None:
        c = self._axis.controller.config
        if pos_gain is not None:
            c.pos_gain = pos_gain
        if vel_gain is not None:
            c.vel_gain = vel_gain
        if vel_integrator_gain is not None:
            c.vel_integrator_gain = vel_integrator_gain

    # --- motion shaping (input mode + ramp/trajectory limits) ---
    def get_motion_config(self) -> dict:
        c = self._axis.controller.config
        tt = self._axis.trap_traj.config
        return {
            "input_mode": c.input_mode,
            "vel_ramp_rate": c.vel_ramp_rate,
            "torque_ramp_rate": c.torque_ramp_rate,
            "input_filter_bandwidth": c.input_filter_bandwidth,
            "trap_vel_limit": tt.vel_limit,
            "trap_accel_limit": tt.accel_limit,
            "trap_decel_limit": tt.decel_limit,
        }

    def set_input_mode(self, mode: int) -> None:
        self._axis.controller.config.input_mode = mode

    def set_motion(self, **kw) -> None:
        c = self._axis.controller.config
        tt = self._axis.trap_traj.config
        if "vel_ramp_rate" in kw:
            c.vel_ramp_rate = kw["vel_ramp_rate"]
        if "torque_ramp_rate" in kw:
            c.torque_ramp_rate = kw["torque_ramp_rate"]
        if "input_filter_bandwidth" in kw:
            c.input_filter_bandwidth = kw["input_filter_bandwidth"]
        if "trap_vel_limit" in kw:
            tt.vel_limit = kw["trap_vel_limit"]
        if "trap_accel_limit" in kw:
            tt.accel_limit = kw["trap_accel_limit"]
        if "trap_decel_limit" in kw:
            tt.decel_limit = kw["trap_decel_limit"]

    # --- per-loop tuning (feedback / current / velocity / position) ---
    def _tuning_targets(self) -> dict:
        """Map each tuning key to the (object, attribute) it lives at, so a
        firmware-path change touches only this table."""
        a = self._axis
        c = a.controller.config
        m = a.config.motor
        return {
            # feedback / estimator
            "encoder_bandwidth": (a.config, "encoder_bandwidth"),
            "commutation_encoder_bandwidth": (a.config, "commutation_encoder_bandwidth"),
            # current / torque loop
            "current_control_bandwidth": (m, "current_control_bandwidth"),
            "current_soft_max": (m, "current_soft_max"),
            "current_hard_max": (m, "current_hard_max"),
            "current_slew_rate_limit": (m, "current_slew_rate_limit"),
            # high-speed current feedforwards
            "wL_FF_enable": (m, "wL_FF_enable"),
            "bEMF_FF_enable": (m, "bEMF_FF_enable"),
            "dI_dt_FF_enable": (m, "dI_dt_FF_enable"),
            # velocity loop
            "vel_gain": (c, "vel_gain"),
            "vel_integrator_gain": (c, "vel_integrator_gain"),
            "vel_integrator_limit": (c, "vel_integrator_limit"),
            "vel_integrator_decay_gain": (c, "vel_integrator_decay_gain"),
            "vel_limit": (c, "vel_limit"),
            # position loop + inertia feedforward
            "pos_gain": (c, "pos_gain"),
            "inertia": (c, "inertia"),
            # gain scheduling
            "enable_gain_scheduling": (c, "enable_gain_scheduling"),
            "gain_scheduling_width": (c, "gain_scheduling_width"),
            "gain_scheduling_min_ratio": (c, "gain_scheduling_min_ratio"),
            # motor model (normally from calibration; needed for FF)
            "torque_constant": (m, "torque_constant"),
            "phase_resistance": (m, "phase_resistance"),
            "phase_inductance": (m, "phase_inductance"),
            "ff_pm_flux_linkage": (m, "ff_pm_flux_linkage"),
            "motor_model_l_d": (m, "motor_model_l_d"),
            "motor_model_l_q": (m, "motor_model_l_q"),
        }

    def get_tuning(self) -> dict:
        """Read every tuning parameter this firmware exposes. Keys whose
        attribute is absent on the connected device are simply omitted."""
        out = {}
        for key, (obj, attr) in self._tuning_targets().items():
            try:
                out[key] = getattr(obj, attr)
            except Exception:  # noqa: BLE001 - attr not present on this fw/config
                pass
        return out

    def set_tuning(self, **kw) -> None:
        targets = self._tuning_targets()
        for key, value in kw.items():
            if key in targets:
                obj, attr = targets[key]
                try:
                    setattr(obj, attr, value)
                except Exception:  # noqa: BLE001
                    pass

    # --- persistence ---
    def save(self) -> None:
        self._raw.save_configuration()

    def erase(self) -> None:
        self._raw.erase_configuration()

    def reboot(self) -> None:
        self._raw.reboot()

    # --- teardown ---
    def disconnect(self) -> None:
        """Best-effort release of the USB handle.

        There is no public close API in the odrive/fibre package for this
        version, so we just try `self._raw.__channel__.serial_device.close()`
        inside try/except and otherwise simply drop our reference to the raw
        object. Does NOT disarm the motor: the user may intentionally leave the
        axis running after disconnecting."""
        try:
            self._raw.__channel__.serial_device.close()
        except Exception:  # noqa: BLE001 - no public close API; best effort only
            pass
        self._raw = None
        self._axis = None

    @property
    def raw(self):
        return self._raw
