"""Wrapper over the odrive USB object tree. All firmware-specific attribute
paths live here so a version change touches one file. Accepts either a real
odrive device or a duck-typed fake."""
from __future__ import annotations

# AxisState ints (fw 0.6.x)
IDLE = 1
FULL_CALIBRATION_SEQUENCE = 3
CLOSED_LOOP_CONTROL = 8


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
            "pos": a.pos_vel_mapper.pos_rel,
            "vel": a.pos_vel_mapper.vel,
            "iq_setpoint": a.motor.foc.Iq_setpoint,
            "iq_measured": a.motor.foc.Iq_measured,
            "fet_temp": a.motor.fet_thermistor.temperature,
            "motor_temp": a.motor.motor_thermistor.temperature,
            "bus_voltage": self._raw.vbus_voltage,
            "bus_current": self._raw.ibus,
        }

    # --- state / setpoints ---
    def set_requested_state(self, state: int) -> None:
        self._axis.requested_state = state

    def current_state(self) -> int:
        return self._axis.current_state

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
