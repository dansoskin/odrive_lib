"""Config backup/restore and save-to-NVM.

Schema v2 captures the full tunable surface the GUI exposes:
``tuning`` (all controller/motor tuning params), ``motion`` (input mode +
ramp/trajectory limits) and ``control_mode``, plus device identity (serial,
firmware). It is a versioned dict so it can grow without breaking old files;
schema 1 (three gains only) is still readable on restore.

JSON cannot represent inf/nan, so floats are (de)serialized transparently here:
non-finite values become the strings ``"inf"``/``"-inf"``/``"nan"`` in the
snapshot and are decoded back to floats when a restore plan is built.

``build_restore_plan`` is a pure, headless-testable function that diffs a
snapshot against the live device; ``apply_restore`` writes a chosen subset."""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.device import Device, values_match

SCHEMA_VERSION = 2

# Parameters whose wrong values can damage hardware: current limits + the motor
# model (and its validity flags). Unchecked by default in the restore dialog.
SENSITIVE_KEYS = {
    "current_soft_max",
    "current_hard_max",
    "current_slew_rate_limit",
    "torque_constant",
    "phase_resistance",
    "phase_inductance",
    "ff_pm_flux_linkage",
    "motor_model_l_d",
    "motor_model_l_q",
    "phase_resistance_valid",
    "phase_inductance_valid",
    "ff_pm_flux_linkage_valid",
    "motor_model_l_dq_valid",
}


@dataclass
class RestoreItem:
    key: str
    section: str          # "tuning" | "motion" | "control_mode"
    current: object        # device's live value, or None if unavailable
    target: object         # value from the snapshot
    changed: bool
    sensitive: bool = False


# --- non-finite float (de)serialization -------------------------------------
def _encode_value(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        if math.isnan(v):
            return "nan"
    return v


def _decode_value(v):
    if isinstance(v, str):
        if v == "inf":
            return float("inf")
        if v == "-inf":
            return float("-inf")
        if v == "nan":
            return float("nan")
    return v


def _walk(obj, fn):
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(x, fn) for x in obj]
    return fn(obj)


def _encode(obj):
    """Return a JSON-safe copy (inf/-inf/nan floats -> tokens)."""
    return _walk(obj, _encode_value)


def _decode(obj):
    """Reverse _encode (tokens -> floats)."""
    return _walk(obj, _decode_value)


def _fmt_value(v) -> str:
    """Human-readable value for the restore diff (handles None/bool/float)."""
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


# --- backup ------------------------------------------------------------------
def backup(dev: Device) -> dict:
    """Read the full tunable config into a JSON-serializable schema-2 dict."""
    snap = {
        "schema": SCHEMA_VERSION,
        "serial": dev.serial_hex(),
        "firmware": list(dev.fw_version()),
        "tuning": dev.get_tuning(),
        "motion": dev.get_motion_config(),
        "control_mode": dev.get_control_mode(),
    }
    return _encode(snap)


# --- restore planning (pure / headless-testable) ----------------------------
def _is_changed(current, target) -> bool:
    """True if target differs from the live value (or the live value is
    unavailable, so a match can't be confirmed)."""
    if current is None:
        return True
    return not values_match(current, target)


