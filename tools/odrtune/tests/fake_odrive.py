"""In-memory fake mimicking the odrive USB object tree, for hardware-free tests.

Only the attributes core/ touches are modeled. save/erase/reboot record calls."""
from types import SimpleNamespace


class FakeAxis:
    def __init__(self):
        self.current_state = 1          # IDLE
        self.requested_state = 1
        self.procedure_result = 0       # SUCCESS
        self.active_errors = 0
        self.disarm_reason = 0
        self.controller = SimpleNamespace(
            input_pos=0.0, input_vel=0.0, input_torque=0.0,
            config=SimpleNamespace(
                control_mode=3, input_mode=1,
                pos_gain=20.0, vel_gain=0.16, vel_integrator_gain=0.32,
            ),
        )
        self.motor = SimpleNamespace(
            foc=SimpleNamespace(Iq_setpoint=0.0, Iq_measured=0.0),
            fet_thermistor=SimpleNamespace(temperature=25.0),
            motor_thermistor=SimpleNamespace(temperature=24.0),
        )
        self.pos_vel_mapper = SimpleNamespace(pos_rel=0.0, vel=0.0)


class FakeODrive:
    def __init__(self):
        self.serial_number = 0x123456789ABC
        self.fw_version_major = 0
        self.fw_version_minor = 6
        self.fw_version_revision = 10
        self.vbus_voltage = 24.0
        self.ibus = 0.5
        self.axis0 = FakeAxis()
        self.saved = False
        self.erased = False
        self.rebooted = False

    def save_configuration(self):
        self.saved = True

    def erase_configuration(self):
        self.erased = True

    def reboot(self):
        self.rebooted = True
