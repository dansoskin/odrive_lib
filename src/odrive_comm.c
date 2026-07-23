#include "odrive.h"
#include "odrive_endpoints_0_6.h"
#include <stdio.h>
#include <stdarg.h>

void odrive_init(odrive_t *od, odrive_send_fn send, void *ctx,
                 uint8_t node_id, float conversion, bool invert)
{
    if (!od) return;
    memset(od, 0, sizeof(*od));
    od->send = send;
    od->ctx = ctx;
    od->node_id = node_id & 0x3Fu;
    od->motor_conv = (conversion == 0.0f) ? (invert ? -1.0f : 1.0f)
                                          : (invert ? -conversion : conversion);
    /* Best-effort: ask for the version so the RX path can flag a fw mismatch.
     * Harmless if the bus/peripheral is not up yet — the host can request again. */
    (void)odrive_request_version(od);
}

odrive_status_t odrive_send_frame(odrive_t *od, uint8_t cmd,
                             const uint8_t *data, uint8_t len, bool rtr)
{
    if (!od || !od->send) return ODRIVE_ERR_BAD_ARG;
    uint32_t id = ODRIVE_CAN_ID(od->node_id, cmd);
    return od->send(od->ctx, id, data, len, rtr) ? ODRIVE_OK : ODRIVE_ERR_SEND;
}

void odrive_set_logger(odrive_t *od, const char *name, odrive_log_fn_t log_fn)
{
    if (!od) return;
    od->log_name = name;
    od->log_fn = log_fn;
}

void odrive_logf(odrive_t *od, const char *fmt, ...)
{
    if (!od || !od->log_fn) return;
    char buf[96];
    int n = 0;
    if (od->log_name) {
        n = snprintf(buf, sizeof buf, "%s: ", od->log_name);
        if (n < 0 || (size_t)n >= sizeof buf) n = 0;
    }
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf + n, sizeof buf - (size_t)n, fmt, ap);
    va_end(ap);
    od->log_fn(buf);
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
        if (!od->fw_checked) {
            od->fw_checked = true;
            if (fb->fw_version_major != ODRIVE_FW_EXPECTED_MAJOR ||
                fb->fw_version_minor != ODRIVE_FW_EXPECTED_MINOR) {
                odrive_logf(od, "fw %u.%u != endpoint table %s; msg-rate endpoints may be wrong",
                            fb->fw_version_major, fb->fw_version_minor,
                            ODRIVE_FW_ENDPOINTS_BUILD);
            }
        }
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
    return odrive_send_frame(od, ODRIVE_CMD_RXSDO, p, 8, false);
}

odrive_status_t odrive_read_sdo(odrive_t *od, uint16_t endpoint_id)
{
    uint8_t p[8] = {0};
    p[0] = 0x00;                 /* read opcode */
    p[1] = (uint8_t)(endpoint_id & 0xFFu);
    p[2] = (uint8_t)((endpoint_id >> 8) & 0xFFu);
    return odrive_send_frame(od, ODRIVE_CMD_RXSDO, p, 8, false);
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
