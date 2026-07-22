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
controls, a live **driver state + error** readout (the error shows both the raw
hex bitfield and decoded names, e.g. `0x1000 (CURRENT_LIMIT_VIOLATION)`; the
decode table targets fw 0.6.x and appends a warning if the connected firmware's
major.minor differs), a **Disarm (IDLE)** button (software disarm — requests
IDLE; this is *not* a hardware emergency stop, and a physical safety circuit is
still required), and two small monitor graphs (bus voltage, FET temperature).
Below,
the window is split: feature tabs on the **left**, a persistent **plots column
on the right** that stays visible on every tab. The plots column holds the
global **Window (s)** control, a **Pause** toggle (freezes sampling so you can
inspect — pan/zoom/cursor still work), and the four large graphs — position,
velocity, current (Iq), torque. Each overlays up to three traces: **actual**
(measured), **target** (the raw command you gave, e.g. `input_pos`), and
**ideal** (the controller's effective setpoint right now, e.g.
`controller.pos_setpoint` — where the motor *should* be after ramps/filtering/
trajectory). Current shows actual + command (`Iq_setpoint`).

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
  rate, trajectory vel/accel/decel limits, filter bandwidth, torque ramp rate).
- **Calibration** — run the full motor+encoder calibration and see the result.
- **Tuning** — adjust every control-loop parameter independently, grouped
  inner-to-outer (scrollable): **feedback** (encoder + commutation-encoder
  bandwidth), **current loop** (bandwidth, soft/hard current max, current slew
  limit), **current feedforward** (cross-coupling wL, back-EMF, dI/dt enables for
  high-speed tracking), **velocity loop** (gain, integrator gain + limit + decay,
  vel limit), **position loop** (gain, inertia accel-FF), **gain scheduling**
  (enable + width + min ratio), and **motor model** (torque constant, phase R/L,
  PM flux linkage, model L_d/L_q — normally from calibration). Plus a
  **back-and-forth sequence** (drive the motor between points A and B at a set
  dwell) so you can watch the repeated step on the right-hand graphs while you
  adjust gains. Tune inner-to-outer: feedback → current (+FF) → velocity →
  position. Parameters your firmware doesn't expose are shown disabled. **Hover
  any field** for a hint on what it does and how it affects the loop, and expand
  the collapsible **Tuning guide** at the top for ODrive's guidelines plus tips.
- **Config** — backup/restore config JSON and save to the ODrive's NVM.

Each graph has a header showing its latest value(s) and three controls: **auto Y**
(on by default — Y auto-scales to the data in the visible time window; turn off
to zoom Y by hand), **cursor** (a crosshair that follows the mouse and reads out
time and value for measurement), and a **–/+** minimize button that collapses the
graph to just its header (latest value still visible) so it takes no space.
Multi-trace graphs additionally show one small **per-trace checkbox** (e.g.
`actual` / `target` / `ideal`) next to the title, checked by default —
unchecking hides that trace and drops it from the latest-value readout.

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
