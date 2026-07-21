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
Click **Connect** (ODrive plugged in over USB). A persistent **top panel**
(visible on every tab) shows the requested-state and control-mode dropdowns, a
live current-state readout, a global **Window (s)** control for the graph time
span, and two small monitor graphs (bus voltage, FET temperature).

Then use the tabs:
- **Plots** — large graphs for position, velocity, current (Iq) and torque, each
  overlaying the **setpoint and measured** traces.
- **Calibration** — run the full motor+encoder calibration and see the result.
- **Tuning** — live gain sliders (pos/vel/vel-integrator) + position step response.
- **Config** — backup/restore config JSON and save to the ODrive's NVM.

All live graphs (top panel + Plots tab) share one time axis and one sampling
clock, so they stay aligned when you pan/zoom or change the window span. The
step-response graph on the Tuning tab is a separate event-triggered capture and
is not linked to the live time axis.

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
