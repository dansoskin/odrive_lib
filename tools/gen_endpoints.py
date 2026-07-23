#!/usr/bin/env python3
"""Generate the C endpoint table for odrive_lib from a connected ODrive.

The ODrive exposes its config parameters over CAN (RxSdo/TxSdo) by numeric
*endpoint id*. Those ids change with every firmware/hardware build, so odrive_lib
does not hardcode them by hand. By default this script connects to an ODrive over
USB (via the ``odrive`` Python package), downloads its endpoint table, saves it to
``flat_endpoints.json`` in the library, and emits the C files the periodic
message-rate API consumes:
    include/odrive_endpoints_0_6.h   (expected-fw macros + extern declaration)
    src/odrive_endpoints_0_6.c       (the endpoint-id array definition)

Usage:
    python tools/gen_endpoints.py                     # connect, download, generate
    python tools/gen_endpoints.py --serial 0123ABCD   # pick a specific device
    python tools/gen_endpoints.py flat_endpoints.json # offline: use an existing json
    python tools/gen_endpoints.py --fw-version 0.6.11 # override version string

Endpoint ids are only valid for the firmware they were read from; regenerate
after flashing new firmware.
"""

import argparse
import json
import sys
from typing import Optional

# Firmware ``axis0.config.can.<leaf>`` parameter -> odrive_msg_rate_t constant.
# Order here is only for readable output; the emitted header uses designated
# initializers, so it is robust to the enum's declaration order.
RATE_PARAMS = [
    ("version_msg_rate_ms",     "ODRIVE_MSG_RATE_VERSION"),
    ("heartbeat_msg_rate_ms",   "ODRIVE_MSG_RATE_HEARTBEAT"),
    ("encoder_msg_rate_ms",     "ODRIVE_MSG_RATE_ENCODER"),
    ("iq_msg_rate_ms",          "ODRIVE_MSG_RATE_IQ"),
    ("error_msg_rate_ms",       "ODRIVE_MSG_RATE_ERROR"),
    ("temperature_msg_rate_ms", "ODRIVE_MSG_RATE_TEMPERATURE"),
    ("bus_voltage_msg_rate_ms", "ODRIVE_MSG_RATE_BUS_VOLTAGE"),
    ("torques_msg_rate_ms",     "ODRIVE_MSG_RATE_TORQUES"),
    ("powers_msg_rate_ms",      "ODRIVE_MSG_RATE_POWERS"),
]


