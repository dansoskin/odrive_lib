"""Wrapper over the odrive USB object tree. All firmware-specific attribute
paths live here so a version change touches one file. Accepts either a real
odrive device or a duck-typed fake."""
from __future__ import annotations

import logging
import math

_log = logging.getLogger(__name__)

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
    """Human-readable name for an AxisState int.

    Prefers our friendly names for the states we map in AXIS_STATES; for any
    other value, decode via the installed odrive package's authoritative enum
    (guarded) so uncommon states still show a name instead of a bare int."""
    for name, v in AXIS_STATES.items():
        if v == value:
            return name
    try:
        from odrive.enums import AxisState as _AS
        return _AS(value).name
    except Exception:  # noqa: BLE001 - enum missing or value unknown
        return str(value)


# Axis.procedure_result decode. Prefer the installed odrive package's
# authoritative enum; fall back to a static table for this firmware line.
try:
    from odrive.enums import ProcedureResult as _PR
    PROCEDURE_RESULTS = {int(v): v.name for v in _PR}
except Exception:  # noqa: BLE001
    PROCEDURE_RESULTS = {0: "SUCCESS", 1: "BUSY", 2: "CANCELLED", 3: "DISARMED",
        4: "NO_RESPONSE", 5: "POLE_PAIR_CPR_MISMATCH", 6: "PHASE_RESISTANCE_OUT_OF_RANGE",
        7: "PHASE_INDUCTANCE_OUT_OF_RANGE", 8: "UNBALANCED_PHASES", 9: "INVALID_MOTOR_TYPE",
        10: "ILLEGAL_HALL_STATE", 11: "TIMEOUT", 12: "HOMING_WITHOUT_ENDSTOP",
        13: "INVALID_STATE", 14: "NOT_CALIBRATED", 15: "NOT_CONVERGING",
        16: "REQUESTED_CURRENT_TOO_HIGH"}


def procedure_result_name(value) -> str:
    """Human-readable name for an Axis.procedure_result int (falls back to
    str(value) for values not in the decode table)."""
    try:
        return PROCEDURE_RESULTS[int(value)]
    except Exception:  # noqa: BLE001 - unknown / undecodable value
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


def _getp(root, path):
    """Walk a dotted attribute path from ``root``, returning NaN if any hop is
    missing. Guards a whole feedback channel (including a missing intermediate
    object such as ``motor_thermistor``) so one absent path just shows a gap
    instead of killing the entire sampling loop."""
    obj = root
    try:
        for part in path.split("."):
            obj = getattr(obj, part)
        return obj
    except Exception:  # noqa: BLE001
        return float("nan")


def _getp_first(root, *paths):
    """Return the first finite value among several dotted paths (guarded).
    Used for position feedback: prefer the controller's estimate, fall back to
    the absolute frame, then the boot-relative frame — so we never plot NaN
    just because e.g. pos_abs has no valid absolute reference yet."""
    for path in paths:
        v = _getp(root, path)
        try:
            if not math.isnan(float(v)):
                return v
        except (TypeError, ValueError):
            if v is not None:
                return v
    return float("nan")


def values_match(requested, actual) -> bool:
    """True if a written value read back as expected.

    Bools compare by equality; floats use relative tolerance 1e-4 (or absolute
    1e-6), with inf==inf and nan==nan. Used for write read-back verification."""
    if isinstance(requested, bool) or isinstance(actual, bool):
        return bool(requested) == bool(actual)
    try:
        r = float(requested)
        a = float(actual)
    except (TypeError, ValueError):
        return requested == actual
    if math.isnan(r) or math.isnan(a):
        return math.isnan(r) and math.isnan(a)
    if math.isinf(r) or math.isinf(a):
        return r == a
    return abs(r - a) <= max(1e-4 * abs(r), 1e-6)


