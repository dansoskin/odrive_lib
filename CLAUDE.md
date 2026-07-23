# CLAUDE.md — odrive_lib (C library)

Reference for AI coding sessions in this repo.

## What this repo is

A **portable C library** to control an ODrive (Pro / S1, firmware **0.6.x**)
over **CAN bus (CANSimple)**. It is consumed as a **git submodule** by external
STM32/MCU firmware projects. This repo is C-only — the USB tuning GUI lives in a
separate repo, **odrive_tuner** (https://github.com/dansoskin/odrive_tuner).

## Layout

```
include/odrive.h            # public API: odrive_t, odrive_status_t, feedback
                            #   struct, callback + send-fn typedefs, prototypes
include/odrive_protocol.h   # fw 0.6.x CANSimple command IDs, CAN-ID macro,
                            #   enums, little-endian pack/unpack helpers
src/odrive_comm.c           # init, send frame, RX decode/dispatch, SDO, status,
                            #   logger (odrive_set_logger/odrive_logf), fw check
src/odrive_setpoints.c      # input pos/vel/torque, absolute/relative position
src/odrive_control.c        # axis state, controller mode, limits, traj limits,
                            #   clear errors, estop, reboot
src/odrive_periodic.c       # set cyclic CAN message rates (per message) via SDO
src/odrive_endpoints_0_6.c  # GENERATED endpoint-id table (see tools/gen_endpoints.py)
src/odrive_feedback.c       # RTR request getters (encoder, Iq, temp, bus, ...)
tools/gen_endpoints.py      # flat_endpoints.json -> odrive_endpoints_0_6.{h,c}
test/                       # host smoke tests (bash test/run.sh, needs gcc)
examples/stm32_fdcan_canbus_wrapper.c   # HAL/canbus_wrapper glue (guarded out
                            #   of the host build with #ifdef ODRIVE_STM32_EXAMPLE)
docs/superpowers/           # design spec + implementation plans
```

## Design rules (keep these)

- **No HAL / no OS / no dynamic allocation.** C99. Depends only on
  `<stdint.h>`, `<string.h>`, `<math.h>`.
- **Hardware access is a callback**: `odrive_send_fn`
  `bool send(void *ctx, uint32_t can_id, const uint8_t *data, uint8_t len, bool rtr)`.
  The host project supplies it; the library never calls a CAN driver directly.
  `rtr=true` ⇒ remote frame, used by the feedback getters.
- **RX is fed in**: the host calls `odrive_on_can_rx(&od, id, data, len)` from
  its ISR / poll loop; the library filters by `node_id`, decodes into
  `od.feedback`, and fires optional per-message callbacks.
- **Return `odrive_status_t`**, never a HAL type, so the core stays portable and
  host-testable.
- **Units:** `conversion`/`invert` apply to position & velocity only; torque and
  gains are raw. Little-endian target assumed (compile-time guard in
  `odrive_protocol.h`).
- One concern per file; add new commands to the matching `src/*.c`.

## Firmware target

ODrive **fw 0.6.x** CANSimple. CAN arbitration id = `(node_id << 5) | cmd_id`.
Command IDs / payloads are in `odrive_protocol.h` (sourced from the ODrive
CANSimple DBC).

## Status / gotchas

- **Not yet verified on hardware.** Code is written to compile on a host; real
  verification happens at bring-up in a consuming project.
- The STM32 example needs the STM32 HAL + canbus_wrapper headers and is
  `#ifdef`-guarded so it is not part of a host compile.
- `odrive_get_status_string()` and `odrive_logf()` use `%f`/`vsnprintf` → need
  float-enabled printf.
- **Periodic message rates** are written by SDO endpoint id, which changes per
  firmware build. `src/odrive_endpoints_0_6.c` is GENERATED from a device's
  `flat_endpoints.json` via `tools/gen_endpoints.py`; the committed placeholder
  is all-zero (periodic calls return `ODRIVE_ERR_BAD_ARG` + log until generated).
- **Logger** is optional (clpf-style `void(*)(const char*)`, `NULL` disables).
  `odrive_init()` best-effort requests the fw version; a major/minor mismatch vs
  the endpoint table is logged once via the RX path (async — not in init).
- **Host tests:** `bash test/run.sh` (needs gcc); links `test/fake_endpoints.c`
  in place of the generated table.

## Conventions

- C: match surrounding style; keep files focused; commit messages
  `feat(c):` / `fix(c):` / `docs(c):`.
- Don't add the tuning GUI (odrtune) back here — it belongs in odrive_tuner.
  Small build/codegen scripts like `tools/gen_endpoints.py` are fine.
