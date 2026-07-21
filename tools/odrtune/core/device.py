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

    # --- feedback snapshot ---
    def feedback(self) -> dict:
        a = self._axis
        return {
            # pos_abs is the absolute frame the controller tracks and that
            # input_pos / set_abs_pos operate in (so "set current position" is
            # reflected here); pos_rel is only relative-to-boot.
            "pos": a.pos_vel_mapper.pos_abs,
            "pos_setpoint": a.controller.input_pos,
            "vel": a.pos_vel_mapper.vel,
            "vel_setpoint": a.controller.input_vel,
            "iq_setpoint": a.motor.foc.Iq_setpoint,
            "iq_measured": a.motor.foc.Iq_measured,
            "torque_setpoint": a.controller.torque_setpoint,
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

    # --- per-loop tuning (current / velocity / position) ---
    def get_tuning(self) -> dict:
        c = self._axis.controller.config
        m = self._axis.config.motor
        return {
            "encoder_bandwidth": self._axis.config.encoder_bandwidth,
            "pos_gain": c.pos_gain,
            "vel_gain": c.vel_gain,
            "vel_integrator_gain": c.vel_integrator_gain,
            "vel_limit": c.vel_limit,
            "vel_integrator_limit": c.vel_integrator_limit,
            "current_control_bandwidth": m.current_control_bandwidth,
            "current_soft_max": m.current_soft_max,
        }

    def set_tuning(self, **kw) -> None:
        c = self._axis.controller.config
        m = self._axis.config.motor
        if "encoder_bandwidth" in kw:
            self._axis.config.encoder_bandwidth = kw["encoder_bandwidth"]
        if "pos_gain" in kw:
            c.pos_gain = kw["pos_gain"]
        if "vel_gain" in kw:
            c.vel_gain = kw["vel_gain"]
        if "vel_integrator_gain" in kw:
            c.vel_integrator_gain = kw["vel_integrator_gain"]
        if "vel_limit" in kw:
            c.vel_limit = kw["vel_limit"]
        if "vel_integrator_limit" in kw:
            c.vel_integrator_limit = kw["vel_integrator_limit"]
        if "current_control_bandwidth" in kw:
            m.current_control_bandwidth = kw["current_control_bandwidth"]
        if "current_soft_max" in kw:
            m.current_soft_max = kw["current_soft_max"]

    # --- persistence ---
    def save(self) -> None:
        self._raw.save_configuration()

    def erase(self) -> None:
        self._raw.erase_configuration()

    def reboot(self) -> None:
        self._raw.reboot()

    @property
    def raw(self):
        return self._raw
