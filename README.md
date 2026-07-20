# odrive_lib

Portable C library to control an ODrive Pro/S1 (firmware 0.6.x) over CAN bus,
plus a Python USB tuning tool (`tools/odrtune`). This repo is designed to be
used as a **git submodule** in firmware projects.

## C library (CAN)

Hardware-agnostic. No HAL dependency. C99. You supply a send callback and feed
received frames in.

### Files to add to your build
- Include path: `include/`
- Sources: `src/odrive_comm.c`, `src/odrive_setpoints.c`,
  `src/odrive_control.c`, `src/odrive_feedback.c`

### Minimal usage
```c
#include "odrive.h"

static bool my_send(void *ctx, uint32_t id, const uint8_t *d, uint8_t len, bool rtr) {
    /* transmit a CAN frame on your hardware; return true on success */
}

odrive_t od;
odrive_init(&od, my_send, my_bus_ctx, /*node_id=*/0, /*conv=*/1.0f, /*invert=*/false);
odrive_set_closed_loop(&od, true);
odrive_set_input_vel(&od, 2.0f, 0.0f);

/* in your CAN RX path: */
odrive_on_can_rx(&od, rx_id, rx_data, rx_len);
float pos = od.feedback.pos_estimate;
```

See `examples/stm32_fdcan_canbus_wrapper.c` for wiring to
[canbus_wrapper](https://github.com/dansoskin/canbus_wrapper) on STM32 FDCAN.

### Units
`conversion` + `invert` scale position/velocity setpoints and estimates.
`conv=1.0, invert=false` uses native ODrive units (turns, turns/s). Torque
(Nm) and gains are always raw.

## Python tuning tool

See `tools/odrtune/` (USB, PySide6). Independent of the C library.
