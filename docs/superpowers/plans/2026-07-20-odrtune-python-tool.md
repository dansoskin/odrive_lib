# odrtune — Python USB Tuning/Debugging Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `odrtune`, a PySide6 desktop GUI that connects to an ODrive Pro/S1 over USB (via the official `odrive` Python package) for debugging and tuning — live plots, calibration wizard, gain tuning + step response, and config backup/restore/save-to-NVM.

**Architecture:** A Qt-free `core/` layer wraps the ODrive device (connect/scan, parameter read/write, calibration sequencing, sampling, step response, config I/O) and is unit-testable against a fake device object. A `ui/` layer (PySide6 widgets + pyqtgraph plots) sits on top, polling `core` on a `QTimer`. The tool is independent of the C library.

**Tech Stack:** Python 3.10+, PySide6 (Qt), pyqtgraph, `odrive` package, pytest (dev).

**Testing strategy:** TDD for the `core/` pure-logic modules using an in-memory **fake ODrive tree** (no hardware). GUI widgets get **headless construction smoke tests** using Qt's `offscreen` platform (`QT_QPA_PLATFORM=offscreen`) — they verify widgets build and wire to `core` without a display or hardware. Full end-to-end verification (calibration, live motor plots) is done manually against a real ODrive whenever one is plugged in.

**File structure (all under `tools/odrtune/`):**
- Create: `pyproject.toml` — package metadata, deps, `odrtune` entry point.
- Create: `odrtune/__init__.py` — version.
- Create: `odrtune/__main__.py` — launches the Qt app.
- Create: `odrtune/core/__init__.py`
- Create: `odrtune/core/device.py` — `connect()`/`scan()`, `Device` wrapper (serial, fw, axis access).
- Create: `odrtune/core/config_io.py` — backup config → dict/JSON, restore, save-to-NVM.
- Create: `odrtune/core/sampler.py` — ring-buffer sampler of pos/vel/iq/temp/bus.
- Create: `odrtune/core/calibration.py` — calibration step sequencer.
- Create: `odrtune/core/step_response.py` — command a step, record response.
- Create: `odrtune/ui/__init__.py`
- Create: `odrtune/ui/main_window.py` — `QMainWindow` with tabs.
- Create: `odrtune/ui/connect_panel.py`
- Create: `odrtune/ui/plots_panel.py`
- Create: `odrtune/ui/calibration_panel.py`
- Create: `odrtune/ui/tuning_panel.py`
- Create: `odrtune/ui/config_panel.py`
- Create: `tests/__init__.py`
- Create: `tests/fake_odrive.py` — in-memory fake device tree.
- Create: `tests/test_config_io.py`, `tests/test_sampler.py`, `tests/test_calibration.py`, `tests/test_step_response.py`, `tests/test_ui_smoke.py`.

**ODrive USB object model used (fw 0.6.x, via `odrive` package):**
- `odrive.find_any(timeout=...)` / `odrive.find_all(...)` → device object `dev`.
- `dev.serial_number`, `dev.fw_version_major/minor/revision`, `dev.vbus_voltage`, `dev.ibus`.
- Axis: `dev.axis0`. State: `axis.current_state` (read), `axis.requested_state` (write). `AxisState` ints match the C enum (IDLE=1, FULL_CALIBRATION_SEQUENCE=3, CLOSED_LOOP_CONTROL=8).
- Feedback: `axis.pos_vel_mapper.pos_rel`/`vel` (fw 0.6.x) — abstracted behind `Device` getters so exact attribute paths live in one file.
- Controller gains: `axis.controller.config.pos_gain`, `.vel_gain`, `.vel_integrator_gain`.
- Currents: `axis.motor.foc.Iq_setpoint`, `axis.motor.foc.Iq_measured`. Temp: `axis.motor.fet_thermistor.temperature`, `axis.motor.motor_thermistor.temperature`.
- Setpoints: `axis.controller.input_pos/input_vel/input_torque`; `axis.controller.config.control_mode`, `.input_mode`.
- Procedure result: `axis.procedure_result` (0 == SUCCESS). Errors: `axis.active_errors`, `axis.disarm_reason`.
- Persistence: `dev.save_configuration()`, `dev.erase_configuration()`, `dev.reboot()`.

> All exact attribute paths are accessed **only** through `core/device.py` getters/setters so a firmware-version tweak touches one file. `core` functions take a `Device` (or a duck-typed fake), never `import odrive` directly except in `device.connect/scan`.

---

### Task 1: Package scaffold + entry point

**Files:**
- Create: `tools/odrtune/pyproject.toml`
- Create: `tools/odrtune/odrtune/__init__.py`
- Create: `tools/odrtune/odrtune/__main__.py`
- Create: `tools/odrtune/tests/__init__.py`

- [ ] **Step 1: Write `tools/odrtune/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "odrtune"
version = "0.1.0"
description = "USB debugging and tuning GUI for ODrive Pro/S1 (fw 0.6.x)"
requires-python = ">=3.10"
dependencies = [
    "PySide6>=6.5",
    "pyqtgraph>=0.13",
    "odrive>=0.6.8",
    "numpy>=1.24",
]

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
odrtune = "odrtune.__main__:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["odrtune*"]
```

