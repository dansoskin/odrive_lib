"""Capture tab: record signals at the native 8 kHz control-loop rate.

The live graphs only reach ~20 Hz, too coarse for current-loop tuning. This tab
drives the ODrive's onboard oscilloscope (fw 0.6.12+) to record a chosen set of
properties into an on-chip buffer at 8 kHz, then downloads and plots the window.

Pick a preset (or type any comma-separated property paths), choose where in the
window the trigger sits, optionally apply a torque/velocity step during the
capture, then hit Capture. The result is drawn on its own millisecond time base
(trigger at 0) and can be exported to CSV. Capturing needs the USB bandwidth, so
the main window pauses live sampling while a capture runs."""
from __future__ import annotations

import csv

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QPushButton, QComboBox,
                               QDoubleSpinBox, QLineEdit, QCheckBox, QFileDialog)
import pyqtgraph as pg

from core import device as device_mod
from core import capture as capture_mod
from ui.time_plot import _PENS

_TRIGGER_TIP = (
    "Where the trigger sits within the capture window (0..1).\n"
    "0.0 = window starts at the trigger (all post-trigger);\n"
    "0.5 = half before / half after the trigger (default);\n"
    "1.0 = window ends at the trigger (all pre-trigger).\n"
    "The recording also auto-triggers if the axis enters IDLE (e.g. on an "
    "error), so you can capture the run-up to a fault.")

_STIM_TIP = ("Apply a step command during the capture so you can see the loop "
             "response. The step is sent just before the trigger.")

# (label, channel key, unit suffix) for the optional stimulus step.
_STIM_CHANNELS = [
    ("Torque step", "torque", " Nm"),
    ("Velocity step", "vel", " turns/s"),
]
_STIM_MODE = {
    "torque": device_mod.CONTROL_MODE_TORQUE,
    "vel": device_mod.CONTROL_MODE_VELOCITY,
}
_PASSTHROUGH = 1


