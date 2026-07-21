"""Reusable live time-series plot with one or more named traces.

Typical use for a control channel is three traces on the same axes:
- **actual**  — the measured value (blue, solid)
- **target**  — the raw command you gave, e.g. input_pos (orange, dashed)
- **ideal**   — the controller's effective setpoint right now, e.g.
  controller.pos_setpoint (green, dotted) — where the motor *should* be at this
  instant after ramps / filtering / trajectory shaping.

Header: title, latest value(s), 'auto Y' and 'cursor' toggles, and a -/+
minimize button. Driven from a shared Sampler via refresh(sampler). Expose the
pyqtgraph PlotItem via `plot_item` so MainWindow can X-link all plots to one
shared time axis."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QCheckBox, QToolButton)

# pens by trace position: actual / target / ideal / (extra)
_PENS = [
    pg.mkPen("#4fc3f7", width=2),                                  # blue solid
    pg.mkPen("#ff8a65", width=1, style=Qt.PenStyle.DashLine),      # orange dashed
    pg.mkPen("#81c784", width=1, style=Qt.PenStyle.DotLine),       # green dotted
    pg.mkPen("#ba68c8", width=1, style=Qt.PenStyle.DashDotLine),   # purple
]
_CURSOR_PEN = pg.mkPen("#9e9e9e", width=1, style=Qt.PenStyle.DashLine)


class TimePlot(QWidget):
    def __init__(self, title, traces, compact=False, parent=None):
        """traces: list of (sampler_key, label). First is the primary/actual."""
        super().__init__(parent)
        self._traces = list(traces)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(1)

        # --- header ---
        self._header = QWidget()
        header = QHBoxLayout(self._header)
        header.setContentsMargins(2, 0, 2, 0)
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
        self._collapse = QToolButton()
        self._collapse.setCheckable(True)
        self._collapse.setText("–")
        self._collapse.setToolTip("Minimize graph")
        self._collapse.setAutoRaise(True)
        header.addWidget(self._collapse)
        root.addWidget(self._header)

        # --- plot ---
        self._pw = pg.PlotWidget()
        self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel("bottom", "time", units="s")
        root.addWidget(self._pw, 1)

        pi = self._pw.getPlotItem()
        multi = len(self._traces) > 1
        if multi:
            pi.addLegend(offset=(-10, 10))
        self._curves = []
        for i, (key, label) in enumerate(self._traces):
            pen = _PENS[i % len(_PENS)]
            curve = self._pw.plot(pen=pen, name=(label if multi else None))
            self._curves.append((key, label, curve))

        # --- crosshair cursor (hidden until enabled) ---
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=_CURSOR_PEN)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=_CURSOR_PEN)
        self._readout = pg.TextItem(color="#e0e0e0", anchor=(0, 1))
        for it in (self._vline, self._hline, self._readout):
            it.setVisible(False)
            pi.addItem(it, ignoreBounds=True)
        self._proxy = pg.SignalProxy(pi.scene().sigMouseMoved,
                                     rateLimit=60, slot=self._on_mouse)

        if compact:
            self._exp_min, self._exp_max = 0, 150
        else:
            self._exp_min, self._exp_max = 170, 16777215
        self.setMinimumHeight(self._exp_min)
        self.setMaximumHeight(self._exp_max)

        self._auto.toggled.connect(self._on_auto)
        self._cursor.toggled.connect(self._on_cursor)
        self._collapse.toggled.connect(self._on_collapse)
        self._on_auto(True)

    @property
    def plot_item(self):
        return self._pw.getPlotItem()

    def refresh(self, sampler) -> None:
        t = sampler.series("t")
        parts = []
        multi = len(self._curves) > 1
        for key, label, curve in self._curves:
            data = sampler.series(key)
            curve.setData(t, data)
            if data:
                parts.append(f"{label} {data[-1]:.4g}" if multi
                             else f"{data[-1]:.4g}")
        self._latest.setText("   ".join(parts))

    # --- header actions ---
    def _on_collapse(self, on: bool):
        self._pw.setVisible(not on)
        if on:
            self.setMinimumHeight(0)
            self.setMaximumHeight(self._header.sizeHint().height())
            self._collapse.setText("+")
        else:
            self.setMinimumHeight(self._exp_min)
            self.setMaximumHeight(self._exp_max)
            self._collapse.setText("–")

    def _on_auto(self, on: bool):
        vb = self._pw.getPlotItem().getViewBox()
        if on:
            vb.setAutoVisible(y=True)
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
