/* Host smoke tests for odrive_lib. No framework: a CHECK macro + captured TX. */
#include "odrive.h"
#include "odrive_endpoints_0_6.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { printf("FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__); g_fail++; } \
    else { printf("ok:   %s\n", (msg)); } } while (0)

/* ---- captured CAN TX ---- */
typedef struct { uint32_t id; uint8_t data[8]; uint8_t len; bool rtr; } frame_t;
static frame_t g_tx[64];
static int g_ntx = 0;
static void tx_reset(void) { g_ntx = 0; }
static bool cap_send(void *ctx, uint32_t id, const uint8_t *d, uint8_t len, bool rtr) {
    (void)ctx;
    if (g_ntx < 64) {
        g_tx[g_ntx].id = id; g_tx[g_ntx].len = len; g_tx[g_ntx].rtr = rtr;
        memset(g_tx[g_ntx].data, 0, 8);
        if (d && len) memcpy(g_tx[g_ntx].data, d, len);
        g_ntx++;
    }
    return true;
}

/* ---- captured log lines ---- */
static char g_log[8][128];
static int g_nlog = 0;
static void log_reset(void) { g_nlog = 0; }
static void cap_log(const char *m) {
    if (g_nlog < 8) { strncpy(g_log[g_nlog], m, 127); g_log[g_nlog][127] = 0; g_nlog++; }
}

static void test_setpoint_frame(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, /*node_id=*/0, /*conv=*/1.0f, /*invert=*/false);
    tx_reset();
    odrive_set_input_torque(&od, 1.5f);
    CHECK(g_ntx == 1, "input_torque emits one frame");
    CHECK(ODRIVE_ID_CMD(g_tx[0].id) == ODRIVE_CMD_SET_INPUT_TORQUE, "input_torque cmd id");
    CHECK(g_tx[0].len == 4 && g_tx[0].rtr == false, "input_torque 4-byte data frame");
}

static void test_msg_rate_enum(void) {
    CHECK(ODRIVE_MSG_RATE_COUNT == 9, "nine cyclic message kinds");
    CHECK(ODRIVE_MSG_RATE_VERSION == 0, "version is first slot");
}

static void test_logger(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);
    log_reset();
    odrive_logf(&od, "no sink %d", 1);       /* logger not set yet */
    CHECK(g_nlog == 0, "logf is a no-op without a sink");
    odrive_set_logger(&od, "odrv0", cap_log);
    odrive_logf(&od, "x=%d", 5);
    CHECK(g_nlog == 1, "logf emits one line");
    CHECK(strcmp(g_log[0], "odrv0: x=5") == 0, "logf prefixes name and formats");
}

static void test_endpoint_fixture(void) {
    CHECK(ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_HEARTBEAT] == 501u,
          "fixture heartbeat endpoint linked");
    CHECK(ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_POWERS] == 0u,
          "fixture powers endpoint is unpopulated");
}

static void feed_version(odrive_t *od, uint8_t major, uint8_t minor) {
    uint8_t d[8] = {0};
    d[4] = major; d[5] = minor; d[6] = 0;   /* proto/hw fields unused here */
    odrive_on_can_rx(od, ODRIVE_CAN_ID(od->node_id, ODRIVE_CMD_GET_VERSION), d, 8);
}

static void test_version_mismatch_logs_once(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);   /* init sends a version request */
    odrive_set_logger(&od, "odrv0", cap_log);
    log_reset();
    feed_version(&od, 0, 5);
    CHECK(g_nlog == 1, "mismatch logs once");
    CHECK(strstr(g_log[0], "endpoint table") != NULL, "mismatch message mentions endpoint table");
    feed_version(&od, 0, 5);
    CHECK(g_nlog == 1, "mismatch does not log again");
}

static void test_version_match_silent(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);
    odrive_set_logger(&od, "odrv0", cap_log);
    log_reset();
    feed_version(&od, ODRIVE_FW_EXPECTED_MAJOR, ODRIVE_FW_EXPECTED_MINOR);
    CHECK(g_nlog == 0, "matching fw logs nothing");
}

static void test_init_requests_version(void) {
    odrive_t od;
    tx_reset();
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);
    CHECK(g_ntx >= 1, "init sends a frame");
    CHECK(ODRIVE_ID_CMD(g_tx[0].id) == ODRIVE_CMD_GET_VERSION && g_tx[0].rtr,
          "init sends a GET_VERSION RTR request");
}

static void test_set_msg_rate_write(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);
    tx_reset();
    odrive_status_t rc = odrive_set_msg_rate(&od, ODRIVE_MSG_RATE_HEARTBEAT, 50u);
    CHECK(rc == ODRIVE_OK, "set_msg_rate returns OK for populated endpoint");
    CHECK(g_ntx == 1, "set_msg_rate emits one frame");
    CHECK(ODRIVE_ID_CMD(g_tx[0].id) == ODRIVE_CMD_RXSDO, "set_msg_rate uses RxSdo");
    CHECK(g_tx[0].data[0] == 0x01, "RxSdo write opcode");
    CHECK(odrive_unpack_u16(&g_tx[0].data[1]) == 501u, "RxSdo endpoint id 501");
    CHECK(odrive_unpack_u32(&g_tx[0].data[4]) == 50u, "RxSdo value 50");
}

static void test_set_msg_rate_unpopulated(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);
    odrive_set_logger(&od, "odrv0", cap_log);
    tx_reset(); log_reset();
    odrive_status_t rc = odrive_set_msg_rate(&od, ODRIVE_MSG_RATE_POWERS, 50u);
    CHECK(rc == ODRIVE_ERR_BAD_ARG, "unpopulated endpoint returns BAD_ARG");
    CHECK(g_ntx == 0, "unpopulated endpoint sends nothing");
    CHECK(g_nlog == 1 && strstr(g_log[0], "unpopulated") != NULL, "unpopulated is logged");
}

static void test_set_all_msg_rates(void) {
    odrive_t od;
    odrive_init(&od, cap_send, NULL, 0, 1.0f, false);
    tx_reset();
    uint32_t rates[ODRIVE_MSG_RATE_COUNT];
    for (int i = 0; i < ODRIVE_MSG_RATE_COUNT; ++i) rates[i] = 100u;
    odrive_status_t rc = odrive_set_all_msg_rates(&od, rates);
    CHECK(rc == ODRIVE_OK, "set_all returns OK");
    CHECK(g_ntx == 8, "set_all emits 8 frames (POWERS skipped)");
}

int main(void) {
    test_setpoint_frame();
    test_msg_rate_enum();
    test_logger();
    test_endpoint_fixture();
    test_init_requests_version();
    test_version_mismatch_logs_once();
    test_version_match_silent();
    test_set_msg_rate_write();
    test_set_msg_rate_unpopulated();
    test_set_all_msg_rates();
    printf(g_fail ? "\n%d CHECK(s) FAILED\n" : "\nALL CHECKS PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