- [ ] **Step 2: Write `tools/odrtune/odrtune/__init__.py`**

```python
"""odrtune - USB debugging and tuning GUI for ODrive Pro/S1."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Write `tools/odrtune/odrtune/__main__.py`**

```python
"""Application entry point."""
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from odrtune.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write `tools/odrtune/tests/__init__.py`**

```python
```

- [ ] **Step 5: Install dev deps and confirm the package imports**

Run:
```bash
cd tools/odrtune && python -m pip install -e ".[dev]"
python -c "import odrtune; print(odrtune.__version__)"
```
Expected: prints `0.1.0`. (`__main__` importing `ui.main_window` is not exercised yet — that module arrives in Task 8.)

- [ ] **Step 6: Commit**

```bash
git add tools/odrtune/pyproject.toml tools/odrtune/odrtune/__init__.py \
        tools/odrtune/odrtune/__main__.py tools/odrtune/tests/__init__.py
git commit -m "feat(py): scaffold odrtune package and entry point"
```

---

### Task 2: Fake ODrive tree for tests

**Files:**
- Create: `tools/odrtune/tests/fake_odrive.py`

- [ ] **Step 1: Write `tools/odrtune/tests/fake_odrive.py`**

```python
"""In-memory fake mimicking the odrive USB object tree, for hardware-free tests.

Only the attributes core/ touches are modeled. save/erase/reboot record calls."""
from types import SimpleNamespace


class FakeAxis:
    def __init__(self):
        self.current_state = 1          # IDLE
        self.requested_state = 1
        self.procedure_result = 0       # SUCCESS
        self.active_errors = 0
        self.disarm_reason = 0
        self.controller = SimpleNamespace(
            input_pos=0.0, input_vel=0.0, input_torque=0.0,
            config=SimpleNamespace(
                control_mode=3, input_mode=1,
                pos_gain=20.0, vel_gain=0.16, vel_integrator_gain=0.32,
            ),
        )
        self.motor = SimpleNamespace(
            foc=SimpleNamespace(Iq_setpoint=0.0, Iq_measured=0.0),
            fet_thermistor=SimpleNamespace(temperature=25.0),
            motor_thermistor=SimpleNamespace(temperature=24.0),
        )
        self.pos_vel_mapper = SimpleNamespace(pos_rel=0.0, vel=0.0)


class FakeODrive:
    def __init__(self):
        self.serial_number = 0x123456789ABC
        self.fw_version_major = 0
        self.fw_version_minor = 6
        self.fw_version_revision = 10
        self.vbus_voltage = 24.0
        self.ibus = 0.5
        self.axis0 = FakeAxis()
        self.saved = False
        self.erased = False
        self.rebooted = False

    def save_configuration(self):
        self.saved = True

    def erase_configuration(self):
        self.erased = True

    def reboot(self):
        self.rebooted = True
```

- [ ] **Step 2: Confirm the fake imports**

Run: `cd tools/odrtune && python -c "from tests.fake_odrive import FakeODrive; d=FakeODrive(); print(d.axis0.controller.config.pos_gain)"`
Expected: prints `20.0`.

- [ ] **Step 3: Commit**

```bash
git add tools/odrtune/tests/fake_odrive.py
git commit -m "test(py): add in-memory fake ODrive tree for hardware-free tests"
```

---

### Task 3: Device wrapper (`core/device.py`)

**Files:**
- Create: `tools/odrtune/odrtune/core/__init__.py`
- Create: `tools/odrtune/odrtune/core/device.py`
- Create: `tools/odrtune/tests/test_device.py`

- [ ] **Step 1: Write the failing test `tools/odrtune/tests/test_device.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/odrtune && python -m pytest tests/test_device.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odrtune.core.device'`.

- [ ] **Step 3: Write `tools/odrtune/odrtune/core/__init__.py`**

```python
```

- [ ] **Step 4: Write `tools/odrtune/odrtune/core/device.py`**

