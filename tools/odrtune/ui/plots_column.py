"""Persistent plots column, shown on the right of the window on every tab.

Holds the global time-window spinbox and the four large setpoint+measured
graphs (position, velocity, current Iq, torque). The graphs live in a scroll
area so a short window still shows them all. (The small bus-voltage and FET
monitors live in the top bar next to the connect controls.)

Sampling and the shared time base are owned by MainWindow, which calls
refresh(sampler) each tick and X-links every plot in `plots`."""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QDoubleSpinBox, QScrollArea, QCheckBox)

from ui.time_plot import TimePlot

# large graphs: (title, [(sampler_key, label), ...])  actual / target / ideal
_MAIN = [
    ("Position (turns)", [("pos", "actual"), ("pos_target", "target"),
                          ("pos_ref", "ideal")]),
    ("Velocity (turns/s)", [("vel", "actual"), ("vel_target", "target"),
                            ("vel_ref", "ideal")]),
    ("Current Iq (A)", [("iq_measured", "actual"), ("iq_setpoint", "command")]),
    ("Torque (Nm)", [("torque_estimate", "actual"), ("torque_target", "target"),
                     ("torque_ref", "ideal")]),
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
        self._pause = QCheckBox("Pause")
        self._pause.setToolTip("Freeze the graphs to inspect them "
                               "(sampling stops; pan/zoom/cursor still work)")
        bar.addWidget(self._pause)
        bar.addStretch(1)
        root.addLayout(bar)

        # --- scrollable stack of graphs ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)

        self._plots = []
        for title, traces in _MAIN:
            self._plots.append(TimePlot(title, traces))
        for p in self._plots:
            col.addWidget(p)

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    @property
    def plots(self):
        return self._plots

    def window_seconds(self) -> float:
        return self._window.value()

    def paused(self) -> bool:
        return self._pause.isChecked()

    def refresh(self, sampler) -> None:
        for p in self._plots:
            p.refresh(sampler)
