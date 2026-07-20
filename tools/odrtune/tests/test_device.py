from odrtune.core.device import Device
from tests.fake_odrive import FakeODrive


def test_device_reads_identity_and_feedback():
    dev = Device(FakeODrive())
    assert dev.fw_version() == (0, 6, 10)
    assert dev.serial_hex() == "0x123456789ABC"
    fb = dev.feedback()
    assert fb["bus_voltage"] == 24.0
    assert fb["pos"] == 0.0 and fb["iq_measured"] == 0.0


def test_device_gains_roundtrip():
    dev = Device(FakeODrive())
    dev.set_gains(pos_gain=30.0, vel_gain=0.2, vel_integrator_gain=0.4)
    assert dev.get_gains() == {"pos_gain": 30.0, "vel_gain": 0.2,
                               "vel_integrator_gain": 0.4}


def test_device_state_control():
    raw = FakeODrive()
    dev = Device(raw)
    dev.set_closed_loop(True)
    assert raw.axis0.requested_state == 8
    dev.set_input_vel(2.0)
    assert raw.axis0.controller.input_vel == 2.0
