"""Headless GUI construction tests. Force Qt's offscreen platform so widgets
build with no display and no hardware."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def test_main_window_constructs(app):
    from odrtune.ui.main_window import MainWindow
    win = MainWindow()
    assert win.windowTitle() == "odrtune"


def test_add_panel_fans_out_device(app):
    from odrtune.ui.main_window import MainWindow
    from tests.fake_odrive import FakeODrive
    from odrtune.core.device import Device
    from PySide6.QtWidgets import QWidget

    class DummyPanel(QWidget):
        def __init__(self):
            super().__init__()
            self.got = None

        def set_device(self, dev):
            self.got = dev

    win = MainWindow()
    panel = DummyPanel()
    win.add_panel("Dummy", panel)
    dev = Device(FakeODrive())
    win._set_device(dev)
    assert panel.got is dev


def test_plots_panel_constructs_and_sets_device(app):
    from odrtune.ui.plots_panel import PlotsPanel
    from tests.fake_odrive import FakeODrive
    from odrtune.core.device import Device

    panel = PlotsPanel(interval_ms=10)
    panel.set_device(Device(FakeODrive()))
    panel._tick()  # one manual tick populates curves without the timer
    assert panel._sampler is not None
    assert len(panel._sampler.series("t")) == 1


def test_calibration_panel_runs_against_fake(app):
    from odrtune.ui.calibration_panel import CalibrationPanel
    from tests.fake_odrive import FakeODrive
    from odrtune.core.device import Device

    raw = FakeODrive()
    panel = CalibrationPanel(interval_ms=1)
    panel.set_device(Device(raw))
    panel._start()
    assert raw.axis0.requested_state == 3
    raw.axis0.current_state = 3
    panel._poll()  # running
    raw.axis0.current_state = 1
    raw.axis0.procedure_result = 0
    panel._poll()  # success
    assert "succeeded" in panel._status.text()


def test_tuning_panel_applies_gain_and_steps(app):
    from odrtune.ui.tuning_panel import TuningPanel
    from tests.fake_odrive import FakeODrive
    from odrtune.core.device import Device

    raw = FakeODrive()
    panel = TuningPanel(interval_ms=1)
    panel.set_device(Device(raw))
    panel._apply_gain("pos_gain", 42.0)
    assert raw.axis0.controller.config.pos_gain == 42.0
    panel._start_step()
    assert raw.axis0.requested_state == 8       # closed loop
    assert raw.axis0.controller.input_pos == 1.0
    panel._record()
    t, y = panel._step.data()
    assert len(t) == 1
