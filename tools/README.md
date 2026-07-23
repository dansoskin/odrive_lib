# tools/

Developer utilities for odrive_lib. Not compiled into the library.

## gen_endpoints.py

Generates the SDO endpoint table the periodic message-rate API consumes:
`include/odrive_endpoints_0_6.h` (expected-fw macros + `extern` decl) and
`src/odrive_endpoints_0_6.c` (the id array). ODrive endpoint ids change with
every firmware/hardware build, so they are read from your device rather than
hardcoded by hand.

```bash
# Connect over USB, download the endpoint table to flat_endpoints.json, generate:
python tools/gen_endpoints.py

# pick a specific device when several are connected:
python tools/gen_endpoints.py --serial 0123ABCD

# offline: use a flat_endpoints.json you already have:
python tools/gen_endpoints.py flat_endpoints.json

# override the version string if it can't be read:
python tools/gen_endpoints.py --fw-version 0.6.11
```

Device mode needs the `odrive` Python package (`pip install odrive`); offline
mode is stdlib-only (Python 3.9+). The downloaded `flat_endpoints.json` is saved
in the repo (change with `--save-json`) as a provenance record. Add
`src/odrive_endpoints_0_6.c` to your firmware build. Regenerate whenever you
flash new firmware to the target ODrive.
