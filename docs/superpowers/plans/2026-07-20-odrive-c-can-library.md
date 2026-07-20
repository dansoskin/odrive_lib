# ODrive C CAN Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable, hardware-agnostic C library that controls an ODrive Pro/S1 (firmware 0.6.x) over CAN bus, consumable as a git submodule by external STM32 projects.

**Architecture:** A single `odrive_t` instance per drive holds a user-supplied send callback (`send(ctx, can_id, data, len, rtr)`), a `node_id`, a conversion factor + inversion, a feedback struct, and optional per-message callbacks. Commands build payloads and call the send callback (fire-and-forget). Incoming frames are pushed in by the host via `odrive_on_can_rx()`, which filters by node_id, decodes into the feedback struct, and fires any registered callback. No HAL dependency; C99; no dynamic allocation.

**Tech Stack:** C99, `<stdint.h>`/`<string.h>`/`<math.h>` only. Host build for a compile/link smoke check uses gcc/clang. STM32 integration shown as an example wiring the existing `canbus_wrapper`.

**Testing note (deviation from default TDD):** The approved spec chose *compile-check + manual bring-up* for the C side (real verification happens at hardware bring-up in a consuming project, which is out of this repo). So instead of per-function failing-test TDD, each module task ends with a **host compile/link smoke check** plus a few sanity assertions on byte encodings against a mock callback. This is intentional and overrides the skill's default TDD flow. The send-callback design keeps full host unit tests addable later without refactoring.

**Protocol reference (fw 0.6.x, from ODrive CANSimple DBC):**
- CAN arbitration ID = `(node_id << 5) | cmd_id`, node_id 0–63, cmd_id 0–31.
- Command IDs and payloads used below:

| Cmd | ID | Payload |
|-----|----|---------|
| Get_Version | 0x00 | (RTR req) resp: proto u8, hw_maj/min/var u8, fw_maj/min/rev u8, unreleased u8 |
| Heartbeat | 0x01 | axis_error u32, axis_state u8, procedure_result u8, traj_done u8 |
| Estop | 0x02 | (none) |
| Get_Error | 0x03 | (RTR req) resp: active_errors u32, disarm_reason u32 |
| RxSdo | 0x04 | opcode u8, endpoint u16, reserved u8, value u32 |
| TxSdo | 0x05 | reserved u8, endpoint u16, reserved u8, value u32 |
| Set_Axis_State | 0x07 | axis_requested_state u32 |
| Get_Encoder_Estimates | 0x09 | (RTR req) resp: pos f32 (rev), vel f32 (rev/s) |
| Set_Controller_Mode | 0x0B | control_mode u32, input_mode u32 |
| Set_Input_Pos | 0x0C | input_pos f32 (rev), vel_ff i16 (×0.001 rev/s), torque_ff i16 (×0.001 Nm) |
| Set_Input_Vel | 0x0D | input_vel f32 (rev/s), input_torque_ff f32 (Nm) |
| Set_Input_Torque | 0x0E | input_torque f32 (Nm) |
| Set_Limits | 0x0F | velocity_limit f32 (rev/s), current_limit f32 (A) |
| Set_Traj_Vel_Limit | 0x11 | traj_vel_limit f32 (rev/s) |
| Set_Traj_Accel_Limits | 0x12 | accel_limit f32, decel_limit f32 (rev/s²) |
| Set_Traj_Inertia | 0x13 | traj_inertia f32 |
| Get_Iq | 0x14 | (RTR req) resp: iq_setpoint f32, iq_measured f32 (A) |
| Get_Temperature | 0x15 | (RTR req) resp: fet_temp f32, motor_temp f32 (°C) |
| Reboot | 0x16 | action u8 (0=reboot,1=save_config,2=erase_config) |
| Get_Bus_Voltage_Current | 0x17 | (RTR req) resp: bus_voltage f32 (V), bus_current f32 (A) |
| Clear_Errors | 0x18 | (none) |
| Set_Absolute_Position | 0x19 | position f32 (rev) |
| Set_Pos_Gain | 0x1A | pos_gain f32 |
| Set_Vel_Gains | 0x1B | vel_gain f32, vel_integrator_gain f32 |
| Get_Torques | 0x1C | (RTR req) resp: torque_target f32, torque_estimate f32 (Nm) |
| Get_Powers | 0x1D | (RTR req) resp: electrical_power f32, mechanical_power f32 (W) |

- **Endianness:** ODrive and STM32/x86 hosts are all little-endian; `memcpy` of f32/u32/i16 into/out of the little-endian byte buffer is used throughout (documented assumption).
- **Unit conversion:** `motor_conv` (with sign for inversion) applied to **position & velocity setpoints/estimates** (setters divide, decode multiplies). Trajectory/limit *magnitudes* (vel limit, accel/decel) divide by `fabsf(motor_conv)`. **Torque and gains stay raw** (no conversion).

**File structure:**
- Create: `include/odrive_protocol.h` — command IDs, CAN-ID macro, enums, `static inline` pack/unpack helpers. No dependency on `odrive_t`.
- Create: `include/odrive.h` — `odrive_status_t`, `odrive_heartbeat_t`, `odrive_feedback_t`, callback typedef, send-callback typedef, `odrive_t`, all public prototypes, and the internal `odrive__send` prototype.
- Create: `src/odrive_comm.c` — init, `odrive__send`, `odrive_on_can_rx` decode/dispatch, callback registration, SDO read/write, `odrive_get_status_string`.
- Create: `src/odrive_setpoints.c` — input pos/vel/torque, absolute/relative position.
- Create: `src/odrive_control.c` — axis state, controller mode, limits, gains, trajectory params, clear errors, estop, reboot.
- Create: `src/odrive_feedback.c` — RTR request functions for all getters.
- Create: `examples/stm32_fdcan_canbus_wrapper.c` — reference adapter wiring `canbus_wrapper`'s `can_send` into the send callback + RX pump (guarded so the host build skips it).
- Create: `test/smoke_test.c` — mock send callback + encoding assertions + link check.
- Create: `test/Makefile` — host build of `src/*.c` + smoke test.
- Create: `README.md` (repo root) — updated with C library usage + submodule integration.

