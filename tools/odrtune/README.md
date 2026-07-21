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
Click **Connect** (ODrive plugged in over USB). The **top bar** holds the connect
controls plus two small monitor graphs (bus voltage, FET temperature). Below,
the window is split: feature tabs on the **left**, a persistent **plots column
on the right** that stays visible on every tab. The plots column holds the
global **Window (s)** control and the four large graphs — position, velocity,
current (Iq), torque — each overlaying the **setpoint and measured** traces.

Left-hand tabs:
- **Control** — requested-state dropdown + live current-state readout; a control
  mode selector (Position/Velocity/Torque) that sets the ODrive mode and picks
  which setpoint is sent; a setpoint box (units follow the mode) with **Send**
  and an optional **live send**; a **Set current position** field (redefines the
  axis's absolute position — homing/zeroing); **Arm** / **Idle** / **Stop**
  shortcuts; and a **Motion shaping** group — an input-mode selector
  (Passthrough / Velocity ramp / Position filter / Trajectory / Torque ramp)
  with the ramp/acceleration fields relevant to the chosen mode (velocity ramp
  rate, trajectory vel/accel/decel limits, filter bandwidth, torque ramp rate).
- **Calibration** — run the full motor+encoder calibration and see the result.
- **Tuning** — adjust each control loop independently: **current** (bandwidth +
  soft current limit), **velocity** (gain, integrator gain, vel limit,
  integrator limit), **position** (gain); plus a position/velocity step-response
  test. Tune inner-to-outer: current → velocity → position.
- **Config** — backup/restore config JSON and save to the ODrive's NVM.

Each graph has a header showing its latest value(s) and two toggles: **auto Y**
(on by default — Y auto-scales to the data in the visible time window; turn off
to zoom Y by hand) and **cursor** (a crosshair that follows the mouse and reads
out time and value for measurement).

All graphs in the right column share one time axis and one sampling clock, so
they stay aligned when you pan/zoom or change the window span. The step-response
graph on the Tuning tab is a separate event-triggered capture and is not linked
to the live time axis.

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