class CapturePanel(QWidget):
    capture_started = Signal()
    capture_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        self._job = None
        self._result = None          # last successful capture dict
        self._curves = []            # (prop, curve)

        root = QVBoxLayout(self)

        # --- availability banner ---
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        root.addWidget(self._banner)

        # --- capture controls ---
        ctrl = QGroupBox("Capture")
        form = QFormLayout(ctrl)
        self._preset = QComboBox()
        for name, _props in capture_mod.PRESETS:
            self._preset.addItem(name)
        self._props = QLineEdit()
        self._props.setToolTip(
            "Comma-separated property paths to capture. Filled from the preset; "
            "edit to capture any paths you like.")
        self._trigger = QDoubleSpinBox()
        self._trigger.setRange(0.0, 1.0)
        self._trigger.setSingleStep(0.1)
        self._trigger.setDecimals(2)
        self._trigger.setValue(0.5)
        self._trigger.setToolTip(_TRIGGER_TIP)
        self._timeout = QDoubleSpinBox()
        self._timeout.setRange(0.1, 60.0)
        self._timeout.setDecimals(1)
        self._timeout.setValue(5.0)
        self._timeout.setSuffix(" s")
        self._timeout.setToolTip(
            "Maximum time to wait for the trigger and recording to complete.")
        form.addRow("Preset:", self._preset)
        form.addRow("Properties:", self._props)
        form.addRow("Trigger point:", self._trigger)
        form.addRow("Timeout:", self._timeout)
        root.addWidget(ctrl)

        # --- optional stimulus ---
        self._stim_group = QGroupBox("Apply step during capture")
        self._stim_group.setCheckable(True)
        self._stim_group.setChecked(False)
        self._stim_group.setToolTip(_STIM_TIP)
        sform = QFormLayout(self._stim_group)
        self._stim_chan = QComboBox()
        for label, key, _suffix in _STIM_CHANNELS:
            self._stim_chan.addItem(label, key)
        self._stim_amp = QDoubleSpinBox()
        self._stim_amp.setRange(-100000.0, 100000.0)
        self._stim_amp.setDecimals(3)
        self._stim_amp.setValue(0.5)
        self._stim_amp.setSuffix(" Nm")
        warn = QLabel("The motor will move. Ensure it is free to rotate.")
        warn.setStyleSheet("color: red; font-weight: bold;")
        warn.setWordWrap(True)
        sform.addRow("Channel:", self._stim_chan)
        sform.addRow("Amplitude:", self._stim_amp)
        sform.addRow(warn)
        root.addWidget(self._stim_group)

        # --- capture button + status ---
        self._capture_btn = QPushButton("Capture")
        root.addWidget(self._capture_btn)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        # --- result header + plot ---
        self._plot_header = QLabel("")
        root.addWidget(self._plot_header)
        self._pw = pg.PlotWidget()
        self._pw.showGrid(x=True, y=True, alpha=0.3)
        self._pw.setLabel("bottom", "time", units="ms")
        self._pw.getPlotItem().addLegend(offset=(-10, 10))
        root.addWidget(self._pw, 1)

        # --- export ---
        self._export_btn = QPushButton("Export CSV…")
        self._export_btn.setEnabled(False)
        root.addWidget(self._export_btn)

        # poll the running job's done flag
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._check_job)

        self._preset.currentIndexChanged.connect(self._on_preset)
        self._stim_chan.currentIndexChanged.connect(self._on_stim_chan)
        self._capture_btn.clicked.connect(self._start_capture)
        self._export_btn.clicked.connect(self._export_csv)

        self._on_preset(0)
        self._refresh_availability()

    # --- device lifecycle ---
    def set_device(self, dev):
        self._dev = dev
        self._refresh_availability()

    def _refresh_availability(self):
        ok, reason = capture_mod.availability(self._dev)
        self._available = ok
        if self._dev is None:
            self._banner.setText("Connect a device to capture.")
            self._banner.setStyleSheet("color: gray;")
        elif ok:
            self._banner.setText(
                "Native 8 kHz onboard-oscilloscope capture available.")
            self._banner.setStyleSheet("color: green;")
        else:
            self._banner.setText(f"Capture unavailable: {reason}")
            self._banner.setStyleSheet("color: red;")
        self._set_controls_enabled(ok)

    def _set_controls_enabled(self, on: bool):
        for w in (self._preset, self._props, self._trigger, self._timeout,
                  self._stim_group, self._capture_btn):
            w.setEnabled(on)
        # export stays enabled only if there's a result to export
        self._export_btn.setEnabled(on and self._result is not None)

    # --- preset / stimulus wiring ---
    def _on_preset(self, idx: int):
        if 0 <= idx < len(capture_mod.PRESETS):
            _name, props = capture_mod.PRESETS[idx]
            self._props.setText(", ".join(props))

    def _on_stim_chan(self, _idx: int):
        key = self._stim_chan.currentData()
        for _label, k, suffix in _STIM_CHANNELS:
            if k == key:
                self._stim_amp.setSuffix(suffix)
                return

    def _parse_props(self) -> list[str]:
        return [p.strip() for p in self._props.text().split(",") if p.strip()]

    # --- capture flow ---
    def _start_capture(self):
        if self._dev is None or not self._available:
            return
        props = self._parse_props()
        if not props:
            self._status.setText("No properties specified.")
            self._status.setStyleSheet("color: red;")
            return

        stimulus, finalize = (None, None)
        if self._stim_group.isChecked():
            stimulus, finalize = self._build_stimulus()

        self._status.setText("Capturing…")
        self._status.setStyleSheet("")
        self._capture_btn.setEnabled(False)
        self.capture_started.emit()

        self._job = capture_mod.CaptureJob(
            self._dev, props, self._trigger.value(), self._timeout.value(),
            stimulus=stimulus, finalize=finalize)
        self._job.run_in_thread()
        self._poll.start()

    def _check_job(self):
        job = self._job
        if job is None or not job.done:
            return
        self._poll.stop()
        self._job = None
        self._capture_btn.setEnabled(self._available)
        self.capture_finished.emit()
        if job.error is not None:
            self._status.setText(f"Capture failed: {job.error}")
            self._status.setStyleSheet("color: red;")
            return
        self._result = job.result
        self._status.setText("")
        self._plot_result(job.result)
        self._export_btn.setEnabled(True)

    def _plot_result(self, result: dict):
        pi = self._pw.getPlotItem()
        # rebuild legend + curves
        pi.clear()
        legend = pi.legend
        if legend is not None:
            legend.clear()
        self._curves = []
        t = result.get("t", [])
        t_ms = [x * 1000.0 for x in t]
        i = 0
        for prop, series in result.items():
            if prop == "t":
                continue
            pen = _PENS[i % len(_PENS)]
            curve = self._pw.plot(t_ms, series, pen=pen, name=prop)
            self._curves.append((prop, curve))
            i += 1
        n = len(t)
        window_ms = (n / capture_mod.SAMPLE_RATE_HZ) * 1000.0
        self._plot_header.setText(
            f"captured {n} samples @ {capture_mod.SAMPLE_RATE_HZ} Hz "
            f"(window {window_ms:.1f} ms)")

    def _export_csv(self):
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export capture CSV", "capture.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            keys = ["t"] + [k for k in self._result if k != "t"]
            rows = len(self._result.get("t", []))
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(keys)
                for r in range(rows):
                    w.writerow([self._result[k][r] for k in keys])
            self._status.setText(f"Exported {rows} samples to {path}")
            self._status.setStyleSheet("color: green;")
        except Exception as e:  # noqa: BLE001 - report to status, don't crash
            self._status.setText(f"Export failed: {e}")
            self._status.setStyleSheet("color: red;")

    # --- stimulus (mirrors the tuning-sequence discipline) ---
    def _build_stimulus(self):
        """Build (stimulus, finalize) closures for the step.

        ``stimulus`` saves control_mode / input_mode / whether the axis was in
        IDLE, switches to PASSTHROUGH + the right control mode, arms closed loop
        and sends the step. ``finalize`` zeroes the command, restores the saved
        modes and re-requests IDLE only if the axis was IDLE beforehand. Every
        device call is guarded so a USB hiccup can't leave the closures raising."""
        dev = self._dev
        ch = self._stim_chan.currentData()
        amp = self._stim_amp.value()
        saved: dict = {}

        def stimulus():
            try:
                saved["control_mode"] = dev.get_control_mode()
                saved["input_mode"] = dev.get_motion_config()["input_mode"]
                saved["was_idle"] = dev.current_state() == device_mod.IDLE
            except Exception:  # noqa: BLE001
                pass
            dev.set_input_mode(_PASSTHROUGH)
            dev.set_control_mode(_STIM_MODE[ch])
            dev.set_closed_loop(True)
            if ch == "torque":
                dev.set_input_torque(amp)
            else:
                dev.set_input_vel(amp)

        def finalize():
            try:
                if ch == "torque":
                    dev.set_input_torque(0.0)
                else:
                    dev.set_input_vel(0.0)
            except Exception:  # noqa: BLE001
                pass
            try:
                if "input_mode" in saved:
                    dev.set_input_mode(saved["input_mode"])
            except Exception:  # noqa: BLE001
                pass
            try:
                if "control_mode" in saved:
                    dev.set_control_mode(saved["control_mode"])
            except Exception:  # noqa: BLE001
                pass
            try:
                if saved.get("was_idle"):
                    dev.set_requested_state(device_mod.IDLE)
            except Exception:  # noqa: BLE001
                pass

        return stimulus, finalize
