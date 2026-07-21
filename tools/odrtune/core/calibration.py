"""Drives the full motor+encoder calibration sequence and polls for the result.

Usage: start(), then poll() repeatedly (e.g. on a QTimer). poll() returns one
of 'running' | 'success' | 'failed'. Because current_state briefly stays IDLE
right after the request, start() latches a 'started' flag and poll() only
evaluates completion after it has observed the axis leave IDLE."""
from __future__ import annotations

from core.device import Device, IDLE, FULL_CALIBRATION_SEQUENCE


class CalibrationRunner:
    def __init__(self, dev: Device):
        self._dev = dev
        self.running = False
        self._left_idle = False
        self.last_error = None

    def start(self) -> None:
        self.running = True
        self._left_idle = False
        self.last_error = None
        self._dev.set_requested_state(FULL_CALIBRATION_SEQUENCE)

    def poll(self) -> str:
        if not self.running:
            return "success" if self.last_error is None else "failed"
        state = self._dev.current_state()
        if state != IDLE:
            self._left_idle = True
            return "running"
        if not self._left_idle:
            # initial IDLE tick before calibration engages; procedure_result
            # may still hold a stale value from a prior run - ignore it.
            return "running"
        pr = self._dev.procedure_result()
        if pr == 0:
            self.running = False
            return "success"
        self.running = False
        self.last_error = {"procedure_result": pr, **self._dev.errors()}
        return "failed"
