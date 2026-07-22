"""Fixed-capacity time-series buffers over Device.feedback(). GUI-agnostic:
the UI calls sample() on a timer, then reads series() for plotting."""
from __future__ import annotations

from collections import deque

from core.device import Device

# Channels read directly from Device.feedback().
CHANNELS = ("pos", "pos_target", "pos_ref",
            "vel", "vel_target", "vel_ref",
            "iq_setpoint", "iq_measured",
            "torque_target", "torque_ref", "torque_estimate",
            "torque_output", "vel_integrator_torque",
            "fet_temp", "motor_temp", "bus_voltage", "bus_current")

# Client-side channels derived from CHANNELS each tick (no extra USB reads):
# tracking error = effective setpoint (ideal) - measured (actual). NaN if
# either input is NaN.
COMPUTED = ("pos_err", "vel_err")


class Sampler:
    def __init__(self, dev: Device, maxlen: int = 2000):
        self._dev = dev
        self.channels = CHANNELS + COMPUTED
        self._buf = {name: deque(maxlen=maxlen)
                     for name in ("t",) + CHANNELS + COMPUTED}

    def sample(self, t: float, keys=None) -> dict:
        # TODO(phase7): adaptive channel reads for high-rate capture — when
        # `keys` is a subset, read only those via a Device.feedback_subset().
        # For now feedback() is one USB round-trip regardless of `keys`.
        fb = self._dev.feedback()
        self._buf["t"].append(t)
        for name in CHANNELS:
            self._buf[name].append(fb[name])
        self._buf["pos_err"].append(fb["pos_ref"] - fb["pos"])
        self._buf["vel_err"].append(fb["vel_ref"] - fb["vel"])
        return fb

    def series(self, name: str) -> list:
        return list(self._buf[name])

    def clear(self) -> None:
        for d in self._buf.values():
            d.clear()