---

### Task 1: Protocol header (command IDs, CAN-ID macro, enums, pack/unpack helpers)

**Files:**
- Create: `include/odrive_protocol.h`

- [ ] **Step 1: Write `include/odrive_protocol.h`**

```c
/* odrive_protocol.h - ODrive fw 0.6.x CANSimple command IDs and byte helpers.
 * No dependency on odrive_t; safe to include anywhere. */
#ifndef ODRIVE_PROTOCOL_H_
#define ODRIVE_PROTOCOL_H_

#include <stdint.h>
#include <string.h>

/* CAN arbitration ID = (node_id[5:0] << 5) | cmd_id[4:0] */
#define ODRIVE_CAN_ID(node_id, cmd) \
    ((((uint32_t)(node_id) & 0x3Fu) << 5) | ((uint32_t)(cmd) & 0x1Fu))
#define ODRIVE_ID_NODE(can_id) (((can_id) >> 5) & 0x3Fu)
#define ODRIVE_ID_CMD(can_id)  ((can_id) & 0x1Fu)

/* Command IDs */
#define ODRIVE_CMD_GET_VERSION            0x00u
#define ODRIVE_CMD_HEARTBEAT              0x01u
#define ODRIVE_CMD_ESTOP                  0x02u
#define ODRIVE_CMD_GET_ERROR              0x03u
#define ODRIVE_CMD_RXSDO                  0x04u
#define ODRIVE_CMD_TXSDO                  0x05u
#define ODRIVE_CMD_SET_AXIS_STATE         0x07u
#define ODRIVE_CMD_GET_ENCODER_ESTIMATES  0x09u
#define ODRIVE_CMD_SET_CONTROLLER_MODE    0x0Bu
#define ODRIVE_CMD_SET_INPUT_POS          0x0Cu
#define ODRIVE_CMD_SET_INPUT_VEL          0x0Du
#define ODRIVE_CMD_SET_INPUT_TORQUE       0x0Eu
#define ODRIVE_CMD_SET_LIMITS             0x0Fu
#define ODRIVE_CMD_SET_TRAJ_VEL_LIMIT     0x11u
#define ODRIVE_CMD_SET_TRAJ_ACCEL_LIMITS  0x12u
#define ODRIVE_CMD_SET_TRAJ_INERTIA       0x13u
#define ODRIVE_CMD_GET_IQ                 0x14u
#define ODRIVE_CMD_GET_TEMPERATURE        0x15u
#define ODRIVE_CMD_REBOOT                 0x16u
#define ODRIVE_CMD_GET_BUS_VOLTAGE_CURRENT 0x17u
#define ODRIVE_CMD_CLEAR_ERRORS           0x18u
#define ODRIVE_CMD_SET_ABSOLUTE_POSITION  0x19u
#define ODRIVE_CMD_SET_POS_GAIN           0x1Au
#define ODRIVE_CMD_SET_VEL_GAINS          0x1Bu
#define ODRIVE_CMD_GET_TORQUES            0x1Cu
#define ODRIVE_CMD_GET_POWERS             0x1Du

/* Axis states (ODrive AxisState enum, fw 0.6.x) */
typedef enum {
    ODRIVE_AXIS_STATE_UNDEFINED             = 0,
    ODRIVE_AXIS_STATE_IDLE                  = 1,
    ODRIVE_AXIS_STATE_STARTUP_SEQUENCE      = 2,
    ODRIVE_AXIS_STATE_FULL_CALIBRATION      = 3,
    ODRIVE_AXIS_STATE_MOTOR_CALIBRATION     = 4,
    ODRIVE_AXIS_STATE_ENCODER_INDEX_SEARCH  = 6,
    ODRIVE_AXIS_STATE_ENCODER_OFFSET_CALIB  = 7,
    ODRIVE_AXIS_STATE_CLOSED_LOOP_CONTROL   = 8
} odrive_axis_state_t;

/* Control modes */
typedef enum {
    ODRIVE_CONTROL_MODE_VOLTAGE  = 0,
    ODRIVE_CONTROL_MODE_TORQUE   = 1,
    ODRIVE_CONTROL_MODE_VELOCITY = 2,
    ODRIVE_CONTROL_MODE_POSITION = 3
} odrive_control_mode_t;

/* Input modes */
typedef enum {
    ODRIVE_INPUT_MODE_INACTIVE    = 0,
    ODRIVE_INPUT_MODE_PASSTHROUGH = 1,
    ODRIVE_INPUT_MODE_VEL_RAMP    = 2,
    ODRIVE_INPUT_MODE_POS_FILTER  = 3,
    ODRIVE_INPUT_MODE_TRAP_TRAJ   = 5,
    ODRIVE_INPUT_MODE_TORQUE_RAMP = 6
} odrive_input_mode_t;

/* Reboot actions */
typedef enum {
    ODRIVE_REBOOT_REBOOT   = 0,
    ODRIVE_REBOOT_SAVE_CONFIG = 1,
    ODRIVE_REBOOT_ERASE_CONFIG = 2
} odrive_reboot_action_t;

/* Little-endian pack/unpack helpers (host + ODrive are little-endian). */
static inline void odrive_pack_f32(uint8_t *dst, float v)   { memcpy(dst, &v, 4); }
static inline void odrive_pack_u32(uint8_t *dst, uint32_t v){ memcpy(dst, &v, 4); }
static inline void odrive_pack_i16(uint8_t *dst, int16_t v) { memcpy(dst, &v, 2); }
static inline float    odrive_unpack_f32(const uint8_t *s)  { float v;    memcpy(&v, s, 4); return v; }
static inline uint32_t odrive_unpack_u32(const uint8_t *s)  { uint32_t v; memcpy(&v, s, 4); return v; }
static inline uint16_t odrive_unpack_u16(const uint8_t *s)  { uint16_t v; memcpy(&v, s, 2); return v; }

#endif /* ODRIVE_PROTOCOL_H_ */
```

