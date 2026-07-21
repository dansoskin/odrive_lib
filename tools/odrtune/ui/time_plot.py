"""Reusable live time-series plot.

A header row (title, latest-value readout, 'auto Y' and 'cursor' checkboxes)
sits above a pyqtgraph plot that shows one measured trace plus an optional
setpoint trace on the same axes, driven from a shared Sampler.

- auto Y (on by default): Y auto-ranges to the data currently visible in the
  time window; uncheck to freeze/zoom Y manually.
- cursor: a crosshair that follows the mouse and reads out (time, value).

The X axis is shared across plots by X-linking their plot items (done by
MainWindow), so all plots pan/zoom together on time. Expose the underlying
pyqtgraph PlotItem via `plot_item` for that linking."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox

_MEASURED_PEN = pg.mkPen("#4fc3f7", width=2)                       # blue
_SETPOINT_PEN = pg.mkPen("#ff8a65", width=1, style=Qt.PenStyle.DashLine)  # orange dashed
_CURSOR_PEN = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)


class TimePlot(QWidget):
    def __init__(self, title, measured_key, setpoint_key=None,
                 compact=False, parent=None):
        super().__init__(parent)
        self._measured_key = measured_key
        self._setpoint_key = setpoint_key

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(1)

        # --- header ---
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>{title}</b>"))
        header.addStretch(1)
        self._latest = QLabel("")
        header.addWidget(self._latest)
        header.addSpacing(10)
        self._auto = QCheckBox("auto Y")
        self._auto.setChecked(True)
        self._cursor = QCheckBox("cursor")
        header.addWidget(self._auto)
        header.addWidget(self._cursor)
        root.addLayout(header)

        # --- plot ---
        self._pw = pg.PlotWidget()
        self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel("bottom", "time", units="s")
        root.addWidget(self._pw, 1)
        self.setMaximumHeight(150) if compact else self.setMinimumHeight(170)

        pi = self._pw.getPlotItem()
        if setpoint_key is not None:
            pi.addLegend(offset=(-10, 10))
        self._measured = self._pw.plot(pen=_MEASURED_PEN, name="measured")
        self._setpoint = None
        if setpoint_key is not None:
            self._setpoint = self._pw.plot(pen=_SETPOINT_PEN, name="setpoint")

        # --- crosshair cursor (hidden until enabled) ---
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=_CURSOR_PEN)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=_CURSOR_PEN)
        self._readout = pg.TextItem(color="#e0e0e0", anchor=(0, 1))
        for it in (self._vline, self._hline, self._readout):
            it.setVisible(False)
            pi.addItem(it, ignoreBounds=True)
        self._proxy = pg.SignalProxy(pi.scene().sigMouseMoved,
                                     rateLimit=60, slot=self._on_mouse)

        self._auto.toggled.connect(self._on_auto)
        self._cursor.toggled.connect(self._on_cursor)
        self._on_auto(True)

    @property
    def plot_item(self):
        return self._pw.getPlotItem()

    def refresh(self, sampler) -> None:
        t = sampler.series("t")
        meas = sampler.series(self._measured_key)
        self._measured.setData(t, meas)
        last_m = meas[-1] if meas else None
        if self._setpoint is not None:
            setp = sampler.series(self._setpoint_key)
            self._setpoint.setData(t, setp)
            last_s = setp[-1] if setp else None
            self._latest.setText(
                "" if last_m is None
                else f"meas {last_m:.4g}  |  set {last_s:.4g}")
        else:
            self._latest.setText("" if last_m is None else f"{last_m:.4g}")

    # --- header actions ---
    def _on_auto(self, on: bool):
        vb = self._pw.getPlotItem().getViewBox()
        if on:
            vb.setAutoVisible(y=True)   # scale Y to data in the visible X window
            vb.enableAutoRange(y=True)
        else:
            vb.enableAutoRange(y=False)

    def _on_cursor(self, on: bool):
        for it in (self._vline, self._hline, self._readout):
            it.setVisible(on)

    def _on_mouse(self, evt):
        if not self._cursor.isChecked():
            return
        pos = evt[0]
        pi = self._pw.getPlotItem()
        if not pi.sceneBoundingRect().contains(pos):
            return
        mp = pi.getViewBox().mapSceneToView(pos)
        x, y = mp.x(), mp.y()
        self._vline.setPos(x)
        self._hline.setPos(y)
        self._readout.setPos(x, y)
        self._readout.setText(f"t={x:.3f} s\ny={y:.4g}")
