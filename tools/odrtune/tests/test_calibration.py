from odrtune.core.device import Device
from odrtune.core.calibration import CalibrationRunner
from tests.fake_odrive import FakeODrive


def test_calibration_requests_state_and_reports_success():
    raw = FakeODrive()
    dev = Device(raw)
    runner = CalibrationRunner(dev)
    runner.start()
    assert raw.axis0.requested_state == 3  # FULL_CALIBRATION_SEQUENCE
    assert runner.running is True

    # simulate ODrive still busy (not back to IDLE)
    raw.axis0.current_state = 3
    assert runner.poll() == "running"

    # simulate completion: returns to IDLE with success
    raw.axis0.current_state = 1
    raw.axis0.procedure_result = 0
    assert runner.poll() == "success"
    assert runner.running is False


def test_calibration_reports_failure():
    raw = FakeODrive()
    dev = Device(raw)
    runner = CalibrationRunner(dev)
    runner.start()
    raw.axis0.current_state = 1
    raw.axis0.procedure_result = 5  # non-zero == failure
    result = runner.poll()
    assert result == "failed"
    assert runner.last_error["procedure_result"] == 5
