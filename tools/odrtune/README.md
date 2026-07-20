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