- [ ] **Step 2: Syntax-check the header**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -fsyntax-only -xc include/odrive_protocol.h`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add include/odrive_protocol.h
git commit -m "feat(c): add ODrive CAN protocol definitions and byte helpers"
```

---

### Task 2: Public API header (types + prototypes)

**Files:**
- Create: `include/odrive.h`

- [ ] **Step 1: Write `include/odrive.h`**

```c
/* odrive.h - Public API for the portable ODrive CAN library (fw 0.6.x). */
#ifndef ODRIVE_H_
#define ODRIVE_H_

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "odrive_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    ODRIVE_OK = 0,
    ODRIVE_ERR_SEND,      /* send callback returned false */
    ODRIVE_ERR_BAD_ARG    /* null pointer / invalid argument */
} odrive_status_t;

/* Send callback: transmit a CAN frame. rtr=true => remote (request) frame.
 * Return true on success. Provided by the host project. */
typedef bool (*odrive_send_fn)(void *ctx, uint32_t can_id,
                               const uint8_t *data, uint8_t len, bool rtr);

typedef struct {
    uint32_t axis_error;
    uint8_t  axis_state;
    uint8_t  procedure_result;
    uint8_t  trajectory_done_flag;
} odrive_heartbeat_t;

typedef struct {
    odrive_heartbeat_t hb;

    float pos_estimate;      /* converted to user units */
    float vel_estimate;      /* converted to user units */
    float iq_setpoint;
    float iq_measured;
    float fet_temperature;
    float motor_temperature;
    float bus_voltage;
    float bus_current;
    float torque_target;
    float torque_estimate;
    float electrical_power;
    float mechanical_power;

    uint32_t active_errors;
    uint32_t disarm_reason;

    uint16_t txsdo_endpoint;
    uint32_t txsdo_value;    /* raw 4 bytes of last TxSdo reply */

    uint8_t protocol_version;
    uint8_t hw_version_major, hw_version_minor, hw_version_variant;
    uint8_t fw_version_major, fw_version_minor, fw_version_revision;
} odrive_feedback_t;

struct odrive; /* fwd */
/* Callback fired when a matching frame is decoded. Read od->feedback inside.
 * Runs in the caller's context (often an ISR): keep it short. */
typedef void (*odrive_cb_t)(struct odrive *od, void *user);

typedef struct { odrive_cb_t fn; void *user; } odrive_cb_slot_t;

typedef struct odrive {
    odrive_send_fn send;
    void          *ctx;
    uint8_t        node_id;
    float          motor_conv;   /* signed: encodes scale + inversion */

    odrive_feedback_t feedback;

    struct {
        odrive_cb_slot_t heartbeat;
        odrive_cb_slot_t encoder;
        odrive_cb_slot_t iq;
        odrive_cb_slot_t temperature;
        odrive_cb_slot_t bus_vi;
        odrive_cb_slot_t torques;
        odrive_cb_slot_t powers;
        odrive_cb_slot_t error;
        odrive_cb_slot_t version;
        odrive_cb_slot_t txsdo;
    } cb;
} odrive_t;

/* ---- init & comm (odrive_comm.c) ---- */
void odrive_init(odrive_t *od, odrive_send_fn send, void *ctx,
                 uint8_t node_id, float conversion, bool invert);
void odrive_on_can_rx(odrive_t *od, uint32_t can_id,
                      const uint8_t *data, uint8_t len);
odrive_status_t odrive_write_sdo(odrive_t *od, uint16_t endpoint_id, uint32_t data);
odrive_status_t odrive_read_sdo(odrive_t *od, uint16_t endpoint_id);
int  odrive_get_status_string(odrive_t *od, char *buf, size_t buf_len);

/* callback registration */
void odrive_on_heartbeat(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_encoder(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_iq(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_temperature(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_bus_vi(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_torques(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_powers(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_error(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_version(odrive_t *od, odrive_cb_t fn, void *user);
void odrive_on_txsdo(odrive_t *od, odrive_cb_t fn, void *user);

/* ---- setpoints (odrive_setpoints.c) ---- */
odrive_status_t odrive_set_input_pos(odrive_t *od, float pos,
                                     float vel_ff, float torque_ff);
odrive_status_t odrive_set_input_vel(odrive_t *od, float vel, float torque_ff);
odrive_status_t odrive_set_input_torque(odrive_t *od, float torque);
odrive_status_t odrive_set_absolute_position(odrive_t *od, float pos);
odrive_status_t odrive_set_relative_pos(odrive_t *od, float delta);

/* ---- control/config (odrive_control.c) ---- */
odrive_status_t odrive_set_axis_state(odrive_t *od, odrive_axis_state_t state);
odrive_status_t odrive_set_closed_loop(odrive_t *od, bool enable); /* closed-loop vs idle */
odrive_status_t odrive_set_controller_mode(odrive_t *od,
                                           odrive_control_mode_t control_mode,
                                           odrive_input_mode_t input_mode);
odrive_status_t odrive_set_limits(odrive_t *od, float vel_limit, float current_limit);
odrive_status_t odrive_set_pos_gain(odrive_t *od, float pos_gain);
odrive_status_t odrive_set_vel_gains(odrive_t *od, float vel_gain,
                                     float vel_integrator_gain);
odrive_status_t odrive_set_traj_vel_limit(odrive_t *od, float vel_limit);
odrive_status_t odrive_set_traj_accel_limits(odrive_t *od, float accel, float decel);
odrive_status_t odrive_set_traj_inertia(odrive_t *od, float inertia);
odrive_status_t odrive_clear_errors(odrive_t *od);
odrive_status_t odrive_estop(odrive_t *od);
odrive_status_t odrive_reboot(odrive_t *od, odrive_reboot_action_t action);

/* ---- getters / RTR requests (odrive_feedback.c) ---- */
odrive_status_t odrive_request_version(odrive_t *od);
odrive_status_t odrive_request_error(odrive_t *od);
odrive_status_t odrive_request_encoder(odrive_t *od);
odrive_status_t odrive_request_iq(odrive_t *od);
odrive_status_t odrive_request_temperature(odrive_t *od);
odrive_status_t odrive_request_bus_vi(odrive_t *od);
odrive_status_t odrive_request_torques(odrive_t *od);
odrive_status_t odrive_request_powers(odrive_t *od);

/* ---- internal (defined in odrive_comm.c, used by other modules) ---- */
odrive_status_t odrive__send(odrive_t *od, uint8_t cmd,
                             const uint8_t *data, uint8_t len, bool rtr);

#ifdef __cplusplus
}
#endif
#endif /* ODRIVE_H_ */
```

