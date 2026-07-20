"""Runs full calibration via core.calibration.CalibrationRunner and shows the
result. Polls on a QTimer."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel)

from odrtune.core.calibration import CalibrationRunner


class CalibrationPanel(QWidget):
    def __init__(self, parent=None, interval_ms: int = 200):
        super().__init__(parent)
        self._dev = None
        self._runner = None
        layout = QVBoxLayout(self)
        self._btn = QPushButton("Run full calibration")
        self._btn.setEnabled(False)
        self._status = QLabel("Connect a device to calibrate.")
        layout.addWidget(self._btn)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self._btn.clicked.connect(self._start)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def set_device(self, dev):
        self._dev = dev
        self._btn.setEnabled(True)
        self._status.setText("Ready.")

    def _start(self):
        if self._dev is None:
            return
        self._runner = CalibrationRunner(self._dev)
        self._runner.start()
        self._status.setText("Calibrating…")
        self._btn.setEnabled(False)
        self._timer.start()

    def _poll(self):
        if self._runner is None:
            return
        result = self._runner.poll()
        if result == "running":
            return
        self._timer.stop()
        self._btn.setEnabled(True)
        if result == "success":
            self._status.setText("Calibration succeeded.")
        else:
            self._status.setText(f"Calibration failed: {self._runner.last_error}")