def _fmt(x) -> str:
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float):
        return f"{x:g}"
    return str(x)


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
        self._caps = None  # capability map, probed once on first request

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
        # For each channel: measured (actual), target (raw command you gave),
        # and ref (the controller's effective setpoint = where the motor should
        # be right now, after ramp/filter/trajectory). "pos" prefers the
        # controller's own estimate (same frame as the setpoints), then the
        # absolute frame, then the boot-relative frame — pos_abs is NaN until
        # the axis has a valid absolute reference (absolute encoder / homing),
        # so a plain incremental setup would otherwise plot NaN. Every path is
        # guarded (_getp) so one attribute a given firmware/config lacks becomes
        # a NaN gap instead of killing the whole sampling loop.
        return {
            "pos": _getp_first(a, "pos_estimate", "pos_vel_mapper.pos_abs",
                               "pos_vel_mapper.pos_rel"),
            "pos_target": _getp(a, "controller.input_pos"),
            "pos_ref": _getp(a, "controller.pos_setpoint"),
            "vel": _getp(a, "pos_vel_mapper.vel"),
            "vel_target": _getp(a, "controller.input_vel"),
            "vel_ref": _getp(a, "controller.vel_setpoint"),
            "iq_setpoint": _getp(a, "motor.foc.Iq_setpoint"),
            "iq_measured": _getp(a, "motor.foc.Iq_measured"),
            "torque_target": _getp(a, "controller.input_torque"),
            "torque_ref": _getp(a, "controller.torque_setpoint"),
            "torque_estimate": _getp(a, "motor.torque_estimate"),
            "torque_output": _getp(a, "controller.effective_torque_setpoint"),
            "vel_integrator_torque": _getp(a, "controller.vel_integrator_torque"),
            "fet_temp": _getp(a, "motor.fet_thermistor.temperature"),
            "motor_temp": _getp(a, "motor.motor_thermistor.temperature"),
            "bus_voltage": _getp(self._raw, "vbus_voltage"),
            "bus_current": _getp(self._raw, "ibus"),
        }

    def diagnostics(self) -> dict:
        """Live read-only limiting/diagnostic values (guarded). NaN where the
        connected firmware doesn't expose the attribute."""
        a = self._axis
        return {
            "effective_current_lim": _get(a.motor, "effective_current_lim"),
            "effective_torque_setpoint": _get(a.controller,
                                              "effective_torque_setpoint"),
            "vel_integrator_torque": _get(a.controller, "vel_integrator_torque"),
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

    def clear_errors(self) -> None:
        """Clear all device errors (fw 0.6.x device-level clear_errors();
        also re-arms the brake resistor). The axis stays disarmed."""
        self._raw.clear_errors()

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
            # motor-model validity
            "phase_resistance_valid": (m, "phase_resistance_valid"),
            "phase_inductance_valid": (m, "phase_inductance_valid"),
            "ff_pm_flux_linkage_valid": (m, "ff_pm_flux_linkage_valid"),
            "motor_model_l_dq_valid": (m, "motor_model_l_dq_valid"),
            # velocity & overspeed behavior
            "enable_vel_limit": (c, "enable_vel_limit"),
            "enable_torque_mode_vel_limit": (c, "enable_torque_mode_vel_limit"),
            "vel_limit_tolerance": (c, "vel_limit_tolerance"),
            "enable_overspeed_error": (c, "enable_overspeed_error"),
            # torque & bus limits (axis-level config)
            "torque_soft_min": (a.config, "torque_soft_min"),
            "torque_soft_max": (a.config, "torque_soft_max"),
            "I_bus_soft_min": (a.config, "I_bus_soft_min"),
            "I_bus_soft_max": (a.config, "I_bus_soft_max"),
            "P_bus_soft_min": (a.config, "P_bus_soft_min"),
            "P_bus_soft_max": (a.config, "P_bus_soft_max"),
            # report filtering
            "I_measured_report_filter_k": (a.motor.foc, "I_measured_report_filter_k"),
            "power_torque_report_filter_bandwidth": (m, "power_torque_report_filter_bandwidth"),
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

    def set_tuning(self, **kw) -> dict:
        """Attempt each write, read the attribute back, and report per key.

        Returns ``{key: (ok, applied_or_msg)}``: ``ok=True`` with the read-back
        value when it matches the request (per ``values_match``); ``ok=False``
        with a short message when the parameter is unknown, the write raised,
        the read-back raised, or the read-back value differs. Failures are
        logged; nothing is silently swallowed."""
        targets = self._tuning_targets()
        results: dict = {}
        for key, value in kw.items():
            if key not in targets:
                results[key] = (False, "unknown parameter")
                _log.warning("set_tuning: unknown parameter %s", key)
                continue
            obj, attr = targets[key]
            try:
                setattr(obj, attr, value)
            except Exception as e:  # noqa: BLE001
                results[key] = (False, f"write error: {e}")
                _log.warning("set_tuning: write %s failed: %s", key, e)
                continue
            try:
                actual = getattr(obj, attr)
            except Exception as e:  # noqa: BLE001
                results[key] = (False, f"readback error: {e}")
                _log.warning("set_tuning: readback %s failed: %s", key, e)
                continue
            if values_match(value, actual):
                results[key] = (True, actual)
            else:
                msg = f"readback {_fmt(actual)} != {_fmt(value)}"
                results[key] = (False, msg)
                _log.warning("set_tuning: %s %s", key, msg)
        return results

    def capabilities(self) -> dict:
        """Map every tuning/motion/diagnostic key to whether this firmware
        exposes it. Probed once and cached for the life of the connection
        (a Device is per-connection, so the map never needs invalidating).

        A tuning key is capable when it appears in ``get_tuning()`` (absent
        attributes are omitted there); motion and diagnostic keys are capable
        when their guarded read returns a non-NaN value."""
        if self._caps is not None:
            return self._caps
        caps: dict = {}
        present = self.get_tuning()
        for key in self._tuning_targets():
            caps[key] = key in present
        try:
            for key, val in self.get_motion_config().items():
                caps[key] = not (isinstance(val, float) and math.isnan(val))
        except Exception:  # noqa: BLE001
            pass
        for key, val in self.diagnostics().items():
            caps[key] = not (isinstance(val, float) and math.isnan(val))
        self._caps = caps
        return caps

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

        ``odrive.find_any()`` returns a ``SyncObject`` whose ``._dev`` is a
        ``RuntimeDevice`` and whose ``._loop`` is the event loop the device
        manager runs on (usually a background thread). We release through the
        real device-manager APIs, most specific first:

        1. ``DeviceManager.release_connection(runtime_device)`` -- decrements
           the connection ref count and, at zero, disconnects and drops the
           libodrive device (frees the USB handle). Run on the manager's loop
           for thread safety.
        2. ``close_device_manager()`` -- broader fallback that tears the whole
           manager (and its background thread) down.

        Each step is guarded; failures are logged at debug level and the next
        step is tried. Does NOT disarm the motor: the user may intentionally
        leave the axis running after disconnecting."""
        raw = self._raw
        self._raw = None
        self._axis = None
        if raw is None:
            return

        runtime = getattr(raw, "_dev", None)
        loop = getattr(raw, "_loop", None)
        released = False

        # Only touch the device manager for a genuine find_any() SyncObject
        # (has both ._dev and ._loop); a duck-typed fake is just dropped.
        if runtime is not None and loop is not None:
            try:
                import asyncio
                from odrive.device_manager import get_device_manager
                dm = get_device_manager()

                async def _release():
                    dm.release_connection(runtime)

                asyncio.run_coroutine_threadsafe(_release(), loop).result(timeout=5)
                released = True
                _log.info("disconnect: released via "
                          "DeviceManager.release_connection()")
            except Exception as e:  # noqa: BLE001 - try broader release next
                _log.debug("disconnect: release_connection failed: %s", e)

            if not released:
                try:
                    from odrive.device_manager import close_device_manager
                    close_device_manager()
                    released = True
                    _log.info("disconnect: released via close_device_manager()")
                except Exception as e:  # noqa: BLE001
                    _log.debug("disconnect: close_device_manager failed: %s", e)

        if not released:
            _log.debug("disconnect: no device-manager release path taken; "
                       "dropped raw reference only")

    @property
    def raw(self):
        return self._raw
