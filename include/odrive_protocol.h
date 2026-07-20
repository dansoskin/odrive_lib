/* odrive_protocol.h - ODrive fw 0.6.x CANSimple command IDs and byte helpers.
 * No dependency on odrive_t; safe to include anywhere. */
#ifndef ODRIVE_PROTOCOL_H_
#define ODRIVE_PROTOCOL_H_

#include <stdint.h>
#include <string.h>

#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)
#error "odrive_lib requires a little-endian target"
#endif

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