def load_endpoints(path: str) -> tuple[dict, Optional[str]]:
    """Return (endpoints_dict, fw_version_str_or_None) from a flat_endpoints.json."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Top level is usually {"endpoints": {...}, "fw_version": "..."} but some
    # dumps are just the flat {path: {...}} map -- accept both.
    endpoints = data.get("endpoints", data) if isinstance(data, dict) else None
    if not isinstance(endpoints, dict):
        sys.exit(f"error: {path}: no 'endpoints' object found")

    version = None
    if isinstance(data, dict):
        for key in ("fw_version", "version", "firmware_version"):
            if key in data and data[key]:
                v = data[key]
                # version may be "0.6.11" or [0, 6, 11]
                version = ".".join(str(x) for x in v) if isinstance(v, list) else str(v)
                break
    return endpoints, version


def find_endpoint(endpoints: dict, leaf: str) -> Optional[dict]:
    """Find the endpoint entry whose final path component is <leaf>.

    Robust to path layout (``axis0.config.can.<leaf>`` vs ``config.can.<leaf>``):
    matches on the last dotted component, preferring paths under ``axis0`` and
    ones containing ``can``.
    """
    matches = [p for p in endpoints if p.split(".")[-1] == leaf]
    if not matches:
        return None
    matches.sort(key=lambda p: (0 if "axis0" in p else 1,
                                0 if ".can" in p else 1, len(p), p))
    entry = dict(endpoints[matches[0]])
    entry["_path"] = matches[0]
    return entry


def fetch_from_device(serial: Optional[str], timeout: float) -> tuple[dict, Optional[str]]:
    """Connect to an ODrive over USB and return (endpoints_dict, fw_version_str)."""
    try:
        import odrive
    except ImportError:
        sys.exit("error: the 'odrive' package is required to connect to a device "
                 "(pip install odrive), or pass an existing flat_endpoints.json to "
                 "work offline")

    print(f"connecting to ODrive{' ' + serial if serial else ''} "
          f"(timeout {timeout:g}s)...", file=sys.stderr)
    try:
        kwargs = {"timeout": timeout}
        if serial:
            kwargs["serial_number"] = serial
        odrv = odrive.find_any(**kwargs)
    except Exception as ex:  # timeout / discovery failure
        sys.exit(f"error: could not connect to an ODrive: {ex}")

    dev = getattr(odrv, "_dev", None)
    flat = getattr(dev, "flat_json", None)
    if not isinstance(flat, dict):
        sys.exit("error: could not read the endpoint table (odrv._dev.flat_json) "
                 "from the odrive package -- unsupported package version?")

    try:
        version = (f"{odrv.fw_version_major}.{odrv.fw_version_minor}"
                   f".{odrv.fw_version_revision}")
    except Exception:
        version = None
    print(f"connected: fw {version}, {len(flat)} endpoints", file=sys.stderr)
    return flat, version


def derive_major_minor(version: Optional[str]) -> tuple[int, int]:
    if not version:
        sys.exit("error: firmware version not found in json; pass --fw-version X.Y.Z")
    parts = version.strip().lstrip("vV").split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        sys.exit(f"error: cannot parse major.minor from version '{version}'; "
                 f"pass --fw-version X.Y.Z")


def collect_rows(endpoints: dict) -> list:
    """Map each rate param to (enum_name, endpoint_id, comment); 0 if missing."""
    rows, n_found = [], 0
    for leaf, enum_name in RATE_PARAMS:
        entry = find_endpoint(endpoints, leaf)
        if entry is None:
            print(f"warning: '{leaf}' not found -> emitting 0 (unpopulated)",
                  file=sys.stderr)
            rows.append((enum_name, 0, f"{leaf}: NOT FOUND"))
            continue
        eid = int(entry["id"])
        etype = entry.get("type", "?")
        if eid > 0xFFFF:
            sys.exit(f"error: '{leaf}' id {eid} exceeds uint16 endpoint range")
        if etype not in ("uint32", "int32"):
            print(f"warning: '{leaf}' type is '{etype}', expected uint32",
                  file=sys.stderr)
        rows.append((enum_name, eid, f"{entry['_path']}  ({etype})"))
        n_found += 1
    if n_found == 0:
        sys.exit("error: no msg-rate endpoints found in json -- wrong file?")
    return rows


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", nargs="?",
                    help="existing flat_endpoints.json; omit to connect to a device")
    ap.add_argument("--serial", help="serial number of the ODrive to connect to")
    ap.add_argument("--timeout", type=float, default=15.0,
                    help="device connect timeout in seconds (default: 15)")
    ap.add_argument("--save-json", default="flat_endpoints.json",
                    help="where to save the downloaded json in device mode "
                         "(default: flat_endpoints.json)")
    ap.add_argument("--header", default="include/odrive_endpoints_0_6.h",
                    help="output header path (default: include/odrive_endpoints_0_6.h)")
    ap.add_argument("--source", default="src/odrive_endpoints_0_6.c",
                    help="output source path (default: src/odrive_endpoints_0_6.c)")
    ap.add_argument("--fw-version",
                    help="override firmware version string (e.g. 0.6.11)")
    args = ap.parse_args()

    if args.json:
        endpoints, version = load_endpoints(args.json)
    else:
        endpoints, version = fetch_from_device(args.serial, args.timeout)
        payload = {"fw_version": version, "endpoints": endpoints}
        with open(args.save_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2)
        print(f"saved {args.save_json} (fw {version})", file=sys.stderr)

    version = args.fw_version or version
    major, minor = derive_major_minor(version)
    rows = collect_rows(endpoints)

    with open(args.header, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_header(version, major, minor))
    with open(args.source, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_source(rows, version))
    print(f"wrote {args.header} and {args.source} (fw {version})")


if __name__ == "__main__":
    main()