```python
"""Wrapper over the odrive USB object tree. All firmware-specific attribute
paths live here so a version change touches one file. Accepts either a real
odrive device or a duck-typed fake."""
from __future__ import annotations

# AxisState ints (fw 0.6.x)
IDLE = 1
FULL_CALIBRATION_SEQUENCE = 3
CLOSED_LOOP_CONTROL = 8


def connect(timeout: float = 15.0):
    """Find and return the first ODrive over USB. Raises on timeout."""
    import odrive
    return Device(odrive.find_any(timeout=timeout))


def scan(timeout: float = 5.0):
    """Return a list of Device wrappers for all ODrives found."""
    import odrive
    return [Device(d) for d in odrive.find_all(timeout=timeout)]


class Device:
    def __init__(self, raw, axis_index: int = 0):
        self._raw = raw
        self._axis = getattr(raw, f"axis{axis_index}")

    # --- identity ---
    def fw_version(self) -> tuple[int, int, int]:
        return (self._raw.fw_version_major, self._raw.fw_version_minor,
                self._raw.fw_version_revision)

    def serial_hex(self) -> str:
        return f"0x{self._raw.serial_number:X}"

    # --- feedback snapshot ---
    def feedback(self) -> dict:
        a = self._axis
        return {
            "pos": a.pos_vel_mapper.pos_rel,
            "vel": a.pos_vel_mapper.vel,
            "iq_setpoint": a.motor.foc.Iq_setpoint,
            "iq_measured": a.motor.foc.Iq_measured,
            "fet_temp": a.motor.fet_thermistor.temperature,
            "motor_temp": a.motor.motor_thermistor.temperature,
            "bus_voltage": self._raw.vbus_voltage,
            "bus_current": self._raw.ibus,
        }

    # --- state / setpoints ---
    def set_requested_state(self, state: int) -> None:
        self._axis.requested_state = state

    def current_state(self) -> int:
        return self._axis.current_state

    def procedure_result(self) -> int:
        return self._axis.procedure_result

    def errors(self) -> dict:
        return {"active_errors": self._axis.active_errors,
                "disarm_reason": self._axis.disarm_reason}

    def set_closed_loop(self, enable: bool) -> None:
        self.set_requested_state(CLOSED_LOOP_CONTROL if enable else IDLE)

    def set_input_pos(self, pos: float) -> None:
        self._axis.controller.input_pos = pos

    def set_input_vel(self, vel: float) -> None:
        self._axis.controller.input_vel = vel

    def set_input_torque(self, torque: float) -> None:
        self._axis.controller.input_torque = torque

    # --- gains ---
    def get_gains(self) -> dict:
        c = self._axis.controller.config
        return {"pos_gain": c.pos_gain, "vel_gain": c.vel_gain,
                "vel_integrator_gain": c.vel_integrator_gain}

    def set_gains(self, pos_gain=None, vel_gain=None,
                  vel_integrator_gain=None) -> None:
        c = self._axis.controller.config
        if pos_gain is not None:
            c.pos_gain = pos_gain
        if vel_gain is not None:
            c.vel_gain = vel_gain
        if vel_integrator_gain is not None:
            c.vel_integrator_gain = vel_integrator_gain

    # --- persistence ---
    def save(self) -> None:
        self._raw.save_configuration()

    def erase(self) -> None:
        self._raw.erase_configuration()

    def reboot(self) -> None:
        self._raw.reboot()

    @property
    def raw(self):
        return self._raw
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tools/odrtune && python -m pytest tests/test_device.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/odrtune/odrtune/core/__init__.py tools/odrtune/odrtune/core/device.py \
        tools/odrtune/tests/test_device.py
git commit -m "feat(py): add Device wrapper over ODrive USB tree"
```

---

### Task 4: Config backup/restore/save (`core/config_io.py`)

**Files:**
- Create: `tools/odrtune/odrtune/core/config_io.py`
- Create: `tools/odrtune/tests/test_config_io.py`

- [ ] **Step 1: Write the failing test `tools/odrtune/tests/test_config_io.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/odrtune && python -m pytest tests/test_config_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odrtune.core.config_io'`.

- [ ] **Step 3: Write `tools/odrtune/odrtune/core/config_io.py`**

```python
"""Config backup/restore to a plain dict (JSON-serializable) and save-to-NVM.

The snapshot intentionally captures the tunable subset we expose in the GUI
(controller gains); it is a versioned dict so it can grow without breaking old
files."""
from __future__ import annotations

from odrtune.core.device import Device

SCHEMA_VERSION = 1


def backup(dev: Device) -> dict:
    """Read the tunable config into a JSON-serializable dict."""
    return {"schema": SCHEMA_VERSION, "gains": dev.get_gains()}


def restore(dev: Device, snapshot: dict) -> None:
    """Apply a snapshot produced by backup(). Unknown keys are ignored."""
    gains = snapshot.get("gains", {})
    dev.set_gains(
        pos_gain=gains.get("pos_gain"),
        vel_gain=gains.get("vel_gain"),
        vel_integrator_gain=gains.get("vel_integrator_gain"),
    )


def save_to_nvm(dev: Device) -> None:
    """Persist current config to the ODrive's non-volatile memory."""
    dev.save()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/odrtune && python -m pytest tests/test_config_io.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/odrtune/odrtune/core/config_io.py tools/odrtune/tests/test_config_io.py
git commit -m "feat(py): add config backup/restore/save-to-NVM"
```

---

### Task 5: Sampler ring buffer (`core/sampler.py`)

**Files:**
- Create: `tools/odrtune/odrtune/core/sampler.py`
- Create: `tools/odrtune/tests/test_sampler.py`

- [ ] **Step 1: Write the failing test `tools/odrtune/tests/test_sampler.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/odrtune && python -m pytest tests/test_sampler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odrtune.core.sampler'`.

- [ ] **Step 3: Write `tools/odrtune/odrtune/core/sampler.py`**

