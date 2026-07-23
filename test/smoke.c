/* Host smoke tests for odrive_lib. No framework: a CHECK macro + captured TX. */
#include "odrive.h"
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

int main(void) {
    (void)cap_log; (void)log_reset;  /* used from Task 4 onward */
    test_setpoint_frame();
    test_msg_rate_enum();
    printf(g_fail ? "\n%d CHECK(s) FAILED\n" : "\nALL CHECKS PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
