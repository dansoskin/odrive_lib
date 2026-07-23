# tools/

Developer utilities for odrive_lib. Not compiled into the library.

## gen_endpoints.py

Generates `include/odrive_endpoints_0_6.h` (the SDO endpoint table the periodic
message-rate API consumes) from an ODrive `flat_endpoints.json`.

ODrive endpoint ids change with every firmware/hardware build, so they are
generated from your device's json rather than hardcoded by hand.

```bash
# get flat_endpoints.json from your ODrive (odrivetool caches it, or export it
# for your firmware build), then:
python tools/gen_endpoints.py flat_endpoints.json
# -> writes include/odrive_endpoints_0_6.h  (expected-fw macros + extern decl)
#           src/odrive_endpoints_0_6.c       (the endpoint-id array definition)

# if the json has no version field:
python tools/gen_endpoints.py flat_endpoints.json --fw-version 0.6.11
```

Add `src/odrive_endpoints_0_6.c` to your build. Override output paths with
`--header` / `--source` if needed.

Requires Python 3.9+ (standard library only). Regenerate whenever you change the
firmware on the target ODrive.
