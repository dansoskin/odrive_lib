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

/* Logger sink: receives a fully-formatted line. NULL disables logging. */
typedef void (*odrive_log_fn_t)(const char *message);

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

    const char     *log_name;   /* prefix for log lines (may be NULL) */
    odrive_log_fn_t log_fn;     /* NULL => logging disabled */
    bool            fw_checked; /* set once the fw version has been evaluated */
} odrive_t;

/* ---- init & comm (odrive_comm.c) ---- */
void odrive_init(odrive_t *od, odrive_send_fn send, void *ctx,
                 uint8_t node_id, float conversion, bool invert);
void odrive_on_can_rx(odrive_t *od, uint32_t can_id,
                      const uint8_t *data, uint8_t len);
odrive_status_t odrive_write_sdo(odrive_t *od, uint16_t endpoint_id, uint32_t data);
odrive_status_t odrive_read_sdo(odrive_t *od, uint16_t endpoint_id);
int  odrive_get_status_string(odrive_t *od, char *buf, size_t buf_len);
void odrive_set_logger(odrive_t *od, const char *name, odrive_log_fn_t log_fn);

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

/* ---- periodic (cyclic) CAN message rates (odrive_periodic.c) ----
 * Configures the ODrive's config.can.*_msg_rate_ms over SDO. rate_ms = 0
 * disables that message. Changes are live immediately; persist to NVM with
 * odrive_reboot(od, ODRIVE_REBOOT_SAVE_CONFIG). Endpoint ids come from
 * odrive_endpoints_0_6.h (generate with tools/gen_endpoints.py). */
odrive_status_t odrive_set_msg_rate(odrive_t *od, odrive_msg_rate_t msg,
                                    uint32_t rate_ms);
odrive_status_t odrive_set_all_msg_rates(odrive_t *od,
                                         const uint32_t rate_ms[ODRIVE_MSG_RATE_COUNT]);

/* ---- control/config (odrive_control.c) ---- */
odrive_status_t odrive_set_axis_state(odrive_t *od, odrive_axis_state_t state);
odrive_status_t odrive_set_closed_loop(odrive_t *od, bool enable); /* closed-loop vs idle */
odrive_status_t odrive_set_controller_mode(odrive_t *od,
                                           odrive_control_mode_t control_mode,
                                           odrive_input_mode_t input_mode);
odrive_status_t odrive_set_limits(odrive_t *od, float vel_limit, float current_limit);
odrive_status_t odrive_set_traj_vel_limit(odrive_t *od, float vel_limit);
odrive_status_t odrive_set_traj_accel_limits(odrive_t *od, float accel, float decel);
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
odrive_status_t odrive_send_frame(odrive_t *od, uint8_t cmd,
                                  const uint8_t *data, uint8_t len, bool rtr);
/* Internal: formatted log via od->log_fn (no-op if unset). Used across modules. */
void odrive_logf(odrive_t *od, const char *fmt, ...);

#ifdef __cplusplus
}
#endif
#endif /* ODRIVE_H_ */
