# ODrive Control Library & USB Tuning Tool — Design

**Date:** 2026-07-20
**Status:** Approved (design phase)

## Overview

This repository provides two independent deliverables for working with ODrive
BLDC motor controllers (ODrive Pro / S1, firmware 0.6.x):

1. **A portable C library** for controlling an ODrive over **CAN bus**, designed
   to be consumed as a **git submodule** by multiple external projects (mostly
   STM32 MCUs). Hardware-agnostic core, no HAL dependency.
2. **A Python GUI tool (`odrtune`)** for **debugging and tuning** an ODrive over
   **USB**, built on the official `odrive` Python package.

The two deliverables are **fully independent** — no shared code or generated
files. Tuning results are saved to the ODrive's own non-volatile memory (NVM),
so the C library does not consume any tuning output at runtime.

### Constraints & context

- This repo is the submodule target; consuming firmware projects live elsewhere
  and are **not** part of this repo. Therefore the C library **cannot be tested
  against real firmware integration immediately** — verification of the C side
  is deferred to hardware bring-up in a consuming project.
- The existing `can_odrive.c` / `can_odrive.h` (author "omer") and the existing
  `canbus_wrapper` (https://github.com/dansoskin/canbus_wrapper) are prior art.
  We do a **clean redesign** keeping proven ideas (CAN-ID formation, decode
  logic, feedback struct, conversion factor) but not preserving exact names or
  the direct HAL/`canbus_wrapper` coupling.
- Target hardware/firmware: **ODrive Pro / S1, firmware 0.6.x** (fixes CAN
  command IDs and endpoint semantics).

---

## Part 1 — C CAN Library

### 1.1 Architecture & portability

- Hardware-agnostic **core** with **no HAL dependency**. Depends only on
  `<stdint.h>` / `<string.h>`. Language standard **C99**. No dynamic
  allocation, no global mutable state.
- Each drive is one `odrive_t` instance, holding:
  - a **send callback** + user context:
    `bool (*send)(void *ctx, uint32_t can_id, const uint8_t *data, uint8_t len, bool rtr)`
    (the `rtr`/remote-request flag lets getters request values via RTR frames;
    maps directly to `canbus_wrapper`'s `can_send(..., is_request)`)
  - `node_id` (0–63)
  - conversion factor + inversion flag (see §1.4)
  - a `feedback` struct (last-decoded values)
  - optional per-message callback function pointers (see §1.2)
- The core does **not** depend on `canbus_wrapper`. An **example** shows how a
  consuming STM32 project wires `canbus_wrapper`'s `can_send()` into the send
  callback and pumps received frames into the library.
- Single ODrive per `odrive_t` instance; the **caller routes** received frames.
  `odrive_on_can_rx()` filters by `node_id` and ignores non-matching frames.

### 1.2 Data flow

**TX (commands):**
- Build the payload (≤ 8 bytes), compute
  `can_id = (node_id << 5) | cmd_id`, call the send callback.
- **Fire-and-forget, non-blocking.** No blocking request/response.
- Return an `odrive_status_t` enum reflecting the callback result — never a HAL
  type.

**RX (feedback):**
- The consuming project calls
  `odrive_on_can_rx(odrive_t *od, uint32_t can_id, const uint8_t *data, uint8_t len)`
  from its CAN RX ISR or poll loop.
- The library extracts `node_id`; if it does not match this instance, the frame
  is ignored. Otherwise it decodes by command ID into `od->feedback` **and**
  fires the registered callback for that message type, if any.
- Callbacks run in the **caller's context** (often the RX ISR) and must be
  short. All callbacks are optional; polling `od->feedback` is always available.
  Callbacks are a strict superset of the polling model.

### 1.3 Command coverage (fw 0.6.x — full documented CAN set)

**Setpoints** (`odrive_setpoints.c`):
- `set_input_pos` (with velocity + torque feedforward)
- `set_input_vel`
- `set_input_torque`
- `set_absolute_position`
- `set_relative_pos` (convenience: last feedback position + delta)

**Config / control** (`odrive_control.c`):
- `set_axis_state` (idle, closed-loop control, calibration states)
- `set_controller_mode` (control mode + input mode)
- `set_limits` (velocity limit, current soft max)
- `set_pos_gain`
- `set_vel_gains` (vel gain, vel integrator gain)
- `set_traj_vel_limit`, `set_traj_accel_limits`, `set_traj_inertia`
- `clear_errors`, `estop`, `reboot`

**Feedback / getters** (`odrive_feedback.c`) — send an **RTR (remote-request)
frame** (zero-length, `rtr=true`); the ODrive replies with a data frame that
arrives later via RX and populates `feedback`/callbacks:
- encoder estimates (pos, vel), Iq (setpoint, measured), temperature,
  bus voltage/current, torques, powers, version, error (active errors +
  disarm reason), heartbeat (axis error/state/procedure result/traj-done).

**SDO** (`odrive_comm.c`):
- `read_sdo` / `write_sdo` for arbitrary endpoint IDs (arbitrary parameter
  access over CAN if ever required).

### 1.4 Units

- Per-instance **conversion factor + inversion**, applied to **position,
  velocity, and trajectory acceleration**: setters divide by the factor, getters
  multiply by it; inversion negates the factor.
- **Torque stays raw in Nm** (no conversion), matching the existing library.
- Default factor `1.0` / no inversion yields native ODrive units (turns,
  turns/s).

### 1.5 Error handling

- Public functions return `odrive_status_t` (e.g. `ODRIVE_OK`,
  `ODRIVE_ERR_SEND`, `ODRIVE_ERR_BAD_ARG`). No HAL types cross the API boundary,
  keeping the library portable and host-compilable.

### 1.6 File layout (modular, one concern per file)

```
include/
  odrive.h            # umbrella public header; odrive_t, odrive_status_t,
                      #   feedback struct, callback typedefs; includes the below
  odrive_protocol.h   # fw 0.6.x command IDs, CAN-ID macro, message byte layouts
src/
  odrive_comm.c       # init, build+send frame, SDO read/write,
                      #   odrive_on_can_rx() decode/dispatch, callback registration
  odrive_setpoints.c  # set_input_pos/vel/torque, absolute/relative position
  odrive_control.c    # axis_state, controller_mode, limits, pos/vel gains,
                      #   traj vel/accel/inertia, clear_errors, estop, reboot
  odrive_feedback.c   # getter request frames + decode helpers
examples/
  stm32_fdcan_canbus_wrapper.c  # wiring can_send() -> send callback + RX pump
```

Each `.c` compiles independently. A consuming project adds `src/*.c` and
`include/` to its build.

### 1.7 Verification (C side)

Per decision: **compile-check + manual bring-up only.** No test suite is built
now. A tiny host smoke-test target that links the sources and calls a few
command builders with a mock send callback confirms it compiles/links on a PC.
The send-callback architecture means full host unit tests (mock callback +
synthetic RX frames) can be added later without refactoring. Real verification
happens at hardware bring-up in a consuming project.

---

## Part 2 — Python USB Tuning/Debugging Tool (`odrtune`)

### 2.1 Stack

- **GUI:** PySide6 (Qt) with **pyqtgraph** for fast real-time scrolling plots.
- **Transport:** official **`odrive` Python package** over USB (object-tree
  access; the standard path for calibration/tuning/config).
- **Packaging:** `pyproject.toml`; launchable as `odrtune` or
  `python -m odrtune`. Python **3.10+**.

### 2.2 Internal structure

- `core/` — Qt-free logic: device scan/connect, parameter read/write,
  calibration sequencing, config backup/restore. Testable independently.
- `ui/` — Qt widgets/panels built on top of `core/`.

### 2.3 Features

- **Connect panel** — scan/select USB ODrive; show serial number, firmware
  version, connection status.
- **Live plots** — scrolling position, velocity, measured Iq/current,
  temperature, bus voltage.
- **Calibration wizard** — step through motor + encoder calibration
  `AxisState`s, show progress, surface errors/results.
- **Gain tuning** — live sliders for `pos_gain`, `vel_gain`,
  `vel_integrator_gain` (live-apply), plus a **step-response** test that
  commands a step and plots the response for tuning by eye.
- **Config** — backup config to JSON, restore from JSON, save to NVM
  (erase/save/reboot); error viewer + clear errors.

### 2.4 Verification (Python side)

Unlike the C library, the Python tool **can** be tested directly whenever an
ODrive is plugged in over USB — it is not blocked by the firmware-integration
constraint. "Done" = launches, connects, and all panels function against real
hardware. `core/` logic is structured to allow unit tests without hardware.

---

## Repository Layout

```
odrive_lib/
  include/   src/   examples/    # C library (this repo IS the git submodule)
  tools/odrtune/                 # Python package (pyproject.toml)
  docs/superpowers/specs/        # design docs
  README.md                      # usage for both deliverables
```

## Conventions / Defaults

- License: **MIT**.
- C library: **C99**, no dynamic allocation, no HAL dependency.
- Python tool: **Python 3.10+**, PySide6 + pyqtgraph + `odrive`.
- CAN arbitration ID: `(node_id << 5) | cmd_id`, node_id 0–63, cmd_id 0–31.

## Out of Scope (YAGNI)

- Blocking request/response CAN getters (non-blocking only).
- Multi-drive bus/registry routing layer (caller routes; single instance each).
- Shared code or generated artifacts between the C library and Python tool.
- Tuning over CAN (tuning is USB-only, by design).
- A C test suite now (deferred; architecture keeps it possible later).
