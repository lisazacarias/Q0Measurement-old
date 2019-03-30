from __future__ import print_function
from subprocess import check_output, CalledProcessError, check_call
from time import sleep
from cryomodule import Cryomodule
from sys import stderr
from typing import Optional
from matplotlib import pyplot as plt
from datetime import datetime


def runQ0Meas(cavity):
    # type: (Cryomodule.Cavity) -> None
    try:
        # TODO coordinate with Cryo
        setPowerSSA(cavity, True)

        # Start with pulsed mode
        setModeRF(cavity, "4")

        setStateRF(cavity, True)
        pushGoButton(cavity)

        checkDrive(cavity)

        phaseCavity(cavity)

        # go to CW
        setModeRF(cavity, "2")

        holdGradient(cavity, 16)

        powerDown(cavity)

    except(CalledProcessError, IndexError, OSError,
           ValueError, AssertionError) as e:
        stderr.write("Procedure failed with error:\n{E}\n".format(E=e))
        sleep(0.01)
        powerDown(cavity)


def setPowerSSA(cavity, turnOn):
    # type: (Cryomodule.Cavity, bool) -> None

    # Using double curly braces to trick it into a partial formatting
    ssaFormatPV = cavity.genPV("SSA:{{SUFFIX}}")

    def genPV(suffix):
        return ssaFormatPV.format(SUFFIX=suffix)

    ssaStatusPV = genPV("StatusMsg")

    value = cagetPV(ssaStatusPV).pop()

    if turnOn:
        stateMap = {"desired": "3", "opposite": "2", "pv": "PowerOn"}
    else:
        stateMap = {"desired": "2", "opposite": "3", "pv": "PowerOff"}

    if value != stateMap["desired"]:
        if value == stateMap["opposite"]:
            print("Setting SSA power...")
            caputPV(genPV(stateMap["pv"]), "1")

            # can't use parentheses with asserts, apparently
            assert cagetPV(ssaStatusPV).pop() ==\
                   stateMap["desired"], "Could not set SSA Power"
        else:
            print("Resetting SSA...")
            caputPV(genPV("FaultReset"), "1")
            assert cagetPV(ssaStatusPV).pop() in ["2", "3"],\
                "Could not reset SSA"
            setPowerSSA(cavity, turnOn)

    print("SSA power set")


# PyEpics doesn't work at LERF yet...
def cagetPV(pv, startIdx=1):
    # type: (str, int) -> Optional[List[str]]
    return check_output(["caget", pv, "-n"]).split()[startIdx:]


def caputPV(pv, val):
    # type: (str, str) -> Optional[int]

    out = check_call(["caput", pv, val])
    sleep(2)
    return out


def setModeRF(cavity, modeDesired):
    # type: (Cryomodule.Cavity, str) -> None

    rfModePV = cavity.genPV("RFMODECTRL")

    if cagetPV(rfModePV).pop() is not modeDesired:
        caputPV(rfModePV, modeDesired)
        assert cagetPV(rfModePV).pop() == modeDesired, "Unable to set RF mode"


def setStateRF(cavity, turnOn):
    # type: (Cryomodule.Cavity, bool) -> None

    rfStatePV = cavity.genPV("RFSTATE")
    rfControlPV = cavity.genPV("RFCTRL")

    rfState = cagetPV(rfStatePV).pop()

    desiredState = ("1" if turnOn else "0")

    if rfState != desiredState:
        print("Setting RF State...")
        caputPV(rfControlPV, desiredState)
        assert cagetPV(rfStatePV).pop() == desiredState,\
            "Unable to set RF state"

    print("RF state set")


def pushGoButton(cavity):
    # type: (Cryomodule.Cavity) -> None
    rfStatePV = cavity.genPV("PULSE_DIFF_SUM")
    caputPV(rfStatePV, "1")


def checkDrive(cavity):
    # type: (Cryomodule.Cavity) -> None

    drivePV = cavity.genPV("SEL_ASET")

    while float(cagetPV(cavity.gradientPV).pop()) < 1:
        currDrive = float(cagetPV(drivePV).pop())
        driveDes = str(currDrive + 1)

        caputPV(drivePV, driveDes)
        assert cagetPV(cavity.gradientPV).pop() == driveDes,\
            "Unable to change drive"


