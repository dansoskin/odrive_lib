from odrtune.core.device import Device
from odrtune.core.sampler import Sampler
from tests.fake_odrive import FakeODrive


def test_sampler_collects_channels():
    raw = FakeODrive()
    dev = Device(raw)
    s = Sampler(dev, maxlen=5)
    raw.axis0.pos_vel_mapper.pos_rel = 1.5
    s.sample(t=0.0)
    assert s.series("pos")[-1] == 1.5
    assert s.series("t")[-1] == 0.0
    assert "iq_measured" in s.channels


def test_sampler_respects_maxlen():
    s = Sampler(Device(FakeODrive()), maxlen=3)
    for i in range(5):
        s.sample(t=float(i))
    assert len(s.series("t")) == 3
    assert s.series("t")[0] == 2.0  # oldest two dropped
