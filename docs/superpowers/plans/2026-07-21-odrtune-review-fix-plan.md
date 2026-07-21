# odrtune Review — Fix & Improvement Plan

**Date:** 2026-07-21
**Inputs:** external review (`odrtune_review_handoff.txt`, baseline fw 0.6.12 docs) + independent self-review of `tools/odrtune` + docs verification.
**App goal:** help the user tune an ODrive Pro/S1 to maximum performance, safely.

## Verification notes (what was checked before planning)

Confirmed against ODrive docs / firmware source:
- `vel_integrator_decay_gain` is a **saturation-time anti-windup decay**: while the
  velocity controller output is saturated, the accumulated integrator torque is
  multiplied by this value each control tick (firmware historically hardcoded
  `0.99`). Valid range ~0..1; **1.0 = no decay**, smaller = faster unwind. Our
  current tooltip ("bleeds when error is small, 0 disables") and range (0..1000)
  are **wrong**; values >1 would *amplify* windup.
- `controller.effective_torque_setpoint`, `controller.vel_integrator_torque`,
  `motor.effective_current_lim` all exist in the fw 0.6.x API — the reviewer's
  diagnostics suggestions are implementable.
- `axis.set_abs_pos()` is still the documented function; **no deprecation
  found**. The reviewer's suggested fallback (`axis.pos_estimate = value`) is
  unverified — do NOT adopt; keep `set_abs_pos` (verify on hardware).

Confirmed in our code:
- "Stop (0)" sends setpoint 0 in the active mode → in **position mode it
  commands a full-speed move to position 0**. Real motion-safety bug.
- Sequence **Stop only stops the timer** → in velocity mode the motor keeps
  spinning at the last A/B velocity. Worse than the reviewer stated.
- Sequence start doesn't set/restore `input_mode` → step shape depends on
  leftover mode (trap/filter/ramp).
- `config_io.backup()` stores only 3 gains; the Tuning tab edits ~25+ params.
- All writes fire on every `valueChanged` tick and exceptions are swallowed
  (`ControlPanel._guard`, `TuningPanel._apply`, `Device.set_tuning`).
- Sampling: 50 ms timer, ~15 sequential fibre reads per tick (+3 status reads)
  → ~20 Hz effective; unusable for current-loop dynamics (~1000 1/s).
- README overstates ("every control-loop parameter").

## Verdicts on the external review

**Agree (adopt as-is):** decay-gain semantics/range/hint; stop-semantics fix per
mode; sequence save/set PASSTHROUGH/restore + safe stop; backup schema v2;
write debounce + readback verification + surfaced errors; motor-model validity
flags; vel/overspeed limit group; torque + bus-current/power limits;
`effective_current_lim` / `effective_torque_setpoint` / `vel_integrator_torque`
diagnostics; FOC Id/Iq/err/mod diagnostics; report-filter params; unit fixes
(1/s not Hz); all individual hint corrections in §3 of the review; E-STOP →
"Software Disarm (Request IDLE)" + not-a-safety-device warning; guide rewrite
(limits-first diagnosis, their 11-step flow); capability detection; calibration
tab expansion; device/axis selection.

**Agree with modification:**
- *Priority:* the two motion-safety bugs (Stop-in-position-mode, sequence stop
  leaves motor running) outrank the decay-gain hint — they command unexpected
  motion today.
- *Backup:* implement schema v2 (testable, selective) AND offer ODrive's native
  host-side full backup (`odrive.configuration` backup/restore) as a separate
  "Full device backup" action; don't replace one with the other.
- *vel_integrator_gain formula:* the 0.5×bw×vel_gain rule is from ODrive's
  classic guide, not invented — but "bandwidth" is ambiguous for 0.6 and the
  current guidance is "start ≈ vel_gain"; drop the formula, keep "start equal,
  tune experimentally".
- *High-rate capture:* agree with the need; "use ODrive's native high-rate
  capture" is under-specified for fw 0.6 over fibre. Plan = investigate
  `InputMode.TUNING` + `controller.autotuning.*` (confirmed to exist) and any
  onboard capture facility; fallback = reduced-channel burst sampling with
  honest labeling of achievable rate.

**Disagree / do not adopt:**
- `set_abs_pos` deprecation + `pos_estimate =` fallback: unsupported by docs;
  keep `set_abs_pos()`.
- "20 Hz plots are not a tuning instrument at all" — overstated for the outer
  loops: position/velocity tuning at typical bandwidths is served by 20 Hz
  monitoring; the limitation is real specifically for the **current loop**.
  Keep live plots as primary for outer loops; add capture for current loop.

