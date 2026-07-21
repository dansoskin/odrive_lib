"""Persistent top panel, always visible above the tabs.

Holds the axis state/mode controls (requested_state + control_mode dropdowns,
live current_state readout), the global time-window spinbox, and two small
measured-only monitor graphs (bus voltage, FET temperature)."""
from __future__ import annotations

from PySide6.QtWidgets import (QWidget, QHBoxLayout, QFormLayout, QComboBox,
                               QLabel, QDoubleSpinBox)

from core import device as device_mod
from ui.time_plot import TimePlot


class TopPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        root = QHBoxLayout(self)

        # --- state / mode controls + window ---
        form = QFormLayout()
        self._req = QComboBox()
        for name, value in device_mod.AXIS_STATES.items():
            self._req.addItem(name, value)
        self._cur = QLabel("—")
        self._mode = QComboBox()
        for name, value in device_mod.CONTROL_MODES.items():
            self._mode.addItem(name, value)
        self._window = QDoubleSpinBox()
        self._window.setRange(1.0, 120.0)
        self._window.setSingleStep(1.0)
        self._window.setValue(10.0)
        self._window.setSuffix(" s")

        form.addRow("Requested state:", self._req)
        form.addRow("Current state:", self._cur)
        form.addRow("Control mode:", self._mode)
        form.addRow("Window:", self._window)
        self._set_controls_enabled(False)
        root.addLayout(form)

        # --- small monitor graphs (measured-only) ---
        self.bus_plot = TimePlot("Bus voltage (V)", "bus_voltage", compact=True)
        self.fet_plot = TimePlot("FET temp (°C)", "fet_temp", compact=True)
        for p in (self.bus_plot, self.fet_plot):
            p.setMinimumWidth(240)
            root.addWidget(p, 1)

        self._req.activated.connect(self._on_req)
        self._mode.activated.connect(self._on_mode)

    # --- exposed to MainWindow ---
    @property
    def plots(self):
        return [self.bus_plot, self.fet_plot]

    def window_seconds(self) -> float:
        return self._window.value()

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        self._sync_combo(self._req, dev.get_requested_state())
        self._sync_combo(self._mode, dev.get_control_mode())
        self._set_controls_enabled(True)

    def refresh(self, sampler) -> None:
        self.bus_plot.refresh(sampler)
        self.fet_plot.refresh(sampler)
        if self._dev is not None:
            try:
                self._cur.setText(self._state_name(self._dev.current_state()))
            except Exception:  # noqa: BLE001 - USB hiccup shouldn't crash the UI
                pass

    # --- helpers ---
    def _set_controls_enabled(self, on: bool) -> None:
        self._req.setEnabled(on)
        self._mode.setEnabled(on)

    def _on_req(self):
        if self._dev is None:
            return
        try:
            self._dev.set_requested_state(self._req.currentData())
        except Exception as exc:  # noqa: BLE001
            self._cur.setText(f"error: {exc}")

    def _on_mode(self):
        if self._dev is None:
            return
        try:
            self._dev.set_control_mode(self._mode.currentData())
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _sync_combo(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    @staticmethod
    def _state_name(value: int) -> str:
        for name, v in device_mod.AXIS_STATES.items():
            if v == value:
                return name
        return str(value)
