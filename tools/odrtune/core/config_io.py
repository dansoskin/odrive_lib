"""Config backup/restore to a plain dict (JSON-serializable) and save-to-NVM.

The snapshot intentionally captures the tunable subset we expose in the GUI
(controller gains); it is a versioned dict so it can grow without breaking old
files."""
from __future__ import annotations

from core.device import Device

SCHEMA_VERSION = 1


def backup(dev: Device) -> dict:
    """Read the tunable config into a JSON-serializable dict."""
    return {"schema": SCHEMA_VERSION, "gains": dev.get_gains()}


def restore(dev: Device, snapshot: dict) -> None:
    """Apply a snapshot produced by backup(). Unknown keys are ignored."""
    gains = snapshot.get("gains", {})
    dev.set_gains(
        pos_gain=gains.get("pos_gain"),
        vel_gain=gains.get("vel_gain"),
        vel_integrator_gain=gains.get("vel_integrator_gain"),
    )


def save_to_nvm(dev: Device) -> None:
    """Persist current config to the ODrive's non-volatile memory."""
    dev.save()
