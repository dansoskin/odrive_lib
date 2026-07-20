#include "odrive.h"

/* Getters are requested with a zero-length remote (RTR) frame; the ODrive
 * replies with a data frame handled in odrive_on_can_rx(). */
static odrive_status_t request(odrive_t *od, uint8_t cmd)
{
    return odrive_send_frame(od, cmd, NULL, 0, true);
}

odrive_status_t odrive_request_version(odrive_t *od)     { return request(od, ODRIVE_CMD_GET_VERSION); }
odrive_status_t odrive_request_error(odrive_t *od)       { return request(od, ODRIVE_CMD_GET_ERROR); }
odrive_status_t odrive_request_encoder(odrive_t *od)     { return request(od, ODRIVE_CMD_GET_ENCODER_ESTIMATES); }
odrive_status_t odrive_request_iq(odrive_t *od)          { return request(od, ODRIVE_CMD_GET_IQ); }
odrive_status_t odrive_request_temperature(odrive_t *od) { return request(od, ODRIVE_CMD_GET_TEMPERATURE); }
odrive_status_t odrive_request_bus_vi(odrive_t *od)      { return request(od, ODRIVE_CMD_GET_BUS_VOLTAGE_CURRENT); }
odrive_status_t odrive_request_torques(odrive_t *od)     { return request(od, ODRIVE_CMD_GET_TORQUES); }
odrive_status_t odrive_request_powers(odrive_t *od)      { return request(od, ODRIVE_CMD_GET_POWERS); }