**Unverified — check on hardware/docs before implementing blindly:**
- Exact decay-gain edge behavior (0.0 = clear immediately?).
- "encoder_bandwidth also sets commutation estimator bandwidth when shared".
- `current_hard_max` re-arm delay behavior.
- Whether `commutation_encoder_bandwidth` is ignored when encoders are shared.

## Self-review findings the external review missed

1. **Sequence Stop leaves the motor running** (velocity mode) — must command a
   safe stop before restoring modes (covered in Phase 0).
2. Dwell changes while a sequence runs don't retime the QTimer.
3. `config.json` is rewritten on every conversion-spinbox tick (each arrow
   click = file write) — debounce/save on `editingFinished`.
4. `Device.feedback()` non-`_ref` reads are unguarded — one missing attribute
   (e.g. no `motor_thermistor` on some configs) kills all sampling. Guard every
   key like `_ref` and drop missing channels from the Sampler.
5. Status reads (`current_state`, errors) add 3 fibre round-trips per 50 ms
   tick — read them every Nth tick.
6. `Device.estop()` duplicates `set_closed_loop(False)` — merge after rename.
7. Calibration runner never completes if the axis exits calibration into
   CLOSED_LOOP instead of IDLE (edge case).
8. Error-decode table (`ODRIVE_ERRORS`) is still hardware-unverified (already
   tracked in memory).

---

## Plan (phases in implementation order)

### Phase 0 — Motion-safety hotfixes (do first)
**Files:** `ui/control_panel.py`, `ui/tuning_panel.py`, `core/device.py`, `ui/main_window.py`
1. **Stop button per mode:** position → hold current `pos` (write `input_pos =`
   current estimate) or Request IDLE; velocity → `input_vel = 0`; torque →
   `input_torque = 0`. Rename to "Stop (hold)".
2. **Sequence lifecycle:** on Start — save axis state, control mode, input
   mode; set `input_mode = PASSTHROUGH`; apply safe initial setpoint; arm. On
   Stop — stop timer; command mode-appropriate safe stop (0 vel / 0 torque /
   hold pos); restore saved modes only after safe.
3. **`vel_integrator_decay_gain`:** clamp range to 0.0–1.0; corrected tooltip
   (saturation decay, 1.0 disables).
4. **Rename E-STOP** → "Disarm (IDLE)"; tooltip: "Software disarm — not a
   hardware emergency stop; a physical safety circuit is still required."
5. `current_slew_rate_limit` minimum → strictly positive (0.001).

### Phase 1 — Write reliability (trustworthy parameter editing)
**Files:** `core/device.py`, `ui/tuning_panel.py`, `ui/control_panel.py`
1. Extend the float spec: `(key, label, suffix, decimals, min, max,
   allow_inf, requires_idle, read_only)`.
2. Write on `editingFinished`/debounce (~250 ms), not every `valueChanged`.
3. After each write: **read back**, compare, show ✓/error inline (statusbar or
   per-row marker); restore displayed value on failure; log the exception.
   `Device.set_tuning` returns per-key success instead of swallowing.
4. `requires_idle` + explicit Apply button for `phase_resistance`,
   `phase_inductance`, `current_hard_max` (+ warning text).
5. Debounce `config.json` saves; retime sequence QTimer if dwell changes.

### Phase 2 — Hints, units, guide corrections
**Files:** `ui/tuning_panel.py`, `README.md`
1. Apply every §3 hint correction from the external review verbatim where
   verified (decay gain, soft/hard current max, slew, FF enables and their
   fallback behavior, integrator limit [Nm], vel_limit + enable flags,
   inertia units [Nm/(turn/s²)], gain scheduling "experimental" + vel-error in
   velocity mode, flux linkage / Ld-Lq validity notes, input filter).
