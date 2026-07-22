# odrtune

**Standalone USB debugging and tuning GUI for ODrive** (Pro / S1, firmware
0.6.x). PySide6 + pyqtgraph, talking to the drive over USB via the official
`odrive` Python package. (The CAN control **C library** for embedding in
firmware is a separate project:
[odrive_lib](https://github.com/dansoskin/odrive_lib).)

If you've never tuned an ODrive: jump to **[Tuning process](#tuning-process)**
below — the same walkthrough is in the app's collapsible *Tuning guide*.

## Install
```bash
python -m pip install -r requirements.txt   # PySide6, pyqtgraph, odrive
```

## Run
```bash
python __main__.py        # or:  python -m __main__   from this folder
```

Pick the target ODrive with the **Serial** chooser (blank = first available;
**Scan** lists connected serials). To drive **two ODrives at once**, launch the
app twice and pick a different serial in each. Click **Connect**; the button
becomes **Disconnect** (releases the USB handle and disables the tabs — it does
*not* disarm the motor; click **Connect** again to reattach). The **top bar**
holds the connect
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
the window is split into **three columns**: the **Control** panel on the
**left** (always visible), the feature **tabs** (Tuning / Capture / Config) in
the **middle**, and a persistent **plots column on the right** that stays
visible at all times. The plots column holds the
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

Panels:
- **Control** (left, always visible) — requested-state dropdown (includes
  **Full calibration**, so motor+encoder calibration runs from here); a control mode selector
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
  in the *currently configured input mode*, honoring your ramp / trajectory /
  filter so you can inspect the shaped motion on the graphs (set **Passthrough**
  for clean step responses while tuning).
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
  affect control). Drive the motor with the **back-and-forth sequence in the
  Control panel** (left, always visible) and watch the repeated step on the
  right-hand graphs while you adjust these gains. A collapsible **Tuning
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
  (needs the `odrive` package + a real device; unavailable otherwise), plus a
  **Reboot device** button (reboots the ODrive; the USB link drops and the app
  releases the device, so you'll need to reconnect).

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

Note on the Position graph: "actual" is the first finite of
`axis.pos_estimate` → `pos_vel_mapper.pos_abs` → `pos_rel`, so it always shows a
real number (a plain incremental axis reads relative-to-boot; `pos_abs` is used
once the axis has a valid absolute reference / is homed).

Tuning changes are applied **live in RAM**; use **Config → Save to NVM** to keep
them across power cycles.

All graphs in the right column share one time axis and one sampling clock, so
they stay aligned when you pan/zoom or change the window span.

## Layout
```
__main__.py   # entry point (launches the Qt app)
core/         # Qt-free ODrive logic (device, config_io, sampler, capture)
ui/           # PySide6 panels + main window
```
`core/` isolates all firmware-specific ODrive attribute paths in `core/device.py`,
so a firmware tweak touches one file. Calibration is run from the Control
panel's requested-state dropdown ("Full calibration").

## Tuning process

The same guide is in the app (collapsible **Tuning guide** at the top of the
Tuning tab). Tune **from the inside out** — each inner loop must be solid before
the outer one:

> feedback → current → velocity → position → then feedforward / shaping.

The motor **will move** during tuning — keep it free to spin and keep the
top-bar **Disarm (IDLE)** within reach.

**Which tool does what**
- **Control panel** (left, always visible) — command the motor: mode, setpoint,
  and the **Back-and-forth** sequence (A↔B) that drives repeated steps in the
  input mode you configured. Set **Passthrough** here for clean step responses.
- **Tuning tab** (middle) — every loop parameter, grouped inner-to-outer, with
  live read-back verification.
- **Capture tab** (middle) — 8 kHz onboard-scope capture; the only tool fast
  enough to see the current loop.
- **Right-hand graphs** — actual vs target vs ideal; use **Pause** to inspect a
  step. *ideal* is what the controller commands each instant; *actual* should
  track it with minimal lag and no ringing.

**0. Prerequisites.** Run **Full calibration** (Control → requested state). You
need valid phase R/L, flux linkage and encoder offset; confirm the top bar
shows `Result: SUCCESS` (use **Clear errors** if needed). Set safe limits:
`current_soft_max`/`current_hard_max`, `vel_limit`, and a correct
`torque_constant` (≈ 8.27 / KV).

**1. Feedback — `encoder_bandwidth`.** Match your encoder: high-resolution
encoders tolerate high values; hall sensors need low (~10–100). It filters the
estimate and *caps* how high the loop gains can go, so set it first.

**2. Current (torque) loop.** You do **not** hand-tune the current PI gains —
ODrive derives them from `current_control_bandwidth` + phase R/L (default
~1000 is fine). **Verify** in the Capture tab (*Current loop (Iq)* preset + a
small torque step): `Iq_measured` should track `Iq_setpoint` with a fast rise,
little overshoot, no ringing. Raise the bandwidth only gradually and only if
R/L are trustworthy, re-capturing each time; stop at the first
overshoot/ringing/noise.

**3. Velocity loop.** Control mode **Velocity**, input mode **Passthrough**.
Set `vel_integrator_gain = 0`; raise `vel_gain` ~30%/step until you hear whine /
see vibration, then back off to ~half. Then raise `vel_integrator_gain` (start
near `vel_gain`) until a step is slightly underdamped, then halve it. Drive
steps with the Control-panel **Back-and-forth** sequence and compare actual vs
ideal.

**4. Position loop.** Sequence → Position. Raise `pos_gain` until a step just
begins to overshoot/ring, then back off until it stops. (Position loop is
P-only; its output is a velocity command clamped by `vel_limit`.)

**5. Feedforward & shaping (last).** `inertia` (accel FF) for fast moves;
current feedforward (`wL`/`bEMF`/`dI_dt`) for high-speed current tracking;
command shaping (ramp / trajectory / filter) in the Control tab; gain
scheduling if high gains buzz at standstill.

**Diagnosis.** If the response lags, first rule out an active limit (current,
torque, bus, velocity, modulation) before raising gains. Buzzing: find the cause
(too-high gains, encoder noise, mechanical resonance, commutation error,
current-loop instability) — lower encoder bandwidth only if estimator noise is
it. A rejected closed-loop request stays in `Idle` with e.g.
`Result: NOT_CALIBRATED`.

**Finish.** Changes are live in RAM. **Disarm**, then **Config → Save to NVM**
(the drive reboots and disconnects — reconnect to verify).

> Verification note: this app has been developed and tested headless (against a
> simulated ODrive tree); the exact firmware attribute paths and the starting
> values above are ODrive's conventional rules of thumb — confirm against your
> hardware and firmware.

