# CLAUDE.md — odrtune (ODrive tuning GUI)

Reference for AI coding sessions in this repo.

## What this repo is

A **standalone PySide6 desktop app** for debugging and tuning an ODrive
(Pro / S1, firmware **0.6.x**) over **USB**, via the official `odrive` Python
package. It is independent of the CAN control C library, which lives in a
separate repo, **odrive_lib** (https://github.com/dansoskin/odrive_lib).

Run: `python __main__.py` (from the repo root). Deps in `requirements.txt`
(PySide6, pyqtgraph, odrive).

## Architecture

- **`core/`** — Qt-free logic, unit-testable against a fake device:
  - `device.py` — **the only place** that touches odrive/fibre and hard-codes
    firmware attribute paths. `connect(serial=None)`, `list_serials()` (passive
    discovery), `Device` wrapper: `feedback()`, `get/set_tuning()` (read-back
    verified, returns `{key:(ok,msg)}`), `get_motion_config()/set_motion()`,
    `diagnostics()`, `capabilities()`, `save()` (idle-gated, reboots),
    `estop()`, `clear_errors()`, `reboot()`, `disconnect()`. Guarded readers
    `_get`/`_getp`/`_getp_first` return NaN for absent attrs.
  - `config_io.py` — schema-2 backup/restore (diff + selective apply),
    inf/nan-safe JSON.
  - `sampler.py` — ring-buffer of feedback channels + computed error channels.
  - `capture.py` — 8 kHz onboard-oscilloscope capture (`odrive.high_rate_capturer`).
  - `settings.py` — `~/.odrtune/config.json` (Control-tab conversion factor).
- **`ui/`** — PySide6 widgets over `core/`:
  - `main_window.py` — **3-column** layout: Control panel (left, always visible,
    in a scroll area) | tabs Tuning/Capture/Config (middle) | plots column
    (right). Owns the single Sampler + 50 ms QTimer; top bar has connect +
    serial chooser + State/Result/Error + Disarm + Clear errors + bus/FET
    monitors. Status/diagnostics read every 5th tick.
  - `time_plot.py` — `TimePlot` (N named traces, per-trace color-key checkboxes,
    auto-Y, cursor, minimize) and **`FloatEdit`** (free-text numeric field used
    by the Tuning tab instead of spinboxes).
  - `control_panel.py` — state/mode, conversion (gear) factor, setpoint,
    set-current-position, motion shaping, and the **single** back-and-forth
    sequence (honors the configured input mode; does NOT force passthrough).
  - `tuning_panel.py` — all loop params (FloatEdit + checkboxes), debounced
    writes with read-back + revert, ∞ toggles, IDLE-gated Apply, diagnostics
    readout, and the collapsible Tuning guide (`_GUIDE_HTML`).
  - `capture_panel.py`, `config_panel.py`.

## Conventions & rules

- Keep all odrive/firmware specifics in `core/device.py`; other modules take a
  duck-typed `Device`. Panels must tolerate `set_device(None)` (disconnect).
- Verify headless: `QT_QPA_PLATFORM=offscreen python -m pytest` isn't set up as
  a suite, but changes are checked by an offscreen smoke script driving a
  `SimpleNamespace` fake ODrive. There is **no** hardware in CI.
- Numeric tuning fields are `FloatEdit` (typed text), not spinboxes.
- Every tuning write is read-back verified; never silently swallow write errors.
- Commit messages: `feat(py):` / `fix(py):` / `docs(py):` / `refactor(py):`.

## ODrive fw 0.6.x facts worth remembering

- `save_configuration()` **requires IDLE** and **reboots** the device (the sync
  call raises a lost-connection error = success). Gate on idle, tear down after.
- Current-loop PI gains are **derived** from `current_control_bandwidth` + R/L,
  not tuned directly. Tune inside-out: encoder bw → current → velocity → position.
- `pos_abs` is NaN without an absolute reference; position feedback falls back to
  `pos_estimate`/`pos_rel`.
- Error/procedure-result decode tables (`ODRIVE_ERRORS`, `PROCEDURE_RESULTS`) are
  in `core/device.py`; they prefer `odrive.enums` and warn if the device fw
  major.minor differs from the built-in table.

## Not yet hardware-verified

The serial chooser / `list_serials` (passive discovery), the native full-device
backup path, the 8 kHz capture plumbing, and the exact firmware attribute paths
have only been exercised against the fake. Confirm on a real 0.6.12+ ODrive.