def build_restore_plan(dev: Device, snapshot: dict):
    """Diff a snapshot against the live device.

    Returns ``(items, warnings)``. ``items`` is a list of :class:`RestoreItem`
    for every recognized key (changed or not); the UI shows the changed ones.
    ``warnings`` carries informational (non-blocking) strings: firmware/serial
    mismatches and any snapshot keys skipped because the device doesn't know
    them. Supports schema 1 (``gains`` -> tuning) and schema 2. Non-finite
    tokens in the snapshot are decoded back to floats."""
    snapshot = _decode(snapshot)
    warnings: list[str] = []

    # Identity mismatches are informational only.
    snap_fw = snapshot.get("firmware")
    if snap_fw is not None:
        try:
            dev_fw = list(dev.fw_version())
        except Exception:  # noqa: BLE001
            dev_fw = None
        if dev_fw is not None and list(snap_fw) != dev_fw:
            warnings.append(
                f"Firmware mismatch: backup {'.'.join(map(str, snap_fw))} "
                f"vs device {'.'.join(map(str, dev_fw))}")
    snap_serial = snapshot.get("serial")
    if snap_serial is not None:
        try:
            dev_serial = dev.serial_hex()
        except Exception:  # noqa: BLE001
            dev_serial = None
        if dev_serial is not None and snap_serial != dev_serial:
            warnings.append(
                f"Serial mismatch: backup {snap_serial} vs device {dev_serial}")

    schema = snapshot.get("schema")
    if "tuning" in snapshot or schema == 2:
        tuning = snapshot.get("tuning", {}) or {}
        motion = snapshot.get("motion", {}) or {}
        has_cm = "control_mode" in snapshot
        cm_target = snapshot.get("control_mode")
    else:  # schema 1 / gains-only
        tuning = snapshot.get("gains", {}) or {}
        motion = {}
        has_cm = False
        cm_target = None

    items: list[RestoreItem] = []

    # tuning section
    tuning_targets = set(dev._tuning_targets().keys())
    live_tuning = dev.get_tuning()
    for key, target in tuning.items():
        if key not in tuning_targets:
            warnings.append(f"Skipped unknown parameter '{key}'")
            continue
        current = live_tuning.get(key)  # None if fw doesn't expose it
        items.append(RestoreItem(
            key=key, section="tuning", current=current, target=target,
            changed=_is_changed(current, target),
            sensitive=key in SENSITIVE_KEYS))

    # motion section
    if motion:
        live_motion = dev.get_motion_config()
        motion_keys = set(live_motion.keys())
        for key, target in motion.items():
            if key not in motion_keys:
                warnings.append(f"Skipped unknown motion parameter '{key}'")
                continue
            current = live_motion.get(key)
            items.append(RestoreItem(
                key=key, section="motion", current=current, target=target,
                changed=_is_changed(current, target), sensitive=False))

    # control_mode
    if has_cm:
        try:
            current = dev.get_control_mode()
        except Exception:  # noqa: BLE001
            current = None
        items.append(RestoreItem(
            key="control_mode", section="control_mode", current=current,
            target=cm_target, changed=_is_changed(current, cm_target),
            sensitive=False))

    return items, warnings


# --- restore application -----------------------------------------------------
_MISSING = object()


def _verify(dev_read, key, target) -> tuple:
    """Read-back verification for motion/control after a write."""
    try:
        actual = dev_read()
    except Exception as e:  # noqa: BLE001
        return (False, f"readback error: {e}")
    if values_match(target, actual):
        return (True, actual)
    return (False, f"readback {_fmt_value(actual)} != {_fmt_value(target)}")


def _apply_motion(dev: Device, kw: dict) -> dict:
    """Apply motion params with read-back. input_mode goes through
    set_input_mode; the rest through set_motion; both are verified against a
    fresh get_motion_config()."""
    out: dict = {}
    kw = dict(kw)
    input_mode = kw.pop("input_mode", None) if "input_mode" in kw else _MISSING
    if input_mode is not _MISSING:
        try:
            dev.set_input_mode(input_mode)
        except Exception as e:  # noqa: BLE001
            out["input_mode"] = (False, f"write error: {e}")
        else:
            out["input_mode"] = _verify(
                lambda: dev.get_motion_config().get("input_mode"),
                "input_mode", input_mode)
    if kw:
        try:
            dev.set_motion(**kw)
        except Exception as e:  # noqa: BLE001
            for k in kw:
                out[k] = (False, f"write error: {e}")
            return out
        live = dev.get_motion_config()
        for k, target in kw.items():
            out[k] = _verify(lambda k=k: live.get(k), k, target)
    return out


def apply_restore(dev: Device, items) -> dict:
    """Apply the given RestoreItems and return merged ``{key: (ok, msg)}``.

    Tuning items go through Device.set_tuning (which already verifies); motion
    and control_mode are applied and read back here."""
    results: dict = {}
    tuning_kw: dict = {}
    motion_kw: dict = {}
    control_mode = _MISSING
    for it in items:
        if it.section == "tuning":
            tuning_kw[it.key] = it.target
        elif it.section == "motion":
            motion_kw[it.key] = it.target
        elif it.section == "control_mode":
            control_mode = it.target
    if tuning_kw:
        results.update(dev.set_tuning(**tuning_kw))
    if motion_kw:
        results.update(_apply_motion(dev, motion_kw))
    if control_mode is not _MISSING:
        try:
            dev.set_control_mode(control_mode)
        except Exception as e:  # noqa: BLE001
            results["control_mode"] = (False, f"write error: {e}")
        else:
            results["control_mode"] = _verify(
                dev.get_control_mode, "control_mode", control_mode)
    return results


def save_to_nvm(dev: Device) -> None:
    """Persist current config to the ODrive's non-volatile memory."""
    dev.save()
