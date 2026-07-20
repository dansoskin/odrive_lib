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
