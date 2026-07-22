# odrtune

USB debugging and tuning GUI for ODrive Pro/S1 (firmware 0.6.x). Independent of
the CAN C library in this repo.

## Install
```bash
cd tools/odrtune
python -m pip install -r requirements.txt
```

## Run
```bash
cd tools/odrtune
python __main__.py        # or, from the repo root: python tools/odrtune
```
Click **Connect** (ODrive plugged in over USB); the button then becomes
**Disconnect** (releases the USB handle and disables the tabs — it does *not*
disarm the motor, so anything you left running keeps running; click **Connect**
again to reattach). The **top bar** holds the connect
controls, a live **driver state + result + error** readout (a **Result:** line
shows the axis `procedure_result` decoded to a name — e.g. a closed-loop request
on an uncalibrated axis stays in `Idle` and shows `Result: NOT_CALIBRATED`,
highlighted when it is anything other than `SUCCESS`; the error shows both the
raw hex bitfield and decoded names, e.g. `0x1000 (CURRENT_LIMIT_VIOLATION)`; the
decode table targets fw 0.6.x and appends a warning if the connected firmware's
major.minor differs), a **Disarm (IDLE)** button (software disarm — requests
IDLE; this is *not* a hardware emergency stop, and a physical safety circuit is
still required), a **Clear errors** button (device-level `clear_errors`; also
re-arms the brake resistor and clears a stale procedure result), and two small
monitor graphs (bus voltage, FET temperature).
Below,
the window is split: feature tabs on the **left**, a persistent **plots column
on the right** that stays visible on every tab. The plots column holds the
global **Window (s)** control, a **Pause** toggle (freezes sampling so you can
inspect — pan/zoom/cursor still work), and the four large graphs — position,
velocity, current (Iq), torque. Titles name the **motor frame** explicitly
(motor turns, motor turns/s, Nm motor). Each overlays several traces: **actual**
(measured), **target** (the raw command you gave, e.g. `input_pos`), and
**ideal** (the controller's effective setpoint right now, e.g.
`controller.pos_setpoint` — where the motor *should* be after ramps/filtering/
trajectory). Position and velocity add an **error** trace (ideal − actual,
computed client-side, hidden by default). Torque adds **output**
(`effective_torque_setpoint`, the final request after all limiting) and
**integrator** (`vel_integrator_torque`, hidden by default). Current shows
actual + command (`Iq_setpoint`). Traces hidden by default (error, integrator)
have their per-trace checkbox unchecked; tick it to show them.

