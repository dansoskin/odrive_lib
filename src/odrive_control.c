#include "odrive.h"
#include <math.h>

odrive_status_t odrive_set_axis_state(odrive_t *od, odrive_axis_state_t state)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_u32(&p[0], (uint32_t)state);
    return odrive_send_frame(od, ODRIVE_CMD_SET_AXIS_STATE, p, 4, false);
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
    return odrive_send_frame(od, ODRIVE_CMD_SET_CONTROLLER_MODE, p, 8, false);
}

odrive_status_t odrive_set_limits(odrive_t *od, float vel_limit, float current_limit)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], vel_limit / fabsf(od->motor_conv)); /* magnitude */
    odrive_pack_f32(&p[4], current_limit);                     /* A, raw */
    return odrive_send_frame(od, ODRIVE_CMD_SET_LIMITS, p, 8, false);
}

odrive_status_t odrive_set_traj_vel_limit(odrive_t *od, float vel_limit)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[4] = {0};
    odrive_pack_f32(&p[0], vel_limit / fabsf(od->motor_conv));
    return odrive_send_frame(od, ODRIVE_CMD_SET_TRAJ_VEL_LIMIT, p, 4, false);
}

odrive_status_t odrive_set_traj_accel_limits(odrive_t *od, float accel, float decel)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[8] = {0};
    odrive_pack_f32(&p[0], accel / fabsf(od->motor_conv));
    odrive_pack_f32(&p[4], decel / fabsf(od->motor_conv));
    return odrive_send_frame(od, ODRIVE_CMD_SET_TRAJ_ACCEL_LIMITS, p, 8, false);
}

odrive_status_t odrive_clear_errors(odrive_t *od)
{
    return odrive_send_frame(od, ODRIVE_CMD_CLEAR_ERRORS, NULL, 0, false);
}

odrive_status_t odrive_estop(odrive_t *od)
{
    return odrive_send_frame(od, ODRIVE_CMD_ESTOP, NULL, 0, false);
}

odrive_status_t odrive_reboot(odrive_t *od, odrive_reboot_action_t action)
{
    if (!od) return ODRIVE_ERR_BAD_ARG;
    uint8_t p[1] = { (uint8_t)action };
    return odrive_send_frame(od, ODRIVE_CMD_REBOOT, p, 1, false);
}
