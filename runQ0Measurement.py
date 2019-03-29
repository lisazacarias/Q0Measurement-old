from __future__ import print_function
from subprocess import check_output, CalledProcessError, check_call
from time import sleep
from cryomodule import Cryomodule
from sys import stderr
from typing import Optional
from matplotlib import pyplot as plt
from datetime import datetime


# PyEpics doesn't work at LERF yet...
def cagetPV(prefix, suffix=None, startIdx=1):
    # type: (str, str, int) -> Optional[List[str]]

    try:
        if suffix:
            assert "{SUFFIX}" in prefix, "PV prefix incorrectly formatted"
            output = check_output(["caget", prefix.format(SUFFIX=suffix), "-n"])
        else:
            output = check_output(["caget", prefix, "-n"])

        return output.split()[startIdx:]

    except (CalledProcessError, IndexError, OSError, AssertionError) as e:
        stderr.write("Unable to caget PV {PREFIX}\n{E}\n".format(PREFIX=prefix,
                                                                 E=e))
        sleep(0.01)
        return


def caputPV(prefix, val, suffix=None):
    # type: (str, str, str) -> Optional[int]

    try:
        if suffix:
            assert "{SUFFIX}" in prefix, "PV prefix incorrectly formatted"
            return check_call(["caput", prefix.format(SUFFIX=suffix), val])
        else:
            return check_call(["caput", prefix, val])

    except (CalledProcessError, AssertionError) as e:
        pv = prefix.format(SUFFIX=suffix)
        stderr.write("Unable to caput PV {PV}\n{E}\n".format(PV=pv, E=e))
        sleep(0.01)
        return


def turnOnSSA(cavity):
    # type: (Cryomodule.Cavity) -> Optional[str]

    print("Turning SSA on...")

    # Using double curly braces to trick it into a partial formatting
    ssaFormatPV = "ACCL:L1B:0{CM}{CAV}0:SSA:{{SUFFIX}}"
    ssaPrefixPV = ssaFormatPV.format(CM=cavity.cryModNumJLAB,
                                     CAV=cavity.cavityNumber)

    value = cagetPV(ssaPrefixPV, "StatusMsg")

    if not value:
        stderr.write("Unable to get SSA Status. Aborting.\n")
        return

    value = value[0]

    # If the SSA is neither on nor off, try a reset
    if value not in ["2", "3"]:

        if not caputPV(ssaPrefixPV, "1", "FaultReset"):
            return

        # Giving the reset some time to go through
        sleep(2)

        value = cagetPV(ssaPrefixPV, "StatusMsg")

        if not value or value[0] not in ["2", "3"]:
            stderr.write("Unable to reset SSA. Aborting.\n")
            return

    if value[0] == "2":
        # TODO Check if RF is off first?
        if not caputPV(ssaPrefixPV, "1", "PowerOn"):
            stderr.write("Unable to turn on SSA. Aborting.\n")
            return

    else:
        print("SSA turned on")
        return value


def turnOnRF(cavity):
    # type: (Cryomodule.Cavity) -> Optional[str]
    print("Turning RF on...")

    rfStateFormatPV = "ACCL:L1B:0{CM}{CAV}0:RFSTATE"
    rfStatePV = rfStateFormatPV.format(CM=cavity.cryModNumJLAB,
                                       CAV=cavity.cavityNumber)

    rfStateControlPV = "ACCL:L1B:0{CM}{CAV}0:RFCTRL"
    rfControlPV = rfStateControlPV.format(CM=cavity.cryModNumJLAB,
                                          CAV=cavity.cavityNumber)

    rfState = cagetPV(rfStatePV)

    if not rfState:
        stderr.write("Unable to get RF status. Aborting.\n")
        return

    rfIsOn = (rfState[0] == "1")

    if rfIsOn:
        print("RF already on.")
        return rfState

    else:

        if not caputPV(rfControlPV, "1"):
            stderr.write("Unable to turn RF on. Aborting.\n")
            return

        sleep(2)

        rfState = cagetPV(rfStatePV)

        if not rfState:
            stderr.write("Unable to get RF status. Aborting.\n")
            return

        rfIsOn = (rfState[0] == "1")

        if rfIsOn:
            print("RF turned on.")
            return rfState

        else:
            stderr.write("Unable to turn RF on. Aborting.\n")
            return


def checkModeRF(cavity, modeDesired):
    # type: (Cryomodule.Cavity, str) -> Optional[str]

    rfModeFormatPV = "ACCL:L1B:0{CM}{CAV}0:RFMODECTRL"
    rfModePV = rfModeFormatPV.format(CM=cavity.cryModNumJLAB,
                                     CAV=cavity.cavityNumber)

    mode = cagetPV(rfModePV)

    if not mode:
        stderr.write("Unable to get RF mode. Aborting.\n")
        return

    mode = mode[0]

    if mode is not modeDesired:
        if not caputPV(rfModePV, modeDesired):
            stderr.write("Unable to set RF mode. Aborting.\n")
            return

        sleep(2)
        mode = cagetPV(rfModePV)

        if not mode:
            stderr.write("Unable to get RF mode. Aborting.\n")
            return

        mode = mode[0]

        if mode is not modeDesired:
            stderr.write("Unable to set RF mode. Aborting.\n")
            return

    return mode


