"""Live scrolling plots of pos/vel/Iq/temperature/bus voltage using pyqtgraph.
Polls a Sampler on a QTimer once a Device is set."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout

from core.sampler import Sampler

# (channel, label) groups plotted on stacked axes
_PLOTS = [
    ("pos", "Position (turns)"),
    ("vel", "Velocity (turns/s)"),
    ("iq_measured", "Iq measured (A)"),
    ("fet_temp", "FET temp (C)"),
    ("bus_voltage", "Bus voltage (V)"),
]


class PlotsPanel(QWidget):
    def __init__(self, parent=None, interval_ms: int = 50):
        super().__init__(parent)
        self._sampler = None
        self._t0 = 0.0
        layout = QVBoxLayout(self)
        self._curves = {}
        win = pg.GraphicsLayoutWidget()
        layout.addWidget(win)
        for i, (chan, label) in enumerate(_PLOTS):
            plot = win.addPlot(row=i, col=0, title=label)
            plot.showGrid(x=True, y=True)
            self._curves[chan] = plot.plot(pen=pg.mkPen(width=2))
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def set_device(self, dev):
        self._sampler = Sampler(dev, maxlen=2000)
        self._t0 = time.monotonic()
        self._timer.start()

    def _tick(self):
        if self._sampler is None:
            return
        try:
            self._sampler.sample(t=time.monotonic() - self._t0)
        except Exception:  # noqa: BLE001 - a USB hiccup shouldn't kill the UI
            return
        ts = self._sampler.series("t")
        for chan, curve in self._curves.items():
            curve.setData(ts, self._sampler.series(chan))
