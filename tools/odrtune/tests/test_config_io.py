import json
from odrtune.core.device import Device
from odrtune.core.config_io import backup, restore, save_to_nvm
from tests.fake_odrive import FakeODrive


def test_backup_captures_gains():
    dev = Device(FakeODrive())
    snap = backup(dev)
    assert snap["gains"]["pos_gain"] == 20.0
    assert snap["gains"]["vel_gain"] == 0.16


def test_restore_applies_gains():
    dev = Device(FakeODrive())
    restore(dev, {"gains": {"pos_gain": 55.0, "vel_gain": 0.3,
                            "vel_integrator_gain": 0.6}})
    assert dev.get_gains()["pos_gain"] == 55.0


def test_backup_json_roundtrip(tmp_path):
    dev = Device(FakeODrive())
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(backup(dev)))
    restore(dev, json.loads(p.read_text()))
    assert dev.get_gains()["vel_integrator_gain"] == 0.32


def test_save_to_nvm_calls_save():
    raw = FakeODrive()
    save_to_nvm(Device(raw))
    assert raw.saved is True