def phaseCavity(cavity):
    # type: (Cryomodule.Cavity) -> None

    waveformFormatStr = cavity.genPV("{INFIX}:AWF")

    def getWaveformPV(infix):
        return waveformFormatStr.format(INFIX=infix)

    # get rid of trailing zeros - might be more elegant way of doing this
    def trimWaveform(waveform):
        last = waveform.pop()
        while last == "0":
            last = waveform.pop()

        while waveform[0] == "0":
            waveform.pop(0)

    def getAndTrimWaveforms():
        res = []

        for suffix in ["REV", "CAV", "FWD"]:
            res.append(cagetPV(getWaveformPV(suffix), startIdx=2))
            trimWaveform(res[-1])

        return res

    def getLine(waveform, lbl):
        return ax.plot(range(len(waveform)), waveform, label=lbl)

    revWaveform, cavWaveform, fwdWaveform = getAndTrimWaveforms()

    plt.ion()
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.set_title("Waveforms")
    ax.set_xlabel("Seconds")
    ax.set_ylabel("Amplitude")

    ax.set_autoscale_on(True)
    ax.autoscale_view(True, True, True)

    lineRev, = getLine(revWaveform, "Reverse")
    lineCav, = getLine(cavWaveform, "Cavity")
    lineFwd, = getLine(fwdWaveform, "Forward")

    fig.canvas.draw()
    fig.canvas.flush_events()

    phasePV = cavity.genPV("SEL_POFF")

    minVal = min(revWaveform)
    mult = 1

    lineWaveformPairs = [(lineRev, revWaveform), (lineCav, cavWaveform),
                         (lineFwd, fwdWaveform)]

    while abs(minVal) > 0.1:
        val = float(cagetPV(phasePV).pop())

        newVal = val + (mult * 1)
        caputPV(phasePV, str(newVal))

        assert float(cagetPV(phasePV).pop()) == newVal,\
            "Unable to set phase offset"

        revWaveform, cavWaveform, fwdWaveform = getAndTrimWaveforms()

        for line, waveform in lineWaveformPairs:
            line.set_data(range(waveform), waveform)

        ax.set_autoscale_on(True)
        ax.autoscale_view(True, True, True)

        fig.canvas.draw()
        fig.canvas.flush_events()

        prevMin = minVal
        minVal = min(revWaveform)

        # I think this accounts for inflection points? Hopefully the decrease
        # in step size addresses the potential for it to get stuck
        if (prevMin <= 0 and minVal > 0) or (prevMin >= 0 and minVal < 0):
            mult *= -0.5

        elif abs(minVal) > abs(prevMin):
            mult *= -1


def holdGradient(cavity, desiredGradient):
    # type: (Cryomodule.Cavity, float) -> None

    amplitudePV = cavity.genPV("ADES")

    startTime = datetime.now()

    step = 0.5
    prevDiff = float(cagetPV(cavity.gradientPV).pop()) - desiredGradient

    # Spin for 40 minutes
    while (datetime.now() - startTime).total_seconds() < 2400:

        gradient = float(cagetPV(cavity.gradientPV).pop())
        currAmp = float(cagetPV(amplitudePV).pop())

        diff = gradient - desiredGradient

        mult = 1 if (diff <= 0) else -1

        if (prevDiff >= 0 and diff < 0) or (prevDiff <= 0 and diff > 0):
            step *= (0.5 if step > 0.01 else 1.5)

        caputPV(amplitudePV, str(currAmp + mult*step))

        prevDiff = diff

        sleep(1)


def powerDown(cavity):
    try:
        setStateRF(cavity, False)
        setPowerSSA(cavity, False)

    except(CalledProcessError, IndexError, OSError,
           ValueError, AssertionError) as e:
        stderr.write("Powering down failed with error:\n{E}\n".format(E=e))
        sleep(0.01)


if __name__ == "__main__":
    runQ0Meas(Cryomodule(12, 2, None, 0, 0).cavities[1])
