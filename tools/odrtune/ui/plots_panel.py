"""Plots tab: the large setpoint+measured graphs for position, velocity,
current (Iq) and torque. Sampling and the shared time base are owned by
MainWindow, which calls refresh(sampler) on each tick; these plots are
X-linked to the rest of the app so they pan/zoom together on time."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout

from ui.time_plot import TimePlot

# (title, measured_key, setpoint_key)
_SPECS = [
    ("Position (turns)", "pos", "pos_setpoint"),
    ("Velocity (turns/s)", "vel", "vel_setpoint"),
    ("Current Iq (A)", "iq_measured", "iq_setpoint"),
    ("Torque (Nm)", "torque_estimate", "torque_setpoint"),
]


class PlotsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._plots = []
        for title, measured, setpoint in _SPECS:
            p = TimePlot(title, measured, setpoint_key=setpoint)
            self._plots.append(p)
            layout.addWidget(p)

    @property
    def plots(self):
        return self._plots

    def refresh(self, sampler) -> None:
        for p in self._plots:
            p.refresh(sampler)
