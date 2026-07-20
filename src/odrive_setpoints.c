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