- [ ] **Step 2: Syntax-check the header**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -fsyntax-only -xc include/odrive.h`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add include/odrive.h
git commit -m "feat(c): add ODrive public API header (types, prototypes)"
```

---

### Task 3: Comm module (init, send helper, RX decode/dispatch, SDO, status string)

**Files:**
- Create: `src/odrive_comm.c`

- [ ] **Step 1: Write `src/odrive_comm.c`**

```c
#include "odrive.h"
#include <stdio.h>

void odrive_init(odrive_t *od, odrive_send_fn send, void *ctx,
                 uint8_t node_id, float conversion, bool invert)
{
    if (!od) return;
    memset(od, 0, sizeof(*od));
    od->send = send;
    od->ctx = ctx;
    od->node_id = node_id & 0x3Fu;
    od->motor_conv = invert ? -conversion : conversion;
}

odrive_status_t odrive__send(odrive_t *od, uint8_t cmd,
                             const uint8_t *data, uint8_t len, bool rtr)
{
    if (!od || !od->send) return ODRIVE_ERR_BAD_ARG;
    uint32_t id = ODRIVE_CAN_ID(od->node_id, cmd);
    return od->send(od->ctx, id, data, len, rtr) ? ODRIVE_OK : ODRIVE_ERR_SEND;
}

static void fire(const odrive_cb_slot_t *s, odrive_t *od)
{
    if (s->fn) s->fn(od, s->user);
}

void odrive_on_can_rx(odrive_t *od, uint32_t can_id,
                      const uint8_t *data, uint8_t len)
{
    if (!od || !data) return;
    if (ODRIVE_ID_NODE(can_id) != od->node_id) return;
    odrive_feedback_t *fb = &od->feedback;
    uint8_t cmd = (uint8_t)ODRIVE_ID_CMD(can_id);

    switch (cmd) {
    case ODRIVE_CMD_HEARTBEAT:
        if (len < 7) return;
        fb->hb.axis_error           = odrive_unpack_u32(data);
        fb->hb.axis_state           = data[4];
        fb->hb.procedure_result     = data[5];
        fb->hb.trajectory_done_flag = data[6];
        fire(&od->cb.heartbeat, od);
        break;
    case ODRIVE_CMD_GET_ENCODER_ESTIMATES:
        if (len < 8) return;
        fb->pos_estimate = odrive_unpack_f32(data)     * od->motor_conv;
        fb->vel_estimate = odrive_unpack_f32(data + 4) * od->motor_conv;
        fire(&od->cb.encoder, od);
        break;
    case ODRIVE_CMD_GET_IQ:
        if (len < 8) return;
        fb->iq_setpoint = odrive_unpack_f32(data);
        fb->iq_measured = odrive_unpack_f32(data + 4);
        fire(&od->cb.iq, od);
        break;
    case ODRIVE_CMD_GET_TEMPERATURE:
        if (len < 8) return;
        fb->fet_temperature   = odrive_unpack_f32(data);
        fb->motor_temperature = odrive_unpack_f32(data + 4);
        fire(&od->cb.temperature, od);
        break;
    case ODRIVE_CMD_GET_BUS_VOLTAGE_CURRENT:
        if (len < 8) return;
        fb->bus_voltage = odrive_unpack_f32(data);
        fb->bus_current = odrive_unpack_f32(data + 4);
        fire(&od->cb.bus_vi, od);
        break;
    case ODRIVE_CMD_GET_TORQUES:
        if (len < 8) return;
        fb->torque_target   = odrive_unpack_f32(data);
        fb->torque_estimate = odrive_unpack_f32(data + 4);
        fire(&od->cb.torques, od);
        break;
    case ODRIVE_CMD_GET_POWERS:
        if (len < 8) return;
        fb->electrical_power = odrive_unpack_f32(data);
        fb->mechanical_power = odrive_unpack_f32(data + 4);
        fire(&od->cb.powers, od);
        break;
    case ODRIVE_CMD_GET_ERROR:
        if (len < 8) return;
        fb->active_errors = odrive_unpack_u32(data);
        fb->disarm_reason = odrive_unpack_u32(data + 4);
        fire(&od->cb.error, od);
        break;
    case ODRIVE_CMD_GET_VERSION:
        if (len < 7) return;
        fb->protocol_version   = data[0];
        fb->hw_version_major   = data[1];
        fb->hw_version_minor   = data[2];
        fb->hw_version_variant = data[3];
        fb->fw_version_major   = data[4];
        fb->fw_version_minor   = data[5];
        fb->fw_version_revision= data[6];
        fire(&od->cb.version, od);
        break;
    case ODRIVE_CMD_TXSDO:
        if (len < 8) return;
        fb->txsdo_endpoint = odrive_unpack_u16(data + 1);
        fb->txsdo_value    = odrive_unpack_u32(data + 4);
        fire(&od->cb.txsdo, od);
        break;
    default:
        break;
    }
}

odrive_status_t odrive_write_sdo(odrive_t *od, uint16_t endpoint_id, uint32_t data)
{
    uint8_t p[8] = {0};
    p[0] = 0x01;                 /* write opcode */
    p[1] = (uint8_t)(endpoint_id & 0xFFu);
    p[2] = (uint8_t)((endpoint_id >> 8) & 0xFFu);
    odrive_pack_u32(&p[4], data);
    return odrive__send(od, ODRIVE_CMD_RXSDO, p, 8, false);
}

odrive_status_t odrive_read_sdo(odrive_t *od, uint16_t endpoint_id)
{
    uint8_t p[8] = {0};
    p[0] = 0x00;                 /* read opcode */
    p[1] = (uint8_t)(endpoint_id & 0xFFu);
    p[2] = (uint8_t)((endpoint_id >> 8) & 0xFFu);
    return odrive__send(od, ODRIVE_CMD_RXSDO, p, 8, false);
}

int odrive_get_status_string(odrive_t *od, char *buf, size_t buf_len)
{
    if (!od || !buf) return -1;
    return snprintf(buf, buf_len,
        "axis_err=%lu state=%u proc=%u traj_done=%u pos=%.3f vel=%.3f "
        "iq=%.2f active_err=%lu disarm=%lu",
        (unsigned long)od->feedback.hb.axis_error,
        od->feedback.hb.axis_state,
        od->feedback.hb.procedure_result,
        od->feedback.hb.trajectory_done_flag,
        od->feedback.pos_estimate,
        od->feedback.vel_estimate,
        od->feedback.iq_measured,
        (unsigned long)od->feedback.active_errors,
        (unsigned long)od->feedback.disarm_reason);
}

#define ODRIVE_CB_SETTER(name, slot) \
    void name(odrive_t *od, odrive_cb_t fn, void *user) \
    { if (od) { od->cb.slot.fn = fn; od->cb.slot.user = user; } }

ODRIVE_CB_SETTER(odrive_on_heartbeat,   heartbeat)
ODRIVE_CB_SETTER(odrive_on_encoder,     encoder)
ODRIVE_CB_SETTER(odrive_on_iq,          iq)
ODRIVE_CB_SETTER(odrive_on_temperature, temperature)
ODRIVE_CB_SETTER(odrive_on_bus_vi,      bus_vi)
ODRIVE_CB_SETTER(odrive_on_torques,     torques)
ODRIVE_CB_SETTER(odrive_on_powers,      powers)
ODRIVE_CB_SETTER(odrive_on_error,       error)
ODRIVE_CB_SETTER(odrive_on_version,     version)
ODRIVE_CB_SETTER(odrive_on_txsdo,       txsdo)
```