```python
"""Fixed-capacity time-series buffers over Device.feedback(). GUI-agnostic:
the UI calls sample() on a timer, then reads series() for plotting."""
from __future__ import annotations

from collections import deque

from odrtune.core.device import Device

CHANNELS = ("pos", "vel", "iq_setpoint", "iq_measured",
            "fet_temp", "motor_temp", "bus_voltage", "bus_current")


class Sampler:
    def __init__(self, dev: Device, maxlen: int = 2000):
        self._dev = dev
        self.channels = CHANNELS
        self._buf = {name: deque(maxlen=maxlen) for name in ("t",) + CHANNELS}

    def sample(self, t: float) -> dict:
        fb = self._dev.feedback()
        self._buf["t"].append(t)
        for name in CHANNELS:
            self._buf[name].append(fb[name])
        return fb

    def series(self, name: str) -> list:
        return list(self._buf[name])

    def clear(self) -> None:
        for d in self._buf.values():
            d.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/odrtune && python -m pytest tests/test_sampler.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/odrtune/odrtune/core/sampler.py tools/odrtune/tests/test_sampler.py
git commit -m "feat(py): add ring-buffer sampler over device feedback"
```

---

### Task 6: Calibration sequencer (`core/calibration.py`)

**Files:**
- Create: `tools/odrtune/odrtune/core/calibration.py`
- Create: `tools/odrtune/tests/test_calibration.py`

- [ ] **Step 1: Write the failing test `tools/odrtune/tests/test_calibration.py`**

```python
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
    raw.axis0.current_state = 3          # entered calibration
    assert runner.poll() == "running"
    raw.axis0.current_state = 1          # back to IDLE
    raw.axis0.procedure_result = 5       # non-zero == failure
    result = runner.poll()
    assert result == "failed"
    assert runner.last_error["procedure_result"] == 5


def test_calibration_ignores_stale_result_before_leaving_idle():
    raw = FakeODrive()
    dev = Device(raw)
    runner = CalibrationRunner(dev)
    runner.start()
    raw.axis0.current_state = 1          # still IDLE right after request
    raw.axis0.procedure_result = 5       # stale value from a prior run
    assert runner.poll() == "running"    # must NOT report failed yet
    assert runner.running is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/odrtune && python -m pytest tests/test_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odrtune.core.calibration'`.

- [ ] **Step 3: Write `tools/odrtune/odrtune/core/calibration.py`**

```python
"""Drives the full motor+encoder calibration sequence and polls for the result.

Usage: start(), then poll() repeatedly (e.g. on a QTimer). poll() returns one
of 'running' | 'success' | 'failed'. Because current_state briefly stays IDLE
right after the request, start() latches a 'started' flag and poll() only
evaluates completion after it has observed the axis leave IDLE."""
from __future__ import annotations

from odrtune.core.device import Device, IDLE, FULL_CALIBRATION_SEQUENCE


class CalibrationRunner:
    def __init__(self, dev: Device):
        self._dev = dev
        self.running = False
        self._left_idle = False
        self.last_error = None

    def start(self) -> None:
        self.running = True
        self._left_idle = False
        self.last_error = None
        self._dev.set_requested_state(FULL_CALIBRATION_SEQUENCE)

    def poll(self) -> str:
        if not self.running:
            return "success" if self.last_error is None else "failed"
        state = self._dev.current_state()
        if state != IDLE:
            self._left_idle = True
            return "running"
        if not self._left_idle:
            # initial IDLE tick before calibration engages; procedure_result
            # may still hold a stale value from a prior run - ignore it.
            return "running"
        pr = self._dev.procedure_result()
        if pr == 0:
            self.running = False
            return "success"
        self.running = False
        self.last_error = {"procedure_result": pr, **self._dev.errors()}
        return "failed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/odrtune && python -m pytest tests/test_calibration.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/odrtune/odrtune/core/calibration.py tools/odrtune/tests/test_calibration.py
git commit -m "feat(py): add full-calibration sequencer with result polling"
```

---

### Task 7: Step-response recorder (`core/step_response.py`)

**Files:**
- Create: `tools/odrtune/odrtune/core/step_response.py`
- Create: `tools/odrtune/tests/test_step_response.py`

- [ ] **Step 1: Write the failing test `tools/odrtune/tests/test_step_response.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/odrtune && python -m pytest tests/test_step_response.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odrtune.core.step_response'`.

- [ ] **Step 3: Write `tools/odrtune/odrtune/core/step_response.py`**

```python
"""Commands a setpoint step and records the response channel over time, for
tuning by eye. GUI-agnostic: begin() then record() on a timer, then data()."""
from __future__ import annotations

from odrtune.core.device import Device

_COMMAND = {
    "pos": lambda dev, v: dev.set_input_pos(v),
    "vel": lambda dev, v: dev.set_input_vel(v),
    "torque": lambda dev, v: dev.set_input_torque(v),
}


class StepResponse:
    def __init__(self, dev: Device, channel: str = "pos"):
        if channel not in _COMMAND:
            raise ValueError(f"unknown channel: {channel}")
        self._dev = dev
        self.channel = channel
        self.target = 0.0
        self._t: list[float] = []
        self._y: list[float] = []

    def begin(self, target: float) -> None:
        self.target = target
        self._t.clear()
        self._y.clear()
        _COMMAND[self.channel](self._dev, target)

    def record(self, t: float) -> None:
        fb = self._dev.feedback()
        # response channel: pos->pos, vel->vel, torque->iq_measured proxy
        key = {"pos": "pos", "vel": "vel", "torque": "iq_measured"}[self.channel]
        self._t.append(t)
        self._y.append(fb[key])

    def data(self) -> tuple[list, list]:
        return list(self._t), list(self._y)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/odrtune && python -m pytest tests/test_step_response.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/odrtune/odrtune/core/step_response.py tools/odrtune/tests/test_step_response.py
git commit -m "feat(py): add step-response recorder"
```

