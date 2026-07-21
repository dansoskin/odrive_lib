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
Click **Connect** (ODrive plugged in over USB), then use the tabs:
- **Plots** — live pos/vel/Iq/temp/bus-voltage.
- **Calibration** — run the full motor+encoder calibration and see the result.
- **Tuning** — live gain sliders (pos/vel/vel-integrator) + position step response.
- **Config** — backup/restore config JSON and save to the ODrive's NVM.

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
