"""Reusable live time-series plot: one measured trace plus an optional
setpoint trace on the same axes, both driven from a shared Sampler.

GUI-agnostic beyond pyqtgraph: call refresh(sampler) on a timer. The X axis is
shared across plots by X-linking their PlotItems (done by MainWindow), so all
plots pan/zoom together on time."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt

_MEASURED_PEN = pg.mkPen("#4fc3f7", width=2)                       # blue
_SETPOINT_PEN = pg.mkPen("#ff8a65", width=1, style=Qt.PenStyle.DashLine)  # orange dashed


class TimePlot(pg.PlotWidget):
    def __init__(self, title, measured_key, setpoint_key=None,
                 compact=False, parent=None):
        super().__init__(parent=parent)
        self._measured_key = measured_key
        self._setpoint_key = setpoint_key

        self.setTitle(title)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("bottom", "time", units="s")

        if setpoint_key is not None:
            self.getPlotItem().addLegend(offset=(-10, 10))
        self._measured = self.plot(pen=_MEASURED_PEN, name="measured")
        self._setpoint = None
        if setpoint_key is not None:
            self._setpoint = self.plot(pen=_SETPOINT_PEN, name="setpoint")

        if compact:
            self.setMaximumHeight(130)
        else:
            self.setMinimumHeight(140)

    def refresh(self, sampler) -> None:
        t = sampler.series("t")
        self._measured.setData(t, sampler.series(self._measured_key))
        if self._setpoint is not None:
            self._setpoint.setData(t, sampler.series(self._setpoint_key))
