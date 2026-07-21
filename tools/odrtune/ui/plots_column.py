"""Persistent plots column, shown on the right of the window on every tab.

Holds the global time-window spinbox and all live graphs: two small
measured-only monitors (bus voltage, FET temperature) and the four large
setpoint+measured graphs (position, velocity, current Iq, torque). The graphs
live in a scroll area so a short window still shows them all.

Sampling and the shared time base are owned by MainWindow, which calls
refresh(sampler) each tick and X-links every plot in `plots`."""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QDoubleSpinBox, QScrollArea)

from ui.time_plot import TimePlot

# large graphs: (title, measured_key, setpoint_key)
_MAIN = [
    ("Position (turns)", "pos", "pos_setpoint"),
    ("Velocity (turns/s)", "vel", "vel_setpoint"),
    ("Current Iq (A)", "iq_measured", "iq_setpoint"),
    ("Torque (Nm)", "torque_estimate", "torque_setpoint"),
]


class PlotsColumn(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # --- global time window control ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Window:"))
        self._window = QDoubleSpinBox()
        self._window.setRange(1.0, 120.0)
        self._window.setSingleStep(1.0)
        self._window.setValue(10.0)
        self._window.setSuffix(" s")
        bar.addWidget(self._window)
        bar.addStretch(1)
        root.addLayout(bar)

        # --- scrollable stack of graphs ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)

        self._plots = []
        self.bus_plot = TimePlot("Bus voltage (V)", "bus_voltage", compact=True)
        self.fet_plot = TimePlot("FET temp (°C)", "fet_temp", compact=True)
        self._plots += [self.bus_plot, self.fet_plot]
        for title, measured, setpoint in _MAIN:
            self._plots.append(TimePlot(title, measured, setpoint_key=setpoint))
        for p in self._plots:
            col.addWidget(p)

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    @property
    def plots(self):
        return self._plots

    def window_seconds(self) -> float:
        return self._window.value()

    def refresh(self, sampler) -> None:
        for p in self._plots:
            p.refresh(sampler)