- [ ] **Step 2: Compile the module (object only)**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -c src/odrive_comm.c -o /tmp/odrive_comm.o`
Expected: no warnings/errors, exit 0. (On Windows Git Bash use a writable temp path, e.g. `-o "$TEMP/odrive_comm.o"`.)

- [ ] **Step 3: Commit**

```bash
git add src/odrive_comm.c
git commit -m "feat(c): add comm module (init, send, RX decode/dispatch, SDO)"
```

---

### Task 4: Setpoints module

**Files:**
- Create: `src/odrive_setpoints.c`

- [ ] **Step 1: Write `src/odrive_setpoints.c`**

```c
#include "odrive.h"
#include <math.h>

odrive_status_t odrive_set_input_pos(odrive_t *od, float pos,
                                     float vel_ff, float torque_ff)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], pos / od->motor_conv);
    /* vel_ff: user units -> rev/s (/conv) -> raw int16 (*1000) */
    odrive_pack_i16(&p[4], (int16_t)lroundf((vel_ff / od->motor_conv) * 1000.0f));
    /* torque_ff: Nm (no conversion) -> raw int16 (*1000) */
    odrive_pack_i16(&p[6], (int16_t)lroundf(torque_ff * 1000.0f));
    return odrive__send(od, ODRIVE_CMD_SET_INPUT_POS, p, 8, false);
}

odrive_status_t odrive_set_input_vel(odrive_t *od, float vel, float torque_ff)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], vel / od->motor_conv);
    odrive_pack_f32(&p[4], torque_ff);   /* Nm, raw */
    return odrive__send(od, ODRIVE_CMD_SET_INPUT_VEL, p, 8, false);
}