---

### Task 8: Main window shell + connect panel + headless smoke test

**Files:**
- Create: `tools/odrtune/odrtune/ui/__init__.py`
- Create: `tools/odrtune/odrtune/ui/main_window.py`
- Create: `tools/odrtune/odrtune/ui/connect_panel.py`
- Create: `tools/odrtune/tests/test_ui_smoke.py`

- [ ] **Step 1: Write `tools/odrtune/odrtune/ui/__init__.py`**

```python
```

- [ ] **Step 2: Write `tools/odrtune/odrtune/ui/connect_panel.py`**

```python
"""Connect/scan panel. Emits `connected(Device)` when a device is opened.
Connection uses core.device.connect(); failures are shown, not raised."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel)

from odrtune.core import device as device_mod


class ConnectPanel(QWidget):
    connected = Signal(object)  # emits a core.device.Device

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QHBoxLayout(self)
        self._btn = QPushButton("Connect")
        self._status = QLabel("Not connected")
        layout.addWidget(self._btn)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self._btn.clicked.connect(self._on_connect)

    def _on_connect(self):
        try:
            dev = device_mod.connect(timeout=15.0)
        except Exception as exc:  # noqa: BLE001 - surface any USB/find error
            self._status.setText(f"Connect failed: {exc}")
            return
        self._dev = dev
        maj, minr, rev = dev.fw_version()
        self._status.setText(f"Connected {dev.serial_hex()}  fw {maj}.{minr}.{rev}")
        self.connected.emit(dev)
```

- [ ] **Step 3: Write `tools/odrtune/odrtune/ui/main_window.py`**

```python
"""Top-level window: a connect bar plus a tab per feature. Panels are given
the active Device when the connect panel reports a connection.

Panels are added in later tasks; this shell wires the connect signal to a
set_device() fan-out so adding a panel is one line."""
from __future__ import annotations

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QTabWidget)

from odrtune.ui.connect_panel import ConnectPanel


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("odrtune")
        self._device = None
        self._device_listeners = []

        central = QWidget()
        root = QVBoxLayout(central)
        self._connect = ConnectPanel()
        self._connect.connected.connect(self._set_device)
        self._tabs = QTabWidget()
        root.addWidget(self._connect)
        root.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

    def add_panel(self, title, panel):
        """Add a feature tab. If the panel has set_device(), it is registered
        to receive the active Device on connect."""
        self._tabs.addTab(panel, title)
        if hasattr(panel, "set_device"):
            self._device_listeners.append(panel)
            if self._device is not None:
                panel.set_device(self._device)

    def _set_device(self, dev):
        self._device = dev
        for p in self._device_listeners:
            p.set_device(dev)
```

- [ ] **Step 4: Write the headless smoke test `tools/odrtune/tests/test_ui_smoke.py`**

```python
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
```

- [ ] **Step 5: Run the smoke tests**

