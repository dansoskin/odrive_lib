# odrive_lib

Portable **C library to control an ODrive** (Pro / S1, firmware 0.6.x) over
**CAN bus**. Hardware-agnostic, no HAL dependency, C99, no dynamic allocation —
designed to be dropped into an STM32 (or any MCU) firmware project as a **git
submodule**.

> The USB tuning GUI that used to live here now has its own repository:
> **[odrive_tuner](https://github.com/dansoskin/odrive_tuner)**.

## What it does

You give the library one **send callback** (transmit a CAN frame) and feed it
received frames via `odrive_on_can_rx()`. It builds the ODrive CANSimple frames
for you (setpoints, limits, trajectory limits, calibration state, etc.) and
decodes incoming feedback (position/velocity, Iq, temperature, bus V/I, torque,
errors, heartbeat) into a struct you read.

## Add it to your project (submodule)

```bash
git submodule add https://github.com/dansoskin/odrive_lib.git third_party/odrive_lib
```

Add to your build:
- **Include path:** `third_party/odrive_lib/include/`
- **Sources:** `src/odrive_comm.c`, `src/odrive_setpoints.c`,
  `src/odrive_control.c`, `src/odrive_feedback.c`

No other dependencies (`<stdint.h>`, `<string.h>`, `<math.h>` only).

## Minimal usage

```c
#include "odrive.h"

/* 1. Your CAN TX. Return true on success. rtr=true is a remote frame
 *    (the library uses it to request feedback getters). */
static bool my_send(void *ctx, uint32_t can_id,
                    const uint8_t *data, uint8_t len, bool rtr) {
    return my_can_transmit(ctx, can_id, data, len, rtr);
}

odrive_t od;
odrive_init(&od, my_send, /*ctx=*/&my_can, /*node_id=*/0,
            /*conversion=*/1.0f, /*invert=*/false);

/* 2. Command the motor */
odrive_set_closed_loop(&od, true);      /* arm (AxisState CLOSED_LOOP_CONTROL) */
odrive_set_input_vel(&od, 2.0f, 0.0f);  /* 2 turns/s, no torque feedforward   */

/* 3. In your CAN RX handler / poll loop, feed every received frame in.
 *    The library ignores frames whose node_id != this instance's. */
odrive_on_can_rx(&od, rx_id, rx_data, rx_len);

/* 4. Read decoded feedback anytime */
float p = od.feedback.pos_estimate;     /* converted to your units */
if (od.feedback.hb.axis_error) { /* handle */ }
```

## STM32 example

`examples/stm32_fdcan_canbus_wrapper.c` shows a complete wiring against STM32
**FDCAN** using [canbus_wrapper](https://github.com/dansoskin/canbus_wrapper):
adapting `can_send()` to the `odrive_send_fn` signature and pumping RX frames
from the ring buffer into `odrive_on_can_rx()`. The library itself never
touches the HAL — that glue lives entirely in your project, so it ports to
bxCAN, other MCUs, or a host-side test harness by writing one send function.

Typical integration:

```c
/* Adapt your CAN driver's send to the library's callback. */
static bool odrive_can_send(void *ctx, uint32_t id,
                            const uint8_t *d, uint8_t len, bool rtr) {
    uint8_t buf[8] = {0};
    if (d && len) memcpy(buf, d, len);
    return can_send((myCAN_t *)ctx, buf, len, id, rtr ? 1u : 0u) == HAL_OK;
}

/* Once, at startup */
odrive_init(&g_od, odrive_can_send, &g_bus, 0, 1.0f, false);

/* Periodically: request feedback, then pump RX */
odrive_request_encoder(&g_od);
while (can_data_in_buffer()) {
    can_rx_packet_t rx;
    if (!can_get_from_rbbuffer(&rx)) break;
    odrive_on_can_rx(&g_od, rx.header.Identifier, rx.data, rx_dlc_to_len(rx));
}
```

## API groups

| File | Functions |
|------|-----------|
| `odrive_comm.c` | `odrive_init`, `odrive_on_can_rx`, SDO read/write, callback registration, status string |
| `odrive_setpoints.c` | `odrive_set_input_pos` (+ff), `set_input_vel`, `set_input_torque`, absolute/relative position |
| `odrive_control.c` | axis state, controller mode, limits, trajectory limits, clear errors, estop, reboot |
| `odrive_feedback.c` | RTR request getters (encoder, Iq, temperature, bus V/I, torques, powers, version, error) |

Everything is declared in `include/odrive.h`; CAN command IDs and byte layouts
in `include/odrive_protocol.h`.

## Units

`conversion` + `invert` scale **position/velocity** setpoints and estimates.
`conversion=1.0, invert=false` uses native ODrive units (turns, turns/s).
**Torque (Nm) and gains are always raw.** With `invert=true`, position/velocity
are inverted but torque is not — in torque mode a positive torque acts opposite
to a positive velocity command.

`odrive_get_status_string()` uses `%f`, so on newlib-nano link with
`-u _printf_float`.

## Status

Hardware bring-up is pending; the library is written to be host-compilable and
the STM32 example is guarded so it only builds inside a project that provides
the HAL + canbus_wrapper. See `CLAUDE.md` for the development context.
