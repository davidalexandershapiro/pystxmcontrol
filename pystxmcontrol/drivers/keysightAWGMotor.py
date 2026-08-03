"""
Leaf motor for the Keysight 33500B AWG trajectory controller.

The per-axis analogue of ``mcsMotor``: it holds a reference to the shared
``keysightAWGController`` and, on ``connect``, publishes its (scan-axis -> AWG channel)
mapping so the controller can assemble the 2-D X/Y trajectory.  Static ``moveTo``
positions the piezo via a DC output; trajectory motion is driven by the controller's
``setup_xy``/``acquire_xy`` through ``derivedPiezo``.

Use ``units=1.0``/``offset=0.0`` in config so ``derivedPiezo.scale2controller`` passes
microns straight through to ``setup_xy`` (the AWG normalizes internally).
"""

from pystxmcontrol.controller.motor import motor


class keysightAWGMotor(motor):

    def __init__(self, controller=None, config=None):
        self.controller = controller
        self.config = config if config is not None else {
            "minValue": -50, "maxValue": 50, "units": 1.0, "offset": 0.0}
        self.simulation = True
        self.position = 0.0
        self.offset = 0.0
        self.units = 1.0
        self.axis = None
        self._axis = 1          # AWG output channel (1|2), from controller_index
        self.stage_type = "piezo"
        self.moving = False
        self.lock = None

    # ------------------------------------------------------------------ #
    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        return self.moving

    def moveTo(self, pos, **kwargs):
        if not self.checkLimits(pos):
            print("[keysightAWGMotor] software limits exceeded for axis %s: %s"
                  % (self.axis, pos))
            return self.position
        self.position = pos
        if not self.simulation and self.controller is not None:
            self.controller.moveTo(self._axis, pos)
        return self.position

    def moveBy(self, step, **kwargs):
        return self.moveTo(self.position + step)

    def getPos(self, **kwargs):
        # The AWG commands position open-loop; achieved position is read back by the
        # USB-1808X ADC during a scan, not here.  Return the last commanded value.
        return self.position

    def stop(self):
        if not self.simulation and self.controller is not None:
            self.controller.disconnect()

    def moveLine(self):
        pass

    # ------------------------------------------------------------------ #
    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs:
            self.logger = kwargs["logger"]
        self.simulation = self.config.get("simulation", True)
        self.lock = self.controller.lock if self.controller is not None else None
        self.axis = axis
        self.stage_type = self.config.get("stage_type", "piezo")
        if axis == 'x':
            self._axis = self.config.get("controller_index", 1)
        elif axis == 'y':
            self._axis = self.config.get("controller_index", 2)
        elif axis == 'z':
            self._axis = self.config.get("controller_index", 3)
        if not self.simulation and self.controller is not None:
            self.controller.setup_axis(self._axis, stage_type=self.stage_type)
            # Publish (scan axis -> AWG channel) so the shared controller can build the
            # 2-D trajectory across both fine axes.
            self.controller.register_axis(axis, self._axis, stage_type=self.stage_type)
        return True
