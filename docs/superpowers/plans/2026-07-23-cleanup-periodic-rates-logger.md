# Tuning Cleanup + Periodic CAN Rates + Logger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove control-loop *tuning* setters from odrive_lib, add a clpf-style logger, an async firmware-version compatibility check, and a per-message CAN cyclic-rate API backed by generated SDO endpoint ids.

**Architecture:** The library stays HAL-free and callback-driven. Endpoint ids (which change per firmware build) live in a generated pair `include/odrive_endpoints_0_6.h` (expected-fw macros + `extern` array declaration) and `src/odrive_endpoints_0_6.c` (the array definition), produced by `tools/gen_endpoints.py`. A committed placeholder (all-zero) keeps the tree building until a real `flat_endpoints.json` is supplied. Host tests compile with gcc and link a fixture definition of the endpoint array.

**Tech Stack:** C99 (gcc/MSYS2 on host), Python 3.9+ stdlib (generator). No test framework — a tiny assert-macro harness in `test/smoke.c`.

**Reference spec:** `docs/superpowers/specs/2026-07-23-cleanup-periodic-rates-logger-design.md`

---

## File Structure

- `include/odrive_protocol.h` — MODIFY: drop 3 tuning command IDs; add `odrive_msg_rate_t` enum.
- `include/odrive.h` — MODIFY: drop 3 tuning prototypes; add `odrive_log_fn_t`, struct fields, logger + periodic prototypes, internal `odrive_logf`.
- `src/odrive_control.c` — MODIFY: delete 3 tuning functions.
- `src/odrive_comm.c` — MODIFY: logger helper, `odrive_set_logger`, init version request, GET_VERSION compatibility check.
- `src/odrive_periodic.c` — CREATE: `odrive_set_msg_rate`, `odrive_set_all_msg_rates`.
- `include/odrive_endpoints_0_6.h` — CREATE (placeholder): expected-fw macros + `extern` array decl.
- `src/odrive_endpoints_0_6.c` — CREATE (placeholder): all-zero array definition (excluded from the host-test build; compiled by real consumers).
- `test/smoke.c` — CREATE: assert harness + tests.
- `test/fake_endpoints.c` — CREATE: fixture definition of the endpoint array for tests.
- `test/run.sh` — CREATE: host build + run.
- `tools/gen_endpoints.py` — MODIFY: emit the split `.h`/`.c` pair.
- `tools/README.md`, `README.md`, `CLAUDE.md` — MODIFY: docs.

Build/test invariant after every task: `bash test/run.sh` compiles clean (`-Wall -Wextra`) and prints no `FAIL`.

---

## Task 1: Host test harness

**Files:**
- Create: `test/smoke.c`
- Create: `test/run.sh`

- [ ] **Step 1: Write the harness with one test of existing behavior**

Create `test/smoke.c`:

```c
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

int main(void) {
    test_setpoint_frame();
    printf(g_fail ? "\n%d CHECK(s) FAILED\n" : "\nALL CHECKS PASSED\n", g_fail);
    return g_fail ? 1 : 0;
}
```

- [ ] **Step 2: Write the build/run script**

