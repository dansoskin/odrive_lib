/* PLACEHOLDER endpoint header for ODrive fw 0.6.x.
 * Regenerate with tools/gen_endpoints.py from your device's flat_endpoints.json.
 * Until then all endpoint ids are 0 and the periodic API returns
 * ODRIVE_ERR_BAD_ARG and logs. The expected fw major/minor below are the
 * library's target and stay 0.6 regardless. */
#ifndef ODRIVE_ENDPOINTS_0_6_H_
#define ODRIVE_ENDPOINTS_0_6_H_

#include "odrive_protocol.h"

#define ODRIVE_FW_EXPECTED_MAJOR   0u
#define ODRIVE_FW_EXPECTED_MINOR   6u
#define ODRIVE_FW_ENDPOINTS_BUILD  "unpopulated"

/* SDO endpoint id per odrive_msg_rate_t (0 = unpopulated). Defined in
 * src/odrive_endpoints_0_6.c (generated) or a test fixture. */
extern const uint16_t ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_COUNT];

#endif /* ODRIVE_ENDPOINTS_0_6_H_ */