Run: `cd tools/odrtune && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v`
Expected: 2 passed. (On Windows PowerShell: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_ui_smoke.py -v`.)

- [ ] **Step 6: Commit**

```bash
git add tools/odrtune/odrtune/ui/__init__.py tools/odrtune/odrtune/ui/main_window.py \
        tools/odrtune/odrtune/ui/connect_panel.py tools/odrtune/tests/test_ui_smoke.py
git commit -m "feat(py): add main window shell and connect panel"
```

---

### Task 9: Live plots panel

**Files:**
- Create: `tools/odrtune/odrtune/ui/plots_panel.py`
- Modify: `tools/odrtune/tests/test_ui_smoke.py` (add a construction test)

- [ ] **Step 1: Write `tools/odrtune/odrtune/ui/plots_panel.py`**

```python
"""Live scrolling plots of pos/vel/Iq/temperature/bus voltage using pyqtgraph.
Polls a Sampler on a QTimer once a Device is set."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout

from odrtune.core.sampler import Sampler

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
```

- [ ] **Step 2: Add a construction test to `tools/odrtune/tests/test_ui_smoke.py`**

Append this function to the existing file:

```python
def test_plots_panel_constructs_and_sets_device(app):
    from odrtune.ui.plots_panel import PlotsPanel
    from tests.fake_odrive import FakeODrive
    from odrtune.core.device import Device

    panel = PlotsPanel(interval_ms=10)
    panel.set_device(Device(FakeODrive()))
    panel._tick()  # one manual tick populates curves without the timer
    assert panel._sampler is not None
    assert len(panel._sampler.series("t")) == 1
```

- [ ] **Step 3: Run the smoke tests**

Run: `cd tools/odrtune && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add tools/odrtune/odrtune/ui/plots_panel.py tools/odrtune/tests/test_ui_smoke.py
git commit -m "feat(py): add live plots panel (pyqtgraph)"
```

---

### Task 10: Calibration panel

**Files:**
- Create: `tools/odrtune/odrtune/ui/calibration_panel.py`
- Modify: `tools/odrtune/tests/test_ui_smoke.py`

- [ ] **Step 1: Write `tools/odrtune/odrtune/ui/calibration_panel.py`**

```python
"""Runs full calibration via core.calibration.CalibrationRunner and shows the
result. Polls on a QTimer."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel)

from odrtune.core.calibration import CalibrationRunner


class CalibrationPanel(QWidget):
    def __init__(self, parent=None, interval_ms: int = 200):
        super().__init__(parent)
        self._dev = None
        self._runner = None
        layout = QVBoxLayout(self)
        self._btn = QPushButton("Run full calibration")
        self._btn.setEnabled(False)
        self._status = QLabel("Connect a device to calibrate.")
        layout.addWidget(self._btn)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self._btn.clicked.connect(self._start)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def set_device(self, dev):
        self._dev = dev
        self._btn.setEnabled(True)
        self._status.setText("Ready.")

    def _start(self):
        if self._dev is None:
            return
        self._runner = CalibrationRunner(self._dev)
        self._runner.start()
        self._status.setText("Calibrating…")
        self._btn.setEnabled(False)
        self._timer.start()

    def _poll(self):
        if self._runner is None:
            return
        result = self._runner.poll()
        if result == "running":
            return
        self._timer.stop()
        self._btn.setEnabled(True)
        if result == "success":
            self._status.setText("Calibration succeeded.")
        else:
            self._status.setText(f"Calibration failed: {self._runner.last_error}")
```

- [ ] **Step 2: Add a construction test to `tools/odrtune/tests/test_ui_smoke.py`**

```python
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
```

- [ ] **Step 3: Run the smoke tests**

Run: `cd tools/odrtune && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add tools/odrtune/odrtune/ui/calibration_panel.py tools/odrtune/tests/test_ui_smoke.py
git commit -m "feat(py): add calibration wizard panel"
```

---

### Task 11: Tuning panel (gain sliders + step response)

**Files:**
- Create: `tools/odrtune/odrtune/ui/tuning_panel.py`
- Modify: `tools/odrtune/tests/test_ui_smoke.py`

- [ ] **Step 1: Write `tools/odrtune/odrtune/ui/tuning_panel.py`**

```python
"""Gain tuning: sliders for pos_gain, vel_gain, vel_integrator_gain (live-apply
to the device), plus a step-response test plotted with pyqtgraph.

Sliders are integer Qt widgets scaled to floats via a per-gain factor."""
from __future__ import annotations

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSlider,
                               QLabel, QPushButton, QDoubleSpinBox)

from odrtune.core.step_response import StepResponse

# (name, max_value, resolution) -> slider int = value / resolution
_GAINS = [
    ("pos_gain", 200.0, 0.1),
    ("vel_gain", 5.0, 0.001),
    ("vel_integrator_gain", 10.0, 0.001),
]


class _GainRow(QWidget):
    def __init__(self, name, maxv, res, on_change):
        super().__init__()
        self._name = name
        self._res = res
        self._on_change = on_change
        row = QHBoxLayout(self)
        self._label = QLabel(name)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(int(maxv / res))
        self._value = QLabel("0.000")
        row.addWidget(self._label)
        row.addWidget(self._slider, 1)
        row.addWidget(self._value)
        self._slider.valueChanged.connect(self._changed)

    def set_value(self, v: float):
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(v / self._res)))
        self._value.setText(f"{v:.3f}")
        self._slider.blockSignals(False)

    def _changed(self, raw):
        v = raw * self._res
        self._value.setText(f"{v:.3f}")
        self._on_change(self._name, v)


class TuningPanel(QWidget):
    def __init__(self, parent=None, interval_ms: int = 20):
        super().__init__(parent)
        self._dev = None
        self._step = None
        self._t0 = 0.0
        layout = QVBoxLayout(self)

        self._rows = {}
        for name, maxv, res in _GAINS:
            row = _GainRow(name, maxv, res, self._apply_gain)
            self._rows[name] = row
            layout.addWidget(row)

        step_bar = QHBoxLayout()
        self._target = QDoubleSpinBox()
        self._target.setRange(-100.0, 100.0)
        self._target.setValue(1.0)
        self._btn = QPushButton("Step (position)")
        self._btn.setEnabled(False)
        step_bar.addWidget(QLabel("Target:"))
        step_bar.addWidget(self._target)
        step_bar.addWidget(self._btn)
        layout.addLayout(step_bar)

        self._plot = pg.PlotWidget(title="Step response")
        self._plot.showGrid(x=True, y=True)
        self._curve = self._plot.plot(pen=pg.mkPen(width=2))
        self._target_line = self._plot.plot(pen=pg.mkPen(style=Qt.DashLine))
        layout.addWidget(self._plot, 1)

        self._btn.clicked.connect(self._start_step)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._record)

    def set_device(self, dev):
        self._dev = dev
        self._btn.setEnabled(True)
        gains = dev.get_gains()
        for name, row in self._rows.items():
            row.set_value(gains[name])

    def _apply_gain(self, name, value):
        if self._dev is not None:
            self._dev.set_gains(**{name: value})

    def _start_step(self):
        if self._dev is None:
            return
        self._dev.set_closed_loop(True)
        self._step = StepResponse(self._dev, channel="pos")
        self._step.begin(target=self._target.value())
        self._t0 = time.monotonic()
        self._timer.start()
        QTimer.singleShot(1500, self._timer.stop)  # record ~1.5 s

    def _record(self):
        if self._step is None:
            return
        try:
            self._step.record(t=time.monotonic() - self._t0)
        except Exception:  # noqa: BLE001
            return
        t, y = self._step.data()
        self._curve.setData(t, y)
        if t:
            self._target_line.setData([t[0], t[-1]],
                                      [self._step.target, self._step.target])
