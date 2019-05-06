from __future__ import division
from cryomodule import Cryomodule
from epicsShell import cagetPV, caputPV
from time import sleep
from math import ceil


TARGET_LL = 95


CAVITY_MAX_HEAT_LOAD = 15


CAVITY_MIN_HEAT_LOAD = 0


HEAT_LOAD_PARAMS = {2: {"low": 16, "high": 120}, 3: {"low": 64, "high": 120}}


def walkHeaters(cryomodule, delta):
    # type: (Cryomodule, float) -> None

    step = 0.5

    def stepCavities():

        for cavity in cryomodule.cavities:
            heaterSetpointPV = cavity.genHeaterPV("POWER_SETPT")
            currSetting = float(cagetPV(heaterSetpointPV))
            diff = delta - currSetting
            mult = 1 if diff > 0 else -1

            cavAtTarget = abs(diff) <= 0.1

            if not cavAtTarget:
                caputPV(heaterSetpointPV, str(currSetting + mult * step))

    while not stepCavities():
        print("Waiting 30s for cryo to stabilize...")
        sleep(30)


def runCalibration(cryomodule):
    walkHeaters(cryomodule)


if __name__ == "__main__":
    # Should be sorted in reverse order
    heatLoads = [13, 10, 7, 4, 1]

    # noinspection PyCompatibility
    cryoModule = Cryomodule(int(raw_input("SLAC CM: ")),
                            int(raw_input("JLAB CM: ")), None, 0, 0)

    currHeatLoad = 0

    for cavity in cryoModule.cavities:
        currHeatLoad += float(cagetPV(cavity.genHeaterPV("POWER_SETPT")))

    maxLoad = HEAT_LOAD_PARAMS[cryoModule.cryModNumJLAB]["high"]
    headroom = maxLoad - currHeatLoad

    if headroom < 0:
        print("High heat load detected. (1) Walk down to 120 before calibrating"
              " or (2) calibrate here?")


    if heatLoads[0] > headroom:
        delta = ceil(heatLoads[0] / 8)
        for i in range(1, 9):
            pass