odrive_status_t odrive_set_input_torque(odrive_t *od, float torque)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_f32(&p[0], torque);      /* Nm, raw */
    return odrive__send(od, ODRIVE_CMD_SET_INPUT_TORQUE, p, 4, false);
}

odrive_status_t odrive_set_absolute_position(odrive_t *od, float pos)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_f32(&p[0], pos / od->motor_conv);
    return odrive__send(od, ODRIVE_CMD_SET_ABSOLUTE_POSITION, p, 4, false);
}

odrive_status_t odrive_set_relative_pos(odrive_t *od, float delta)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    /* feedback.pos_estimate is already in user units */
    return odrive_set_input_pos(od, od->feedback.pos_estimate + delta, 0.0f, 0.0f);
}
```

- [ ] **Step 2: Compile the module**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -c src/odrive_setpoints.c -o /tmp/odrive_setpoints.o`
Expected: no warnings/errors, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/odrive_setpoints.c
git commit -m "feat(c): add setpoints module (pos/vel/torque, absolute/relative)"
```

---

### Task 5: Control/config module

**Files:**
- Create: `src/odrive_control.c`

- [ ] **Step 1: Write `src/odrive_control.c`**

```c
#include "odrive.h"
#include <math.h>

odrive_status_t odrive_set_axis_state(odrive_t *od, odrive_axis_state_t state)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_u32(&p[0], (uint32_t)state);
    return odrive__send(od, ODRIVE_CMD_SET_AXIS_STATE, p, 4, false);
}

odrive_status_t odrive_set_closed_loop(odrive_t *od, bool enable)
{
    return odrive_set_axis_state(od, enable ? ODRIVE_AXIS_STATE_CLOSED_LOOP_CONTROL
                                            : ODRIVE_AXIS_STATE_IDLE);
}

odrive_status_t odrive_set_controller_mode(odrive_t *od,
                                           odrive_control_mode_t control_mode,
                                           odrive_input_mode_t input_mode)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_u32(&p[0], (uint32_t)control_mode);
    odrive_pack_u32(&p[4], (uint32_t)input_mode);
    return odrive__send(od, ODRIVE_CMD_SET_CONTROLLER_MODE, p, 8, false);
}

odrive_status_t odrive_set_limits(odrive_t *od, float vel_limit, float current_limit)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], vel_limit / fabsf(od->motor_conv)); /* magnitude */
    odrive_pack_f32(&p[4], current_limit);                     /* A, raw */
    return odrive__send(od, ODRIVE_CMD_SET_LIMITS, p, 8, false);
}

odrive_status_t odrive_set_pos_gain(odrive_t *od, float pos_gain)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_f32(&p[0], pos_gain);    /* raw */
    return odrive__send(od, ODRIVE_CMD_SET_POS_GAIN, p, 4, false);
}

odrive_status_t odrive_set_vel_gains(odrive_t *od, float vel_gain,
                                     float vel_integrator_gain)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], vel_gain);            /* raw */
    odrive_pack_f32(&p[4], vel_integrator_gain); /* raw */
    return odrive__send(od, ODRIVE_CMD_SET_VEL_GAINS, p, 8, false);
}

odrive_status_t odrive_set_traj_vel_limit(odrive_t *od, float vel_limit)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_f32(&p[0], vel_limit / fabsf(od->motor_conv));
    return odrive__send(od, ODRIVE_CMD_SET_TRAJ_VEL_LIMIT, p, 4, false);
}

odrive_status_t odrive_set_traj_accel_limits(odrive_t *od, float accel, float decel)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], accel / fabsf(od->motor_conv));
    odrive_pack_f32(&p[4], decel / fabsf(od->motor_conv));
    return odrive__send(od, ODRIVE_CMD_SET_TRAJ_ACCEL_LIMITS, p, 8, false);
}

odrive_status_t odrive_set_traj_inertia(odrive_t *od, float inertia)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_f32(&p[0], inertia);     /* raw */
    return odrive__send(od, ODRIVE_CMD_SET_TRAJ_INERTIA, p, 4, false);
}

odrive_status_t odrive_clear_errors(odrive_t *od)
{
    return odrive__send(od, ODRIVE_CMD_CLEAR_ERRORS, NULL, 0, false);
}

odrive_status_t odrive_estop(odrive_t *od)
{
    return odrive__send(od, ODRIVE_CMD_ESTOP, NULL, 0, false);
}

odrive_status_t odrive_reboot(odrive_t *od, odrive_reboot_action_t action)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[1] = { (uint8_t)action };
    return odrive__send(od, ODRIVE_CMD_REBOOT, p, 1, false);
}
```

- [ ] **Step 2: Compile the module**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -c src/odrive_control.c -o /tmp/odrive_control.o`
Expected: no warnings/errors, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/odrive_control.c
git commit -m "feat(c): add control/config module (state, mode, limits, gains, traj)"
```

---

### Task 6: Feedback/getters module (RTR requests)

**Files:**
- Create: `src/odrive_feedback.c`

- [ ] **Step 1: Write `src/odrive_feedback.c`**

```c
#include "odrive.h"

/* Getters are requested with a zero-length remote (RTR) frame; the ODrive
 * replies with a data frame handled in odrive_on_can_rx(). */
static odrive_status_t request(odrive_t *od, uint8_t cmd)
{
    return odrive__send(od, cmd, NULL, 0, true);
}