```

- [ ] **Step 2: Add a construction test to `tools/odrtune/tests/test_ui_smoke.py`**

```python
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
```

- [ ] **Step 3: Run the smoke tests**

Run: `cd tools/odrtune && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v`
Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add tools/odrtune/odrtune/ui/tuning_panel.py tools/odrtune/tests/test_ui_smoke.py
git commit -m "feat(py): add tuning panel (gain sliders + step response)"
```

---

### Task 12: Config panel (backup/restore/save + error viewer)

**Files:**
- Create: `tools/odrtune/odrtune/ui/config_panel.py`
- Modify: `tools/odrtune/tests/test_ui_smoke.py`

- [ ] **Step 1: Write `tools/odrtune/odrtune/ui/config_panel.py`**

```python
"""Backup config to JSON, restore from JSON, save to NVM, and view/clear errors.
File dialogs are wrapped so tests can drive backup/restore with explicit paths."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QFileDialog)

from odrtune.core.config_io import backup, restore, save_to_nvm


class ConfigPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._backup_btn = QPushButton("Backup to JSON…")
        self._restore_btn = QPushButton("Restore from JSON…")
        self._save_btn = QPushButton("Save to NVM")
        for b in (self._backup_btn, self._restore_btn, self._save_btn):
            b.setEnabled(False)
            bar.addWidget(b)
        layout.addLayout(bar)
        self._status = QLabel("Connect a device.")
        layout.addWidget(self._status)
        layout.addStretch(1)

        self._backup_btn.clicked.connect(self._backup_dialog)
        self._restore_btn.clicked.connect(self._restore_dialog)
        self._save_btn.clicked.connect(self._save)

    def set_device(self, dev):
        self._dev = dev
        for b in (self._backup_btn, self._restore_btn, self._save_btn):
            b.setEnabled(True)
        self._status.setText("Ready.")

    # --- testable core actions (no dialogs) ---
    def backup_to(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup(self._dev), f, indent=2)
        self._status.setText(f"Backed up to {path}")

    def restore_from(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            restore(self._dev, json.load(f))
        self._status.setText(f"Restored from {path}")

    def _save(self):
        if self._dev is None:
            return
        save_to_nvm(self._dev)
        self._status.setText("Saved to NVM.")

    # --- dialog wrappers ---
    def _backup_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Backup config",
                                              "odrive_config.json", "JSON (*.json)")
        if path:
            self.backup_to(path)

    def _restore_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore config",
                                              "", "JSON (*.json)")
        if path:
            self.restore_from(path)
```

- [ ] **Step 2: Add a construction test to `tools/odrtune/tests/test_ui_smoke.py`**

```python
def test_config_panel_backup_restore_save(app, tmp_path):
    from odrtune.ui.config_panel import ConfigPanel
    from tests.fake_odrive import FakeODrive
    from odrtune.core.device import Device

    raw = FakeODrive()
    panel = ConfigPanel()
    panel.set_device(Device(raw))
    p = str(tmp_path / "cfg.json")
    panel.backup_to(p)
    raw.axis0.controller.config.pos_gain = 999.0
    panel.restore_from(p)
    assert raw.axis0.controller.config.pos_gain == 20.0  # restored original
    panel._save()
    assert raw.saved is True
```

- [ ] **Step 3: Run the smoke tests**

Run: `cd tools/odrtune && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v`
Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add tools/odrtune/odrtune/ui/config_panel.py tools/odrtune/tests/test_ui_smoke.py
git commit -m "feat(py): add config backup/restore/save panel"
```

---

### Task 13: Wire panels into the main window + full test run + tool README

**Files:**
- Modify: `tools/odrtune/odrtune/ui/main_window.py`
- Modify: `tools/odrtune/tests/test_ui_smoke.py`
- Create: `tools/odrtune/README.md`

- [ ] **Step 1: Register the panels in `MainWindow.__init__`**

In `tools/odrtune/odrtune/ui/main_window.py`, add these imports at the top with the other UI imports:

```python
from odrtune.ui.plots_panel import PlotsPanel
from odrtune.ui.calibration_panel import CalibrationPanel
from odrtune.ui.tuning_panel import TuningPanel
from odrtune.ui.config_panel import ConfigPanel
```

Then, at the end of `__init__` (after `self.setCentralWidget(central)`), add:

```python
        self.add_panel("Plots", PlotsPanel())
        self.add_panel("Calibration", CalibrationPanel())
        self.add_panel("Tuning", TuningPanel())
        self.add_panel("Config", ConfigPanel())