2. Units: label bandwidths **[1/s]** (not Hz/rad-s) to match the API.
3. Guide rewrite: limits-first diagnosis ("if it lags, check ramps/filters/
   current/torque/bus/velocity/modulation limits before raising gains"),
   buzzing diagnosis list, staged current-bandwidth warning, the 11-step
   PASSTHROUGH tuning flow; drop the 0.5×bw formula.
4. README: remove "every control-loop parameter" claim.

### Phase 3 — Parameter coverage for max tuning
**Files:** `core/device.py` (`_tuning_targets`), `ui/tuning_panel.py`
1. **Validity flags** (checkboxes beside their values):
   `phase_resistance_valid`, `phase_inductance_valid`,
   `ff_pm_flux_linkage_valid`, `motor_model_l_dq_valid`.
2. **Velocity & overspeed group:** `enable_vel_limit`,
   `enable_torque_mode_vel_limit`, `vel_limit_tolerance`,
   `enable_overspeed_error` (vel_limit already present; support Inf).
3. **Torque limits:** `axis.config.torque_soft_min/max` (signed fields).
4. **Bus limits:** `I_bus_soft_min/max`, `P_bus_soft_min/max` (signed).
5. **Report filters:** `motor.foc.I_measured_report_filter_k`,
   `config.motor.power_torque_report_filter_bandwidth`.
6. **Read-only diagnostics row(s):** `motor.effective_current_lim`,
   `controller.effective_torque_setpoint`, `controller.vel_integrator_torque`
   (live labels, greyed spinboxes or plain readouts).

### Phase 4 — Plotting improvements
**Files:** `core/device.py`, `core/sampler.py`, `ui/plots_column.py`, `ui/main_window.py`
1. Torque plot: add `effective_torque_setpoint` ("output") and optionally
   `vel_integrator_torque` ("integrator") traces.
2. Client-side **error traces** (pos_setpoint−pos, vel_setpoint−vel) — no extra
   USB reads; toggleable.
3. Optional **FOC diagnostics plot** (collapsed by default): `Id_setpoint`,
   `Id_measured`, `Ierr_d/q`, `mod_magn_sqr`, `effective_current_lim`.
4. Guard all `feedback()` reads with `_get`; auto-drop missing channels.
5. Stagger status reads (state/errors every ~5th tick); make sampled channel
   set adaptive (skip channels whose plots are collapsed) to raise the
   effective rate of the ones you're watching.
6. Label graphs explicitly as **motor-side** (turns, turns/s, Nm); optional
   setting to display pos/vel in load units using the Control-tab conversion.

### Phase 5 — Backup/restore that actually covers the app
**Files:** `core/config_io.py`, `ui/config_panel.py`
1. Schema v2: `{schema:2, serial, firmware, tuning: get_tuning(),
   motion: get_motion_config(), control_mode, input_mode}`.
2. Restore: firmware/serial compatibility check, show a **diff**, selective
   apply, explicit confirmation for current limits + motor model.
3. Optional "Full device backup/restore" via the host-side
   `odrive.configuration` utilities (whole config tree), as a separate action.

### Phase 6 — Capability & firmware handling
1. On connect: build a capability map (attribute presence probe once, not per
   write); mark unsupported fields "n/a (fw)" instead of silently grey.
2. Show fw version prominently; extend the existing error-decode fw warning
   pattern to parameter semantics where relevant.

### Phase 7 — Real current-loop tuning instruments
1. Investigate fw 0.6 capture options; implement **triggered burst capture**
   (max-rate reads of a minimal channel set with honest achieved-rate display)
   if no native scope is exposed.
2. **Built-in excitation:** `InputMode.TUNING` + `controller.autotuning.*`
   (frequency, pos/vel/torque amplitude) with amplitude/duration safety limits
   and start/stop; present as the deterministic alternative to the A/B
   sequence.
3. Sequence safety limits: max pos/vel/torque, test timeout, abort on any
   ODrive error.

### Phase 8 — Scope growth (after the above)
1. Device selector (serial) + axis selector (axis0/axis1).
2. Calibration tab: individual procedures (motor, encoder offset, index
   search), procedure result text, clear errors, save-after-calibration
   prompt; hall/harmonic/anticogging later under an "advanced" expander.
3. Advanced expander: field weakening (`fw_enable`, `fw_mod_setpoint`,
   `fw_fb_bandwidth`), spinout detection thresholds, dual-encoder options,
   encoder harmonic/off-axis compensation, anticogging workflow.

## Acceptance criteria
- Phase 0: no control in the app can command unintended motion; verified by
  headless tests driving each mode.
- Phase 1: a rejected write is visible in the UI and the display reverts;
  verified with a fake that raises/clamps.
- Phases 2–5: hints match verified docs; backup→wipe→restore round-trips every
  Tuning/Motion parameter on the fake.
- Phase 7: capture achieves a measured, displayed sample rate and the
  excitation mode arms/disarms safely.
- Everything remains headless-testable against the fake ODrive; hardware
  verification items stay tracked in the project memory.
