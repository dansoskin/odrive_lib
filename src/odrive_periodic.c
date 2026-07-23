#include "odrive.h"
#include "odrive_endpoints_0_6.h"

odrive_status_t odrive_set_msg_rate(odrive_t *od, odrive_msg_rate_t msg,
                                    uint32_t rate_ms)
{
    if (!od || msg < 0 || msg >= ODRIVE_MSG_RATE_COUNT) return ODRIVE_ERR_BAD_ARG;
    uint16_t ep = ODRIVE_MSG_RATE_ENDPOINT[msg];
    if (ep == 0u) {
        odrive_logf(od, "msg-rate endpoint %d unpopulated (regenerate endpoints)", (int)msg);
        return ODRIVE_ERR_BAD_ARG;
    }
    return odrive_write_sdo(od, ep, rate_ms);
}

odrive_status_t odrive_set_all_msg_rates(odrive_t *od,
                                         const uint32_t rate_ms[ODRIVE_MSG_RATE_COUNT])
{
    if (!od || !rate_ms) return ODRIVE_ERR_BAD_ARG;
    odrive_status_t rc = ODRIVE_OK;
    for (int m = 0; m < ODRIVE_MSG_RATE_COUNT; ++m) {
        uint16_t ep = ODRIVE_MSG_RATE_ENDPOINT[m];
        if (ep == 0u) {
            odrive_logf(od, "msg-rate endpoint %d unpopulated (skipped)", m);
            continue;
        }
        odrive_status_t s = odrive_write_sdo(od, ep, rate_ms[m]);
        if (s != ODRIVE_OK && rc == ODRIVE_OK) rc = s;
    }
    return rc;
}