```

- [ ] **Step 2: Add a full-window integration test to `tools/odrtune/tests/test_ui_smoke.py`**

```python
def test_full_window_has_all_tabs(app):
    from odrtune.ui.main_window import MainWindow
    win = MainWindow()
    titles = [win._tabs.tabText(i) for i in range(win._tabs.count())]
    assert titles == ["Plots", "Calibration", "Tuning", "Config"]
```

- [ ] **Step 3: Run the complete test suite**

Run: `cd tools/odrtune && QT_QPA_PLATFORM=offscreen python -m pytest -v`
Expected: all tests pass (device 3, config_io 4, sampler 2, calibration 3, step_response 1, ui_smoke 7 = 20 passed).

- [ ] **Step 4: Write `tools/odrtune/README.md`**

````markdown
# odrtune

USB debugging and tuning GUI for ODrive Pro/S1 (firmware 0.6.x). Independent of
the CAN C library in this repo.

## Install
```bash
cd tools/odrtune
python -m pip install -e ".[dev]"
```

## Run
```bash
odrtune            # or: python -m odrtune
```
Click **Connect** (ODrive plugged in over USB), then use the tabs:
- **Plots** — live pos/vel/Iq/temp/bus-voltage.
- **Calibration** — run the full motor+encoder calibration and see the result.
- **Tuning** — live gain sliders (pos/vel/vel-integrator) + position step response.
- **Config** — backup/restore config JSON and save to the ODrive's NVM.

## Tests (no hardware needed)
```bash
QT_QPA_PLATFORM=offscreen python -m pytest -v
```
Core logic is tested against an in-memory fake ODrive; GUI panels are built
headlessly with Qt's offscreen platform. End-to-end motor behavior is verified
manually against a real ODrive.
````

- [ ] **Step 5: Commit**

```bash
git add tools/odrtune/odrtune/ui/main_window.py tools/odrtune/tests/test_ui_smoke.py \
        tools/odrtune/README.md
git commit -m "feat(py): wire all panels into main window; add tool README"
```

---

## Self-Review

**Spec coverage (Part 2 of design):**
- §2.1 PySide6 + pyqtgraph + official `odrive` over USB, pyproject, `odrtune`/`python -m odrtune` → Tasks 1, 8, 13. ✅
- §2.2 Qt-free `core/` under `ui/` → `core/` Tasks 3–7, `ui/` Tasks 8–13; `core` never imports odrive except `connect/scan`. ✅
- §2.3 Connect panel (scan/select, serial+fw, status) → Task 8. ✅
- §2.3 Live plots (pos/vel/Iq/temp/bus V) → Task 9. ✅
- §2.3 Calibration wizard (AxisState sequence, progress, errors) → Tasks 6, 10. ✅
- §2.3 Gain sliders (pos/vel/vel-integrator, live-apply) + step response → Tasks 7, 11. ✅
- §2.3 Config backup/restore JSON + save to NVM; error viewer/clear → Tasks 4, 12. ✅
- §2.4 core testable without hardware; GUI verified against real hardware → fake tree (Task 2), offscreen smoke tests throughout. ✅
- Independence from C library → separate package under `tools/odrtune`, no shared code. ✅

**Placeholder scan:** No TBD/TODO; every step has complete code. ✅

**Type consistency:** `Device` methods (`fw_version`, `serial_hex`, `feedback`, `get_gains`, `set_gains`, `set_closed_loop`, `set_input_pos/vel/torque`, `set_requested_state`, `current_state`, `procedure_result`, `errors`, `save`, `erase`, `reboot`) are defined in Task 3 and used identically in Tasks 4–12. `Sampler.series/sample/channels`, `CalibrationRunner.start/poll/running/last_error`, `StepResponse.begin/record/data/target`, `config_io.backup/restore/save_to_nvm`, and `MainWindow.add_panel/_set_device/_tabs` all match between definition and use. Feedback dict keys (`pos`, `vel`, `iq_measured`, `fet_temp`, `bus_voltage`, …) match between `Device.feedback` (Task 3), `Sampler` (Task 5), `StepResponse` (Task 7), and `PlotsPanel` (Task 9). ✅

**Test count note:** ui_smoke grows to 7 tests (2 in Task 8, +1 each in Tasks 9/10/11/12, +1 in Task 13); with calibration's 3 core tests the Task 13 total is 20.

**Fw-attribute risk:** Exact odrive attribute paths (e.g. `pos_vel_mapper.pos_rel`, `motor.foc.Iq_measured`) are isolated in `core/device.py`. If a real ODrive on the bench uses slightly different paths for fw 0.6.x, only that file changes — verify against the connected device during first bring-up.
