#include "odrive_endpoints_0_6.h"

/* Test fixture: known ids; POWERS intentionally 0 to exercise the unpopulated
 * path. Linked into the host tests instead of src/odrive_endpoints_0_6.c. */
const uint16_t ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_COUNT] = {
    [ODRIVE_MSG_RATE_VERSION]     = 500u,
    [ODRIVE_MSG_RATE_HEARTBEAT]   = 501u,
    [ODRIVE_MSG_RATE_ENCODER]     = 502u,
    [ODRIVE_MSG_RATE_IQ]          = 503u,
    [ODRIVE_MSG_RATE_ERROR]       = 504u,
    [ODRIVE_MSG_RATE_TEMPERATURE] = 505u,
    [ODRIVE_MSG_RATE_BUS_VOLTAGE] = 506u,
    [ODRIVE_MSG_RATE_TORQUES]     = 507u,
    [ODRIVE_MSG_RATE_POWERS]      = 0u,
};
