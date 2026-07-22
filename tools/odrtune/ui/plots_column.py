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

# large graphs: (title, [(sampler_key, label[, visible_default]), ...])
# actual / target / ideal / output / integrator / error. Traces marked False
# start hidden (their checkbox unchecked). Titles name the motor frame.
_MAIN = [
    ("Position (motor turns)", [("pos", "actual"), ("pos_target", "target"),
                                ("pos_ref", "ideal"), ("pos_err", "error", False)]),
    ("Velocity (motor turns/s)", [("vel", "actual"), ("vel_target", "target"),
                                  ("vel_ref", "ideal"), ("vel_err", "error", False)]),
    ("Current Iq (A)", [("iq_measured", "actual"), ("iq_setpoint", "command")]),
    ("Torque (Nm, motor)", [("torque_estimate", "actual"), ("torque_target", "target"),
                            ("torque_ref", "ideal"), ("torque_output", "output", True),
                            ("vel_integrator_torque", "integrator", False)]),
]

# Channels always sampled regardless of which plots are collapsed: the top-bar
# bus/FET monitors and the inputs to the client-side error channels.
_BASE_KEYS = ("bus_voltage", "fet_temp", "pos", "pos_ref", "vel", "vel_ref")


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

    def needed_keys(self) -> set:
        """Union of the sampler keys of the non-collapsed plots plus the base
        keys (top-bar monitors + error-channel inputs). A collapsed plot's
        exclusive channels aren't needed for display."""
        keys = set(_BASE_KEYS)
        for p in self._plots:
            if not p.collapsed:
                keys.update(p.keys)
        return keys

    def refresh(self, sampler) -> None:
        # Skip collapsed plots — a cheap CPU win, since a minimized graph has no
        # visible curves to redraw.
        for p in self._plots:
            if not p.collapsed:
                p.refresh(sampler)
