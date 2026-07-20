from odrtune.core.device import Device
from odrtune.core.step_response import StepResponse
from tests.fake_odrive import FakeODrive


def test_step_commands_target_and_records_samples():
    raw = FakeODrive()
    dev = Device(raw)
    sr = StepResponse(dev, channel="pos")
    sr.begin(target=1.0)
    assert raw.axis0.controller.input_pos == 1.0  # step commanded

    # simulate the axis converging over 3 samples
    for i, p in enumerate((0.4, 0.8, 1.0)):
        raw.axis0.pos_vel_mapper.pos_rel = p
        sr.record(t=float(i))
    t, y = sr.data()
    assert t == [0.0, 1.0, 2.0]
    assert y == [0.4, 0.8, 1.0]
    assert sr.target == 1.0