Left-hand tabs:
- **Control** — requested-state dropdown; a control mode selector
  (Position/Velocity/Torque) that sets the ODrive mode and picks which setpoint
  is sent; a **Conversion** (gear/units) factor — position/velocity setpoints are
  multiplied by it before sending (`driver_revs = your_value × conversion`, e.g. a
  1:3 gear → enter 3; `1` = no conversion; torque stays raw; persisted to
  `~/.odrtune/config.json`); a setpoint box with
  **Send** and an optional **live send**; a **Set current position** field (redefines the
  axis's absolute position — homing/zeroing); **Arm** / **Idle** /
  **Stop (hold)** shortcuts (Stop commands a mode-appropriate safe stop while
  leaving the axis armed: position mode *holds the current position*, velocity
  mode commands zero speed, torque mode zero torque); and a **Motion shaping**
  group — an input-mode selector
  (Passthrough / Velocity ramp / Position filter / Trajectory / Torque ramp)
  with the ramp/acceleration fields relevant to the chosen mode (velocity ramp
  rate, trajectory vel/accel/decel limits, filter bandwidth, torque ramp rate);
  and a **Back-and-forth** sequence (points A/B + dwell) that drives the motor
  in the *currently configured input mode* — unlike the Tuning-tab sequence
  (which forces Passthrough for clean steps), this one honors your ramp /
  trajectory / filter so you can inspect the shaped motion on the graphs.
- **Calibration** — run the full motor+encoder calibration and see the result.
- **Tuning** — adjust the key control-loop parameters independently, grouped
  inner-to-outer (scrollable): a **Diagnostics** readout at the top (live
  read-only effective current limit, effective torque setpoint, and velocity
  integrator torque), then **feedback** (encoder + commutation-encoder
  bandwidth), **current loop** (bandwidth, soft/hard current max, current slew
  limit), **current feedforward** (cross-coupling wL, back-EMF, dI/dt enables for
  high-speed tracking), **velocity loop** (gain, integrator gain + limit + decay,
  vel limit), **velocity & overspeed limits** (enforce vel limit, torque-mode vel
  limit, tolerance, overspeed error), **torque & bus limits** (signed torque and
  DC bus current/power soft clamps, each with a ±∞ disable toggle), **position
  loop** (gain, inertia accel-FF), **gain scheduling** (enable + width + min
  ratio), **motor model** (torque constant, phase R/L, PM flux linkage, model
  L_d/L_q + their validity flags — normally from calibration), and **report
  filtering** (reported-only Iq/Id and power/torque filter settings that do not
  affect control). Plus a
  **back-and-forth sequence** (drive the motor between points A and B at a set
  dwell) so you can watch the repeated step on the right-hand graphs while you
  adjust gains — this one **forces Passthrough** for clean step responses (the
  Control-tab sequence keeps your input mode instead). A collapsible **Tuning
  guide** at the top gives a full inside-out walkthrough. Tune inner-to-outer:
  feedback → current (+FF) → velocity →
  position. Parameters your firmware doesn't expose are shown disabled. Edits are
  debounced and every write is **verified by read-back** (a status line shows
  `key ✓` or the read-back mismatch, and the field reverts on failure); a few
  fields that change low-level current measurement (phase R/L, current hard max)
  require the axis in **IDLE** and an explicit **Apply**, and fields that accept
  infinity (vel limit, integrator limit, torque/bus soft limits) have an **∞**
  toggle (min-side limits write −∞ instead). **Hover
  any field** for a hint on what it does and how it affects the loop, and expand
  the collapsible **Tuning guide** at the top for ODrive's guidelines plus tips.
- **Capture** — record signals at the native **8 kHz** control-loop rate using
  the ODrive's **onboard oscilloscope** (the live graphs only reach ~20 Hz, too
  coarse for current-loop tuning). Pick a **preset** (current loop Iq, current
  D/Q, current error + modulation, velocity loop, position loop, torque) or type
  any comma-separated property paths; choose the **trigger point** (0..1: where
  in the window the trigger sits — the recording also auto-triggers if the axis
  enters IDLE, e.g. on an error) and a **timeout**. Optionally **apply a step**
  (torque Nm / velocity turns/s) during the capture to see the loop response
  (*the motor moves* — the amplitude is restored and the axis returned to its
  prior mode/state afterwards). The result is plotted on its own millisecond time
  base (trigger at 0) with one curve per property, a header showing the sample
  count and window length, and an **Export CSV…** button. Requires firmware
  **0.6.12+** (older firmware lacks the feature or has a trigger-point hang bug);
  a banner reports availability. Live graphs pause during a capture because it
  needs the full USB bandwidth.
- **Config** — backup/restore config JSON and save to the ODrive's NVM.
  **Backup** writes a schema-2 snapshot (every Tuning parameter + motion shaping
  + control mode, plus device serial/firmware; ±∞ values are preserved).
  **Restore** diffs the snapshot against the live device and shows a
  **selective-apply dialog**: only *changed* items appear as checkboxes
  (`key: current → target`); firmware/serial mismatches are flagged at the top
  as (non-blocking) warnings; current-limit and motor-model parameters are
  gated in a separate **Sensitive** section that is **unchecked by default**
  and warns that wrong values can damage hardware. A second row offers ODrive's
  host-side **native full backup/restore** of the whole device config tree
  (needs the `odrive` package + a real device; unavailable otherwise).

Each graph has a header showing its latest value(s) and three controls: **auto Y**
(on by default — Y auto-scales to the data in the visible time window; turn off
to zoom Y by hand), **cursor** (a crosshair that follows the mouse and reads out
time and value for measurement), and a **–/+** minimize button that collapses the
graph to just its header (latest value still visible) so it takes no space.
Multi-trace graphs additionally show one small **per-trace checkbox** (e.g.
`actual` / `target` / `ideal`) next to the title, checked by default —
unchecking hides that trace and drops it from the latest-value readout. Each
checkbox label is colored to match its trace's line, so the checkboxes double as
the color key (there is no separate clickable plot legend).

Note on the Position graph: it plots the **absolute** position (`pos_abs`) — the
frame the controller and `input_pos`/`Set current position` operate in — so
homing/zeroing is reflected on the graph.

Tuning changes are applied **live in RAM**; use **Config → Save to NVM** to keep
them across power cycles.

All graphs in the right column share one time axis and one sampling clock, so
they stay aligned when you pan/zoom or change the window span.

## Layout
```
tools/odrtune/
  __main__.py   # entry point (launches the Qt app)
  core/         # Qt-free ODrive logic (device, config_io, sampler,
                #   calibration, step_response)
  ui/           # PySide6 panels + main window
```
`core/` isolates all firmware-specific ODrive attribute paths in `core/device.py`,
so a firmware tweak touches one file.
