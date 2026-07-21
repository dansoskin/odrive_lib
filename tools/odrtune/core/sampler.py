"""Fixed-capacity time-series buffers over Device.feedback(). GUI-agnostic:
the UI calls sample() on a timer, then reads series() for plotting."""
from __future__ import annotations

from collections import deque

from core.device import Device

CHANNELS = ("pos", "pos_setpoint", "vel", "vel_setpoint",
            "iq_setpoint", "iq_measured", "torque_setpoint", "torque_estimate",
            "fet_temp", "motor_temp", "bus_voltage", "bus_current")


class Sampler:
    def __init__(self, dev: Device, maxlen: int = 2000):
        self._dev = dev
        self.channels = CHANNELS
        self._buf = {name: deque(maxlen=maxlen) for name in ("t",) + CHANNELS}

    def sample(self, t: float) -> dict:
        fb = self._dev.feedback()
        self._buf["t"].append(t)
        for name in CHANNELS:
            self._buf[name].append(fb[name])
        return fb

    def series(self, name: str) -> list:
        return list(self._buf[name])

    def clear(self) -> None:
        for d in self._buf.values():
            d.clear()
