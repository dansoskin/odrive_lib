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