def phaseCavity(cavity):
    # type: (Cryomodule.Cavity) -> Optional[float]

    def getWaveformPV(midfix):
        formatStr = "ACCL:L1B:0{CM}{CAV}0:{MIDFIX}:AWF"
        return formatStr.format(CM=cavity.cryModNumJLAB,
                                CAV=cavity.cavityNumber, MIDFIX=midfix)

    def trimWaveform(waveform):
        last = waveform.pop()
        while last == "0":
            last = waveform.pop()

    cavWaveformPV = getWaveformPV("CAV")
    forwardWaveformPV = getWaveformPV("FWD")
    reverseWaveformPV = getWaveformPV("REV")

    reverseWaveform = cagetPV(reverseWaveformPV, startIdx=2)
    cavWaveform = cagetPV(cavWaveformPV, startIdx=2)
    forwardWaveform = cagetPV(forwardWaveformPV, startIdx=2)

    if not reverseWaveform or not cavWaveform or not forwardWaveform:
        stderr.write("Unable to get waveforms. Aborting.\n")
        return

    trimWaveform(reverseWaveform)
    trimWaveform(cavWaveform)
    trimWaveform(forwardWaveform)

    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.set_title("Waveforms")
    ax.set_xlabel("Amplitude")
    ax.set_ylabel("")

    ax.plot(range(0, len(reverseWaveform)), reverseWaveform, label="Reverse")
    ax.plot(range(0, len(cavWaveform)), cavWaveform, label="Cav")
    ax.plot(range(0, len(forwardWaveform)), forwardWaveform, label="Forward")

    phaseFormatPV = "ACCL:L1B:0{CM}{CAV}0:SEL_POFF"
    phasePV = phaseFormatPV.format(CM=cavity.cryModNumJLAB,
                                   CAV=cavity.cavityNumber)

    # TODO pick waveform tolerance
    minVal = min(reverseWaveform)
    mult = 1
    while abs(minVal) > 0.5:
        val = cagetPV(phasePV)
        if not val:
            stderr.write("Unable to get phase offset. Aborting.\n")
            return

        try:
            val = float(val[0])
        except ValueError:
            stderr.write("Phase offset invalid. Aborting.\n")
            return

        # TODO figure out step size
        newVal = val + (mult * 0.1)
        status = caputPV(phasePV, str(newVal))

        if not status:
            stderr.write("Unable to set phase offset. Aborting.\n")
            return

        sleep(0.5)

        val = cagetPV(phasePV)
        if not val:
            stderr.write("Unable to get phase offset. Aborting.\n")
            return

        try:
            val = float(val[0])
            if val != newVal:
                stderr.write("Unable to set phase offset. Aborting.\n")
                return

        except ValueError:
            stderr.write("Phase offset invalid. Aborting.\n")
            return

        reverseWaveform = cagetPV(reverseWaveformPV, startIdx=2)
        if not reverseWaveform:
            stderr.write("Unable to get waveform. Aborting.\n")
            return

        # TODO figure out how to replot
        trimWaveform(reverseWaveform)
        prevMin = minVal
        minVal = min(reverseWaveform)

        if abs(minVal) > prevMin:
            mult *= -1

    return minVal


def holdGradient(cavity, desiredGradient):
    # type: (Cryomodule.Cavity, float) -> Optional[float]

    amplitudeFormatPV = "ACCL:L1B:0{CM}{CAV}0:ADES"
    amplitudePV = amplitudeFormatPV.format(CM=cavity.cryModNumJLAB,
                                           CAV=cavity.cavityNumber)

    startTime = datetime.now()
    val = cagetPV(cavity.gradientPV)

    while (datetime.now() - startTime).total_seconds() < 2400 and val:
        val = float(val[0])

        currAmp = cagetPV(amplitudePV)

        if not currAmp:
            pass

        currAmp = float(currAmp[0])

        if val - desiredGradient > 0.5:
            caputPV(amplitudePV, str(currAmp - 0.1))

        elif val - desiredGradient < -0.5:
            caputPV(amplitudePV, str(currAmp + 0.1))

        sleep(5)

        val = cagetPV(cavity.gradientPV)

    if not val:
        stderr.write("Unable to get gradient. Aborting.\n")
        return


if __name__ == "__main__":
    cav = Cryomodule(12, 2, None, 0, 0).cavities[1]
    # TODO coordinate with Cryo
    if turnOnSSA(cav):
        if turnOnRF(cav):
            # Start with pulsed mode
            if checkModeRF(cav, "4"):
                if phaseCavity(cav):
                    # go to CW
                    if checkModeRF(cav, "2"):
                        # spins for 40 min
                        holdGradient(cav, 16)
                        # TODO turn off RF and SSA? or prompt?