Create `test/run.sh`:

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
# Exclude the generated/placeholder endpoint definition; tests link test/fake_endpoints.c instead.
SRC=$(ls src/*.c | grep -v 'odrive_endpoints_0_6.c')
gcc -std=c99 -Wall -Wextra -Iinclude $SRC test/*.c -o test/smoke -lm
./test/smoke
```

- [ ] **Step 3: Run and verify it passes**

Run: `bash test/run.sh`
Expected: compiles clean, prints `ok:` lines and `ALL CHECKS PASSED`, exit 0.

- [ ] **Step 4: Commit**

```bash
git add test/smoke.c test/run.sh
git commit -m "test(c): add host smoke-test harness"
```

---

## Task 2: Remove tuning (gain) setters

**Files:**
- Modify: `include/odrive_protocol.h` (command IDs)
- Modify: `include/odrive.h` (prototypes)
- Modify: `src/odrive_control.c` (function bodies)
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Delete the three command IDs**

In `include/odrive_protocol.h`, remove these lines:

```c
#define ODRIVE_CMD_SET_TRAJ_INERTIA       0x13u
#define ODRIVE_CMD_SET_POS_GAIN           0x1Au
#define ODRIVE_CMD_SET_VEL_GAINS          0x1Bu
```

(Keep `SET_TRAJ_VEL_LIMIT 0x11`, `SET_TRAJ_ACCEL_LIMITS 0x12`, `SET_LIMITS 0x0F`, `GET_TORQUES 0x1C`, `GET_POWERS 0x1D`.)

- [ ] **Step 2: Delete the three prototypes**

In `include/odrive.h`, remove:

```c
odrive_status_t odrive_set_pos_gain(odrive_t *od, float pos_gain);
odrive_status_t odrive_set_vel_gains(odrive_t *od, float vel_gain,
                                     float vel_integrator_gain);
odrive_status_t odrive_set_traj_inertia(odrive_t *od, float inertia);
```

- [ ] **Step 3: Delete the three function bodies**

In `src/odrive_control.c`, remove `odrive_set_pos_gain`, `odrive_set_vel_gains`, and `odrive_set_traj_inertia` in full. Keep `odrive_set_traj_vel_limit` and `odrive_set_traj_accel_limits`.

- [ ] **Step 4: Update docs**

In `README.md`:
- In "What it does" (~line 15), change `setpoints, limits, gains, trajectory, calibration state` to `setpoints, limits, trajectory limits, calibration state`.
- In the API-groups table row for `odrive_control.c`, change `limits, pos/vel gains, trajectory params` to `limits, controller mode, trajectory limits`.

In `CLAUDE.md`, the `src/odrive_control.c` layout line, change `limits, gains, traj,` to `limits, traj limits,`.

- [ ] **Step 5: Build and verify no regressions**

Run: `bash test/run.sh`
Expected: compiles clean (no reference to removed symbols), `ALL CHECKS PASSED`.

- [ ] **Step 6: Commit**

```bash
git add include/odrive_protocol.h include/odrive.h src/odrive_control.c README.md CLAUDE.md
git commit -m "refactor(c): remove control-loop gain setters (tuning -> odrive_tuner)"
```

---

## Task 3: Message-rate enum

**Files:**
- Modify: `include/odrive_protocol.h`
- Modify: `test/smoke.c`

- [ ] **Step 1: Add the enum**

In `include/odrive_protocol.h`, after the reboot-actions enum (before the pack/unpack helpers), add:

```c
/* Cyclic (periodic) CAN message kinds; order mirrors the feedback getters.
 * Indexes the endpoint table in odrive_endpoints_0_6.h. */
typedef enum {
    ODRIVE_MSG_RATE_VERSION = 0,
    ODRIVE_MSG_RATE_HEARTBEAT,
    ODRIVE_MSG_RATE_ENCODER,
    ODRIVE_MSG_RATE_IQ,
    ODRIVE_MSG_RATE_ERROR,
    ODRIVE_MSG_RATE_TEMPERATURE,
    ODRIVE_MSG_RATE_BUS_VOLTAGE,   /* fw bus_voltage_msg_rate_ms; maps to the bus_vi getter */
    ODRIVE_MSG_RATE_TORQUES,
    ODRIVE_MSG_RATE_POWERS,
    ODRIVE_MSG_RATE_COUNT
} odrive_msg_rate_t;
```

- [ ] **Step 2: Add a test asserting the count**

In `test/smoke.c`, add this function and call it from `main` before the print:

```c
static void test_msg_rate_enum(void) {
    CHECK(ODRIVE_MSG_RATE_COUNT == 9, "nine cyclic message kinds");
    CHECK(ODRIVE_MSG_RATE_VERSION == 0, "version is first slot");
}
```

Add `test_msg_rate_enum();` in `main`.

- [ ] **Step 3: Build and verify**

Run: `bash test/run.sh`
Expected: `ok: nine cyclic message kinds`, `ALL CHECKS PASSED`.

- [ ] **Step 4: Commit**

```bash
git add include/odrive_protocol.h test/smoke.c
git commit -m "feat(c): add odrive_msg_rate_t cyclic-message enum"
```

---

## Task 4: Logger (clpf-style)

**Files:**
- Modify: `include/odrive.h`
- Modify: `src/odrive_comm.c`
- Modify: `test/smoke.c`

- [ ] **Step 1: Add typedef, struct fields, and prototypes**

In `include/odrive.h`, add the typedef next to `odrive_send_fn` (before `struct odrive`):

```c
/* Logger sink: receives a fully-formatted line. NULL disables logging. */
typedef void (*odrive_log_fn_t)(const char *message);
```

In `struct odrive`, after the `cb` sub-struct, add:

```c
    const char     *log_name;   /* prefix for log lines (may be NULL) */
    odrive_log_fn_t log_fn;     /* NULL => logging disabled */
    bool            fw_checked; /* set once the fw version has been evaluated */
```

In the comm section prototypes (near `odrive_get_status_string`), add:

```c
void odrive_set_logger(odrive_t *od, const char *name, odrive_log_fn_t log_fn);
```

In the internal section (next to `odrive_send_frame`), add:

```c
/* Internal: formatted log via od->log_fn (no-op if unset). Used across modules. */
void odrive_logf(odrive_t *od, const char *fmt, ...);
```

- [ ] **Step 2: Implement the logger in comm.c**

In `src/odrive_comm.c`, add `#include <stdarg.h>` under the existing includes. Add these two functions (e.g. after `odrive_send_frame`):

```c
void odrive_set_logger(odrive_t *od, const char *name, odrive_log_fn_t log_fn)
{
    if (!od) return;
    od->log_name = name;
    od->log_fn = log_fn;
}

void odrive_logf(odrive_t *od, const char *fmt, ...)
{
    if (!od || !od->log_fn) return;
    char buf[96];
    int n = 0;
    if (od->log_name) {
        n = snprintf(buf, sizeof buf, "%s: ", od->log_name);
        if (n < 0 || (size_t)n >= sizeof buf) n = 0;
    }
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf + n, sizeof buf - (size_t)n, fmt, ap);
    va_end(ap);
    od->log_fn(buf);
}
```

- [ ] **Step 3: Write the logger test**

In `test/smoke.c`, add and call from `main`:

```c
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
```

- [ ] **Step 4: Build and verify**

Run: `bash test/run.sh`
Expected: `ok: logf prefixes name and formats`, `ALL CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add include/odrive.h src/odrive_comm.c test/smoke.c
git commit -m "feat(c): add clpf-style logger (odrive_set_logger / odrive_logf)"
```

---

## Task 5: Placeholder endpoint header/source + test fixture

**Files:**
- Create: `include/odrive_endpoints_0_6.h`
- Create: `src/odrive_endpoints_0_6.c`
- Create: `test/fake_endpoints.c`
- Modify: `test/smoke.c`

- [ ] **Step 1: Create the placeholder header**

Create `include/odrive_endpoints_0_6.h`:

```c
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
```

- [ ] **Step 2: Create the placeholder definition**

Create `src/odrive_endpoints_0_6.c`:

```c
/* PLACEHOLDER definition — regenerate with tools/gen_endpoints.py.
 * Real consuming projects compile this file (or its generated replacement). */
#include "odrive_endpoints_0_6.h"

const uint16_t ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_COUNT] = { 0 };
```

- [ ] **Step 3: Create the test fixture definition**

Create `test/fake_endpoints.c` (linked into tests instead of the placeholder; `POWERS` is intentionally 0 to exercise the unpopulated path):

```c
#include "odrive_endpoints_0_6.h"

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
```

- [ ] **Step 4: Verify the placeholder source compiles standalone**

Run: `gcc -std=c99 -Wall -Wextra -Iinclude -c src/odrive_endpoints_0_6.c -o /dev/null`
Expected: no output, exit 0.

- [ ] **Step 5: Add a linkage test**

In `test/smoke.c`, add `#include "odrive_endpoints_0_6.h"` under the existing includes, then add and call from `main`:

```c
static void test_endpoint_fixture(void) {
    CHECK(ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_HEARTBEAT] == 501u,
          "fixture heartbeat endpoint linked");
    CHECK(ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_POWERS] == 0u,
          "fixture powers endpoint is unpopulated");
}
```

- [ ] **Step 6: Build and verify**

Run: `bash test/run.sh`
Expected: `run.sh` already excludes `src/odrive_endpoints_0_6.c` and compiles `test/*.c` (now includes `fake_endpoints.c`). `ALL CHECKS PASSED`.

- [ ] **Step 7: Commit**

```bash
git add include/odrive_endpoints_0_6.h src/odrive_endpoints_0_6.c test/fake_endpoints.c test/smoke.c
git commit -m "feat(c): add placeholder fw-0.6.x endpoint table + test fixture"
```

---

## Task 6: Async firmware-version check

**Files:**
- Modify: `src/odrive_comm.c`
- Modify: `test/smoke.c`

- [ ] **Step 1: Include the endpoint macros**

In `src/odrive_comm.c`, add under the includes:

```c
#include "odrive_endpoints_0_6.h"
```

- [ ] **Step 2: Best-effort version request in init**

In `src/odrive_comm.c`, at the end of `odrive_init` (after `od->motor_conv = ...`), add:

```c
    /* Best-effort: ask for the version so the RX path can flag a fw mismatch.
     * Harmless if the bus/peripheral is not up yet — the host can request again. */
    (void)odrive_request_version(od);
```

- [ ] **Step 3: Compare version on decode**

In `src/odrive_comm.c`, in `odrive_on_can_rx`, replace the `ODRIVE_CMD_GET_VERSION` case body so it evaluates compatibility once before firing the callback:

```c
    case ODRIVE_CMD_GET_VERSION:
        if (len < 7) return;
        fb->protocol_version   = data[0];
        fb->hw_version_major   = data[1];
        fb->hw_version_minor   = data[2];
        fb->hw_version_variant = data[3];
        fb->fw_version_major   = data[4];
        fb->fw_version_minor   = data[5];
        fb->fw_version_revision= data[6];
        if (!od->fw_checked) {
            od->fw_checked = true;
            if (fb->fw_version_major != ODRIVE_FW_EXPECTED_MAJOR ||
                fb->fw_version_minor != ODRIVE_FW_EXPECTED_MINOR) {
                odrive_logf(od, "fw %u.%u != endpoint table %s; msg-rate endpoints may be wrong",
                            fb->fw_version_major, fb->fw_version_minor,
                            ODRIVE_FW_ENDPOINTS_BUILD);
            }
        }
        fire(&od->cb.version, od);
        break;
```

- [ ] **Step 4: Write the version-check tests**

In `test/smoke.c`, add a helper to feed a version frame plus two tests, and call both from `main`:

```c
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
```

Add `test_init_requests_version(); test_version_mismatch_logs_once(); test_version_match_silent();` to `main`.

- [ ] **Step 5: Build and verify**

Run: `bash test/run.sh`
Expected: all four new checks `ok:`, `ALL CHECKS PASSED`.

- [ ] **Step 6: Commit**

```bash
git add src/odrive_comm.c test/smoke.c
git commit -m "feat(c): async fw-version compatibility check with logged warning"
```

---

## Task 7: Periodic message-rate API

**Files:**
- Create: `src/odrive_periodic.c`
- Modify: `include/odrive.h`
- Modify: `test/smoke.c`

- [ ] **Step 1: Add prototypes**

In `include/odrive.h`, after the setpoints section (or in its own labeled group), add:

```c
/* ---- periodic (cyclic) CAN message rates (odrive_periodic.c) ----
 * Configures the ODrive's config.can.*_msg_rate_ms over SDO. rate_ms = 0
 * disables that message. Changes are live immediately; persist to NVM with
 * odrive_reboot(od, ODRIVE_REBOOT_SAVE_CONFIG). Endpoint ids come from
 * odrive_endpoints_0_6.h (generate with tools/gen_endpoints.py). */
odrive_status_t odrive_set_msg_rate(odrive_t *od, odrive_msg_rate_t msg,
                                    uint32_t rate_ms);
odrive_status_t odrive_set_all_msg_rates(odrive_t *od,
                                         const uint32_t rate_ms[ODRIVE_MSG_RATE_COUNT]);
```

- [ ] **Step 2: Implement the module**

Create `src/odrive_periodic.c`:

```c
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
```

Note: `msg < 0` compares an enum against 0 — harmless and guards callers who pass a bad int cast; if `-Wtype-limits` complains under a future flag set, drop that half of the condition.

- [ ] **Step 3: Write the periodic tests**

In `test/smoke.c`, add and call from `main`. These rely on the `test/fake_endpoints.c` fixture (HEARTBEAT=501, POWERS=0):

```c
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
```

Add `test_set_msg_rate_write(); test_set_msg_rate_unpopulated(); test_set_all_msg_rates();` to `main`.

- [ ] **Step 4: Build and verify**

Run: `bash test/run.sh`
Expected: `run.sh`'s `src/*.c` glob now includes `src/odrive_periodic.c`; the extern array resolves from `test/fake_endpoints.c`. All new checks `ok:`, `ALL CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add include/odrive.h src/odrive_periodic.c test/smoke.c
git commit -m "feat(c): per-message periodic CAN rate API (set_msg_rate/set_all_msg_rates)"
```

---

## Task 8: Update generator to emit the split .h/.c, and finalize docs

**Files:**
- Modify: `tools/gen_endpoints.py`
- Modify: `tools/README.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Change the generator output**

In `tools/gen_endpoints.py`, replace `build_header` with two builders and update `main` to write both files. Replace the `build_header` function and `main` with:

```python
def build_header(version: str, major: int, minor: int) -> str:
    lines = [
        "/* AUTO-GENERATED by tools/gen_endpoints.py -- DO NOT EDIT BY HAND.",
        f" * Source firmware: {version}",
        " * Endpoint ids are only valid for this exact firmware build. */",
        "#ifndef ODRIVE_ENDPOINTS_0_6_H_",
        "#define ODRIVE_ENDPOINTS_0_6_H_",
        "",
        '#include "odrive_protocol.h"',
        "",
        f"#define ODRIVE_FW_EXPECTED_MAJOR   {major}u",
        f"#define ODRIVE_FW_EXPECTED_MINOR   {minor}u",
        f'#define ODRIVE_FW_ENDPOINTS_BUILD  "{version}"',
        "",
        "extern const uint16_t ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_COUNT];",
        "",
        "#endif /* ODRIVE_ENDPOINTS_0_6_H_ */",
    ]
    return "\n".join(lines) + "\n"


def build_source(rows: list, version: str) -> str:
    lines = [
        "/* AUTO-GENERATED by tools/gen_endpoints.py -- DO NOT EDIT BY HAND.",
        f" * Source firmware: {version} */",
        '#include "odrive_endpoints_0_6.h"',
        "",
        "const uint16_t ODRIVE_MSG_RATE_ENDPOINT[ODRIVE_MSG_RATE_COUNT] = {",
    ]
    width = max(len(name) for name, _, _ in rows)
    for enum_name, eid, comment in rows:
        lines.append(f"    [{enum_name:<{width}}] = {eid}u,  /* {comment} */")
    lines.append("};")
    return "\n".join(lines) + "\n"


def collect_rows(endpoints: dict) -> list:
    rows, n_found = [], 0
    for leaf, enum_name in RATE_PARAMS:
        entry = find_endpoint(endpoints, leaf)
        if entry is None:
            print(f"warning: '{leaf}' not found -> emitting 0 (unpopulated)", file=sys.stderr)
            rows.append((enum_name, 0, f"{leaf}: NOT FOUND"))
            continue
        eid = int(entry["id"])
        etype = entry.get("type", "?")
        if eid > 0xFFFF:
            sys.exit(f"error: '{leaf}' id {eid} exceeds uint16 endpoint range")
        if etype not in ("uint32", "int32"):
            print(f"warning: '{leaf}' type is '{etype}', expected uint32", file=sys.stderr)
        rows.append((enum_name, eid, f"{entry['_path']}  ({etype})"))
        n_found += 1
    if n_found == 0:
        sys.exit("error: no msg-rate endpoints found in json -- wrong file?")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", help="path to flat_endpoints.json")
    ap.add_argument("--header", default="include/odrive_endpoints_0_6.h",
                    help="output header path (default: include/odrive_endpoints_0_6.h)")
    ap.add_argument("--source", default="src/odrive_endpoints_0_6.c",
                    help="output source path (default: src/odrive_endpoints_0_6.c)")
    ap.add_argument("--fw-version", help="override firmware version (e.g. 0.6.11)")
    args = ap.parse_args()

    endpoints, version = load_endpoints(args.json)
    version = args.fw_version or version
    major, minor = derive_major_minor(version)
    rows = collect_rows(endpoints)

    with open(args.header, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_header(version, major, minor))
    with open(args.source, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_source(rows, version))
    print(f"wrote {args.header} and {args.source} (fw {version})")
```

Remove the now-unused `-o/--output` handling (superseded by `--header`/`--source`). Keep `load_endpoints`, `find_endpoint`, `derive_major_minor`, and `RATE_PARAMS` unchanged.

- [ ] **Step 2: Verify the generator round-trips and the output compiles**

Run:
```bash
cat > /tmp/fx.json <<'EOF'
{"fw_version":"0.6.11","endpoints":{
 "axis0.config.can.version_msg_rate_ms":{"id":400,"type":"uint32"},
 "axis0.config.can.heartbeat_msg_rate_ms":{"id":401,"type":"uint32"},
 "axis0.config.can.encoder_msg_rate_ms":{"id":402,"type":"uint32"},
 "axis0.config.can.iq_msg_rate_ms":{"id":403,"type":"uint32"},
 "axis0.config.can.error_msg_rate_ms":{"id":404,"type":"uint32"},
 "axis0.config.can.temperature_msg_rate_ms":{"id":405,"type":"uint32"},
 "axis0.config.can.bus_voltage_msg_rate_ms":{"id":406,"type":"uint32"},
 "axis0.config.can.torques_msg_rate_ms":{"id":407,"type":"uint32"},
 "axis0.config.can.powers_msg_rate_ms":{"id":408,"type":"uint32"}}}
EOF
python tools/gen_endpoints.py /tmp/fx.json --header /tmp/ep.h --source /tmp/ep.c
gcc -std=c99 -Wall -Wextra -Iinclude -I/tmp -include /tmp/ep.h -c /tmp/ep.c -o /dev/null
```
Expected: `wrote /tmp/ep.h and /tmp/ep.c (fw 0.6.11)`, and the gcc compile exits 0 with no warnings. (Do NOT overwrite the committed placeholder here.)

- [ ] **Step 3: Verify the placeholder still matches the consumed shape**

Run: `bash test/run.sh`
Expected: unchanged — `ALL CHECKS PASSED` (the generator change does not touch committed headers).

- [ ] **Step 4: Update docs**

In `tools/README.md`, change the usage to the split output and note both files are generated:

```bash
python tools/gen_endpoints.py flat_endpoints.json
# -> writes include/odrive_endpoints_0_6.h and src/odrive_endpoints_0_6.c
```

In `README.md`:
- In the submodule "Sources" list (~line 27), add `src/odrive_periodic.c` and `src/odrive_endpoints_0_6.c`.
- Add API-groups table rows: `odrive_periodic.c` → "set_msg_rate, set_all_msg_rates" and note `odrive_comm.c` now also has "logger (odrive_set_logger)".
- Add a short "Periodic messages & firmware" subsection: generate the endpoint header with `tools/gen_endpoints.py`, that `odrive_init` requests the version and logs a mismatch, and that rates persist only after `odrive_reboot(SAVE_CONFIG)`.

In `CLAUDE.md`, add to the Layout block:
```
src/odrive_periodic.c       # set cyclic CAN message rates (per message) via SDO
src/odrive_endpoints_0_6.c  # GENERATED endpoint-id table (tools/gen_endpoints.py)
tools/gen_endpoints.py      # flat_endpoints.json -> odrive_endpoints_0_6.{h,c}
```
and note the logger + async fw-check under "Status / gotchas".

- [ ] **Step 5: Commit**

```bash
git add tools/gen_endpoints.py tools/README.md README.md CLAUDE.md
git commit -m "feat(c): generator emits split endpoint .h/.c; update docs"
```

---

## Self-Review

**Spec coverage:**
- Remove gains → Task 2. ✓
- Logger (clpf-style) → Task 4. ✓
- Generated endpoint table + placeholder → Tasks 5, 8. ✓
- Enum → Task 3. ✓
- Async version check → Task 6. ✓
- Per-message + all-at-once API → Task 7. ✓
- Host-compile + capturing-send + logger tests → Tasks 1–7. ✓
- Docs (README/CLAUDE/tools) → Tasks 2, 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; commands have expected output. The committed all-zero endpoint file is an intentional, documented placeholder, not a plan gap.

**Type consistency:** `odrive_msg_rate_t`, `odrive_log_fn_t`, `ODRIVE_MSG_RATE_ENDPOINT`, `ODRIVE_MSG_RATE_COUNT`, `odrive_logf`, `odrive_set_logger`, `odrive_set_msg_rate`, `odrive_set_all_msg_rates`, `ODRIVE_FW_EXPECTED_MAJOR/MINOR`, `ODRIVE_FW_ENDPOINTS_BUILD`, `fw_checked` used identically across tasks. `run.sh` glob (`src/*.c` minus `odrive_endpoints_0_6.c`, plus `test/*.c`) is consistent from Task 1 and absorbs new files without edits.

## Post-implementation (requires the user's real json)

Once the user supplies `flat_endpoints.json`:
```bash
python tools/gen_endpoints.py flat_endpoints.json
bash test/run.sh   # still green; consumers now build the real src/odrive_endpoints_0_6.c
```
Verify the nine ids are non-zero (no "NOT FOUND" warnings); if any warn, adjust the path matcher in `RATE_PARAMS`/`find_endpoint`.
