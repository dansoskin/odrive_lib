"""High-rate capture via the ODrive onboard oscilloscope (Qt-free, testable).

The live sampler only reaches ~20 Hz (each feedback() is ~17 sequential USB
round-trips). For real current-loop tuning we need the native control-loop rate.
This module drives the firmware's high-rate capturer (fw 0.6.12+), which records
a chosen set of properties into an on-chip circular buffer at the fixed 8 kHz
control-loop frequency, then downloads the whole window over USB.

Everything here is synchronous and Qt-free so it can be unit-tested with a fake
device. The actual odrive-package plumbing (sync<->async event loop bridging) is
isolated in ``_odrive_runner`` and injected into :class:`CaptureJob` as ``runner``
so tests can substitute a canned implementation.
"""
from __future__ import annotations

import threading

SAMPLE_RATE_HZ = 8000

# Ordered capture presets: (display name, [property paths]).
PRESETS = [
    ("Current loop (Iq)", [
        "axis0.motor.foc.Iq_setpoint",
        "axis0.motor.foc.Iq_measured",
    ]),
    ("Current D/Q", [
        "axis0.motor.foc.Id_setpoint",
        "axis0.motor.foc.Id_measured",
        "axis0.motor.foc.Iq_setpoint",
        "axis0.motor.foc.Iq_measured",
    ]),
    ("Current error + modulation", [
        "axis0.motor.foc.Ierr_d",
        "axis0.motor.foc.Ierr_q",
        "axis0.motor.foc.mod_magn_sqr",
    ]),
    ("Velocity loop", [
        "axis0.controller.vel_setpoint",
        "axis0.pos_vel_mapper.vel",
    ]),
    ("Position loop", [
        "axis0.controller.pos_setpoint",
        "axis0.pos_vel_mapper.pos_abs",
    ]),
    ("Torque", [
        "axis0.controller.effective_torque_setpoint",
        "axis0.motor.torque_estimate",
    ]),
]


def availability(dev) -> tuple[bool, str]:
    """Whether high-rate capture is usable on ``dev``.

    Returns ``(ok, reason)``. ``ok`` is True only when the odrive package ships
    the high-rate capturer, the device exposes ``oscilloscope.trigger_pos`` and
    the firmware is 0.6.12+ (older firmware either lacks the feature or has the
    known trigger_point>0 hang bug). Tolerates ``dev is None`` and any probing
    error by returning a not-ok reason rather than raising."""
    if dev is None:
        return (False, "no device connected")
    try:
        import odrive.high_rate_capturer  # noqa: F401
    except Exception:  # noqa: BLE001 - odrive package too old / not installed
        return (False, "odrive package missing high_rate_capturer")

    try:
        fw = tuple(dev.fw_version())
    except Exception:  # noqa: BLE001 - identity read shouldn't crash the check
        fw = None

    raw = getattr(dev, "raw", None)
    osc = getattr(raw, "oscilloscope", None)
    has_trigger_pos = False
    if osc is not None:
        try:
            has_trigger_pos = hasattr(osc, "trigger_pos")
        except Exception:  # noqa: BLE001 - guarded getattr
            has_trigger_pos = False

    def _fw_str() -> str:
        return f"{fw[0]}.{fw[1]}.{fw[2]}" if fw else "unknown"

    if not has_trigger_pos:
        return (False, f"requires firmware 0.6.12+ (found {_fw_str()})")
    if fw is not None and fw < (0, 6, 12):
        return (False, f"requires firmware 0.6.12+ (found {_fw_str()})")
    return (True, "")


def _odrive_runner(raw, properties, trigger_point, timeout_s, on_armed=None):
    """Real capture using the odrive package. Returns ``{"t": [...s...], "<prop>": [...]}``.

    ``raw`` is the object ``odrive.find_any()`` returned (a ``SyncObject``); it
    carries the RuntimeDevice (``_dev``) and the odrive event loop (``_loop``).
    We mimic what the package's own sync helpers do: run the async
    ``high_rate_capture_start`` / ``trigger_and_download_async`` coroutines on
    that loop from this (background) thread via ``run_on_loop``.

    ``on_armed`` (if given) is invoked after the oscilloscope is configured
    (recording started) and immediately before the trigger, so an optional
    stimulus step lands inside the capture window. Any exception propagates with
    a readable message."""
    from odrive.high_rate_capturer import high_rate_capture_start, TimestampFmt
    from odrive._internal_utils import run_on_loop

    rt = getattr(raw, "_dev", None)
    loop = getattr(raw, "_loop", None)
    if rt is None or loop is None:
        raise RuntimeError(
            "could not obtain the odrive RuntimeDevice/event loop from the "
            "connected device (expected a sync object from odrive.find_any())")

    props = list(properties)

    # Configure + start recording into the on-chip circular buffer.
    capturer = run_on_loop(high_rate_capture_start(rt, props), loop)

    # Fire the optional stimulus right before triggering.
    if on_armed is not None:
        on_armed()

    # trigger -> wait(timeout) -> download the whole buffer as a dict with
    # nanosecond timestamps relative to the trigger.
    data = run_on_loop(
        capturer.trigger_and_download_async(
            trigger_point, timeout_s, dict, TimestampFmt.NANOSECONDS),
        loop)

    ts_ns = data.get("timestamps", [])
    result = {"t": [t / 1e9 for t in ts_ns]}
    for key, series in data.items():
        if key == "timestamps":
            continue
        result[key] = list(series)
    return result


class CaptureJob:
    """One high-rate capture, run on a background thread.

    The actual start/trigger/wait/download work is delegated to ``runner``
    (defaults to :func:`_odrive_runner`; tests inject a fake). ``stimulus`` (if
    given) is passed to the runner as its ``on_armed`` hook so it fires between
    starting the recording and the trigger; ``finalize`` (if given) always runs
    in a ``finally`` block after the capture, whether it succeeded or failed.

    After the thread finishes, exactly one of ``result`` (a dict
    ``{"t": [...], "<prop>": [...]}``) or ``error`` (a string) is set, and
    ``done`` is True. No Qt imports here; the UI polls ``done`` on a timer."""

    def __init__(self, dev, properties, trigger_point, timeout_s,
                 stimulus=None, finalize=None, runner=None):
        self.dev = dev
        self.properties = list(properties)
        self.trigger_point = trigger_point
        self.timeout_s = timeout_s
        self.stimulus = stimulus
        self.finalize = finalize
        self.runner = runner or _odrive_runner
        self.result = None
        self.error = None
        self.done = False
        self._thread = None

    def run_in_thread(self, on_done=None):
        """Start the capture on a daemon thread; returns the Thread."""
        self._thread = threading.Thread(
            target=self._run, args=(on_done,), daemon=True)
        self._thread.start()
        return self._thread

    def _run(self, on_done):
        try:
            self.result = self.runner(
                self.dev.raw, self.properties, self.trigger_point,
                self.timeout_s, on_armed=self.stimulus)
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            self.error = str(e) or repr(e)
        finally:
            if self.finalize is not None:
                try:
                    self.finalize()
                except Exception:  # noqa: BLE001 - teardown must not mask result
                    pass
            self.done = True
            if on_done is not None:
                try:
                    on_done()
                except Exception:  # noqa: BLE001
                    pass
