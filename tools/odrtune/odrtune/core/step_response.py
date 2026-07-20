"""Commands a setpoint step and records the response channel over time, for
tuning by eye. GUI-agnostic: begin() then record() on a timer, then data()."""
from __future__ import annotations

from odrtune.core.device import Device

_COMMAND = {
    "pos": lambda dev, v: dev.set_input_pos(v),
    "vel": lambda dev, v: dev.set_input_vel(v),
    "torque": lambda dev, v: dev.set_input_torque(v),
}


class StepResponse:
    def __init__(self, dev: Device, channel: str = "pos"):
        if channel not in _COMMAND:
            raise ValueError(f"unknown channel: {channel}")
        self._dev = dev
        self.channel = channel
        self.target = 0.0
        self._t: list[float] = []
        self._y: list[float] = []

    def begin(self, target: float) -> None:
        self.target = target
        self._t.clear()
        self._y.clear()
        _COMMAND[self.channel](self._dev, target)

    def record(self, t: float) -> None:
        fb = self._dev.feedback()
        # response channel: pos->pos, vel->vel, torque->iq_measured proxy
        key = {"pos": "pos", "vel": "vel", "torque": "iq_measured"}[self.channel]
        self._t.append(t)
        self._y.append(fb[key])

    def data(self) -> tuple[list, list]:
        return list(self._t), list(self._y)