odrive_status_t odrive_request_version(odrive_t *od)     { return request(od, ODRIVE_CMD_GET_VERSION); }
odrive_status_t odrive_request_error(odrive_t *od)       { return request(od, ODRIVE_CMD_GET_ERROR); }
odrive_status_t odrive_request_encoder(odrive_t *od)     { return request(od, ODRIVE_CMD_GET_ENCODER_ESTIMATES); }
odrive_status_t odrive_request_iq(odrive_t *od)          { return request(od, ODRIVE_CMD_GET_IQ); }
odrive_status_t odrive_request_temperature(odrive_t *od) { return request(od, ODRIVE_CMD_GET_TEMPERATURE); }
odrive_status_t odrive_request_bus_vi(odrive_t *od)      { return request(od, ODRIVE_CMD_GET_BUS_VOLTAGE_CURRENT); }
odrive_status_t odrive_request_torques(odrive_t *od)     { return request(od, ODRIVE_CMD_GET_TORQUES); }
odrive_status_t odrive_request_powers(odrive_t *od)      { return request(od, ODRIVE_CMD_GET_POWERS); }
```

- [ ] **Step 2: Compile the module**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -c src/odrive_feedback.c -o /tmp/odrive_feedback.o`
Expected: no warnings/errors, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/odrive_feedback.c
git commit -m "feat(c): add feedback getters module (RTR requests)"
```

---

### Task 7: Host smoke test (mock callback + encoding assertions + link check)

**Files:**
- Create: `test/smoke_test.c`
- Create: `test/Makefile`

- [ ] **Step 1: Write `test/smoke_test.c`**

```c
/* Host-only smoke test: verifies the whole library links and a few command
 * encodings are byte-correct against a mock send callback. Not a full suite. */
#include "odrive.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static struct {
    uint32_t id; uint8_t data[8]; uint8_t len; bool rtr; int count;
} g_last;

static bool mock_send(void *ctx, uint32_t id, const uint8_t *d, uint8_t len, bool rtr)
{
    (void)ctx;
    g_last.id = id; g_last.len = len; g_last.rtr = rtr; g_last.count++;
    memset(g_last.data, 0, sizeof(g_last.data));
    if (d && len) memcpy(g_last.data, d, len);
    return true;
}

int main(void)
{
    odrive_t od;
    odrive_init(&od, mock_send, NULL, /*node_id=*/5, /*conv=*/1.0f, /*invert=*/false);

    /* CAN id formation: node 5, Set_Input_Torque (0x0E) */
    odrive_set_input_torque(&od, 1.5f);
    assert(g_last.id == ((5u << 5) | 0x0Eu));
    assert(g_last.len == 4);
    float t; memcpy(&t, g_last.data, 4); assert(fabsf(t - 1.5f) < 1e-6f);

    /* Set_Input_Pos with conv=1.0: pos passthrough, ff int16 * 1000 */
    odrive_set_input_pos(&od, 0.25f, 2.0f, 0.5f);
    assert(g_last.id == ((5u << 5) | 0x0Cu));
    assert(g_last.len == 8);
    float pos; memcpy(&pos, g_last.data, 4); assert(fabsf(pos - 0.25f) < 1e-6f);
    int16_t vff, tff; memcpy(&vff, g_last.data + 4, 2); memcpy(&tff, g_last.data + 6, 2);
    assert(vff == 2000 && tff == 500);

    /* Getter uses RTR, zero length */
    odrive_request_encoder(&od);
    assert(g_last.rtr == true && g_last.len == 0);
    assert(g_last.id == ((5u << 5) | 0x09u));

    /* RX decode + conversion: feed a Get_Encoder_Estimates reply */
    odrive_init(&od, mock_send, NULL, 5, /*conv=*/2.0f, /*invert=*/false);
    uint8_t enc[8]; float p = 1.0f, v = 3.0f;
    memcpy(enc, &p, 4); memcpy(enc + 4, &v, 4);
    odrive_on_can_rx(&od, ODRIVE_CAN_ID(5, 0x09), enc, 8);
    assert(fabsf(od.feedback.pos_estimate - 2.0f) < 1e-6f);  /* 1.0 * conv(2.0) */
    assert(fabsf(od.feedback.vel_estimate - 6.0f) < 1e-6f);

    /* RX for a non-matching node is ignored */
    od.feedback.pos_estimate = 0.0f;
    odrive_on_can_rx(&od, ODRIVE_CAN_ID(6, 0x09), enc, 8);
    assert(od.feedback.pos_estimate == 0.0f);

    printf("smoke OK (%d frames sent)\n", g_last.count);
    return 0;
}
```

- [ ] **Step 2: Write `test/Makefile`**

```make
CC ?= gcc
CFLAGS = -std=c99 -Wall -Wextra -I../include
SRC = ../src/odrive_comm.c ../src/odrive_setpoints.c \
      ../src/odrive_control.c ../src/odrive_feedback.c smoke_test.c

smoke: $(SRC)
	$(CC) $(CFLAGS) $(SRC) -o smoke -lm

run: smoke
	./smoke

clean:
	rm -f smoke
```

- [ ] **Step 3: Build and run the smoke test**

Run: `make -C test run`
Expected: builds with no warnings, prints `smoke OK (3 frames sent)`, exit 0.
(If `make`/`gcc` are unavailable on this Windows host, compile directly with your host compiler:
`gcc -std=c99 -Wall -Wextra -Iinclude src/*.c test/smoke_test.c -o smoke -lm && ./smoke`.)

- [ ] **Step 4: Commit**

```bash
git add test/smoke_test.c test/Makefile
git commit -m "test(c): add host smoke test (encoding assertions + link check)"
```

---

### Task 8: STM32 example adapter (canbus_wrapper wiring)

**Files:**
- Create: `examples/stm32_fdcan_canbus_wrapper.c`

- [ ] **Step 1: Write `examples/stm32_fdcan_canbus_wrapper.c`**

```c
/* Example: wiring the portable ODrive library to an STM32 project that uses
 * dansoskin/canbus_wrapper for the FDCAN peripheral.
 *
 * This file is documentation/reference only. It requires the STM32 HAL and
 * canbus_wrapper headers and is NOT part of the host build. Guarded so it
 * compiles to nothing unless ODRIVE_STM32_EXAMPLE is defined by the project. */
#ifdef ODRIVE_STM32_EXAMPLE

#include "odrive.h"
#include "can.h"   /* canbus_wrapper: myCAN_t, can_send(), ring-buffer API */

/* 1) Adapt canbus_wrapper's can_send() to the ODrive send-callback signature.
 *    can_send(myCAN, payload, len, node_id(=can_id), is_request). */
static bool odrive_can_send(void *ctx, uint32_t can_id,
                            const uint8_t *data, uint8_t len, bool rtr)
{
    myCAN_t *bus = (myCAN_t *)ctx;
    /* can_send takes non-const payload; copy into a local buffer. */
    uint8_t buf[8] = {0};
    if (data && len) memcpy(buf, data, len);
    return can_send(bus, buf, len, can_id, rtr ? 1u : 0u) == HAL_OK;
}

/* 2) Create and initialize the drive (node 0, work in motor turns). */
static myCAN_t   g_bus;      /* set up elsewhere via can_setup(&g_bus, &hfdcan1) */
static odrive_t  g_odrive;

void odrive_example_init(void)
{
    odrive_init(&g_odrive, odrive_can_send, &g_bus,
                /*node_id=*/0, /*conversion=*/1.0f, /*invert=*/false);
}

/* 3) Pump received frames from canbus_wrapper's ring buffer into the library.
 *    Call this from the main loop or a CAN RX task. The exact ring-buffer
 *    read call matches your canbus_wrapper API (can_data_in_buffer /
 *    can_get_from_rbbuffer). Adjust field names to your rx-packet type. */
void odrive_example_poll_rx(void)
{
    while (can_data_in_buffer()) {
        /* rx_pkt has: FDCAN_RxHeaderTypeDef header; uint8_t data[8]; */
        can_rx_packet_t rx;
        if (can_get_from_rbbuffer(&rx) == 0) break;
        uint32_t id  = rx.header.Identifier;
        uint8_t  len = (uint8_t)rx.header.DataLength; /* map DLC->bytes if needed */
        odrive_on_can_rx(&g_odrive, id, rx.data, len);
    }
}

/* 4) Typical usage from application code:
 *      odrive_example_init();
 *      odrive_set_closed_loop(&g_odrive, true);
 *      odrive_set_input_vel(&g_odrive, 2.0f, 0.0f);
 *      // periodically: odrive_request_encoder(&g_odrive);
 *      //              odrive_example_poll_rx();
 *      // then read g_odrive.feedback.pos_estimate, etc.
 */

#endif /* ODRIVE_STM32_EXAMPLE */
```

- [ ] **Step 2: Verify the host build still ignores the example**

Run: `make -C test run`
Expected: still prints `smoke OK ...` (the example is guarded out and not part of the build), exit 0.

- [ ] **Step 3: Commit**

```bash
git add examples/stm32_fdcan_canbus_wrapper.c
git commit -m "docs(c): add STM32 canbus_wrapper adapter example"
```

---

### Task 9: README (usage + submodule integration)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Overwrite `README.md`**

````markdown
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

### Host smoke test
```bash
make -C test run   # prints "smoke OK ..."
```

## Python tuning tool

See `tools/odrtune/` (USB, PySide6). Independent of the C library.
````

- [ ] **Step 2: Verify it renders / no broken structure**

Run: `head -20 README.md`
Expected: shows the new content.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document C library usage and submodule integration"
```

---

## Self-Review

**Spec coverage:**
- §1.1 portable core + send callback + node_id + conv/invert + feedback + callbacks → Tasks 2, 3. ✅
- §1.1 RTR flag in callback → header (Task 2), used in Task 6. ✅
- §1.1 no HAL, C99, no dynamic alloc → all tasks (compile flags, no malloc). ✅
- §1.2 TX fire-and-forget + status enum → `odrive__send` (Task 3). ✅
- §1.2 RX feed-in, node filter, decode + fire callback → `odrive_on_can_rx` (Task 3). ✅
- §1.3 full command set: setpoints (Task 4), control/config (Task 5), getters (Task 6), SDO (Task 3). ✅ Every command in the protocol table maps to a function.
- §1.4 units: signed conv for pos/vel, |conv| for limits/accel, raw torque/gains → Tasks 3–5. ✅
- §1.5 `odrive_status_t`, no HAL types crossing API → Task 2/3. ✅
- §1.6 modular file layout → Tasks 1–6 match the file list exactly. ✅
- §1.7 compile-check + smoke, no full suite → Task 7. ✅
- STM32/canbus_wrapper as example, not baked in → Task 8. ✅

**Placeholder scan:** No TBD/TODO; every code step has complete code. ✅

**Type consistency:** `odrive_t`, `odrive_status_t`, `odrive_cb_t`, `odrive_send_fn`, `odrive__send`, `ODRIVE_CMD_*`, `ODRIVE_CAN_ID`, and all `odrive_*` function names are used identically across Tasks 2–8. Feedback field names (`pos_estimate`, `iq_measured`, `hb.axis_error`, …) match between the struct (Task 2) and decode/status (Task 3) and smoke test (Task 7). ✅

**Note:** `odrive_read_sdo`/`odrive_write_sdo` prototypes are declared in Task 2 and defined in Task 3 (comm module), consistent with the file layout.
