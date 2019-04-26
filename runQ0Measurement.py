from __future__ import print_function
from __future__ import division
from subprocess import CalledProcessError
from time import sleep

from numpy import mean

from cryomodule import Cryomodule
from sys import stderr, stdout
from matplotlib import pyplot as plt
from datetime import datetime, timedelta
from epicsShell import cagetPV, caputPV
from calculateQ0 import parseRawData, MYSAMPLER_TIME_INTERVAL
from scipy.stats import linregress
from math import log10

if hasattr(__builtins__, 'raw_input'):
    input = raw_input


DESIRED_LL = 95


def runQ0Meas(cavity, desiredGradient):
    # type: (Cryomodule.Cavity, float) -> None
    try:
        cavity.refGradVal = desiredGradient
        checkCryo(cavity, 2)

        # checkAcqControl(cavity)
        # setPowerSSA(cavity, True)
        # characterize(cavity)
        #
        # #caputPV(cavity.genAcclPV("SEL_ASET"), "15")
        #
        # # Start with pulsed mode
        # setModeRF(cavity, "4")
        #
        # setStateRF(cavity, True)
        # pushGoButton(cavity)
        #
        # checkAndSetOnTime(cavity)
        # checkDrive(cavity)
        #
        # phaseCavity(cavity)
        #
        # #lowerAmplitude(cavity)
        #
        # # go to CW
        # setModeRF(cavity, "2")
        #
        # walkToGradient(cavity, desiredGradient)
        #
        # startTime = holdGradient(cavity, desiredGradient)
        #
        # powerDown(cavity)
        #
        # endTime = launchHeaterRun(cavity)

    # %Y-%m-%d-%H:%M


    except(CalledProcessError, IndexError, OSError, ValueError,
           AssertionError) as e:
        writeAndFlushStdErr("Procedure failed with error:\n{E}\n".format(E=e))
        # powerDown(cavity)

def writeAndFlushStdErr(message):
    stderr.write("\n{MSSG}\n".format(MSSG=message))
    stderr.flush()

def characterize(cavity):

    def checkAndPush(basePV, pushPV, param, newPV=None):
        oldVal = float(cagetPV(cavity.genAcclPV(basePV)))

        newVal = (float(cagetPV(cavity.genAcclPV(newPV)))
                  if newPV
                  else float(cagetPV(cavity.genAcclPV(basePV + "_NEW"))))

        if abs(newVal - oldVal) < 0.15:
            caputPV(cavity.genAcclPV(pushPV), "1")

        else:
            print("Old and new {PARAM} differ by more than 0.15 - please "
                  "inspect and push manually".format(PARAM=param))


    caputPV(cavity.genAcclPV("SSACALSTRT"), "1")

    checkAndPush("SLOPE", "PUSH_SSASLOPE.PROC", "slopes")

    caputPV(cavity.genAcclPV("PROBECALSTRT"), "1")

    checkAndPush("QLOADED", "PUSH_QLOADED.PROC", "Loaded Qs")

    checkAndPush("CAV:SCALER_SEL.B", "PUSH_CAV_SCALE.PROC", "Cavity Scales",
                 "CAV:CAL_SCALEB_NEW")


def launchHeaterRun(cavity):
    # type: (Cryomodule.Cavity) -> datetime
    # TODO check cryo levels

    for heaterPV in cavity.heaterPVs:
        curVal = float(cagetPV(heaterPV))
        caputPV(heaterPV, str(curVal + 1))
        
    startTime = datetime.now()
    
    print("\nStart time: {START}".format(START=startTime))
    
    stdout.write("\nRunning heaters for 40 minutes...")
    
    while (datetime.now() - startTime).total_seconds() < 2400:
        stdout.write(".")
        stdout.flush()

        # Abort the run if the downstream liquid helium level dips below 90
        if float(cagetPV(cavity.dsLevelPV)) < 90:
            break
        sleep(5)

    endTime = datetime.now()
    print("\nEnd Time: {END}".format(END=endTime))
    duration = (endTime - startTime).total_seconds() / 3600
    print("Duration in hours: {DUR}".format(DUR=duration))

    for heaterPV in cavity.heaterPVs:
        curVal = float(cagetPV(heaterPV))
        caputPV(heaterPV, str(curVal - 1))

    return endTime
        

def checkAcqControl(cavity):
    print("Checking Waveform Data Acquisition Control...")
    for infix in ["CAV", "FWD", "REV", "DRV", "DAC"]:
        enablePV = cavity.genAcclPV(infix + ":ENABLE")
        if float(cagetPV(enablePV)) != 1:
            print("Enabling {INFIX}".format(INFIX=infix))
            caputPV(enablePV, "1")
    
    suffixValPairs = [("MODE", 1), ("HLDOFF", 0.1), ("STAT_START", 0.065),
                      ("STAT_WIDTH", 0.004), ("DECIM", 255)]
    
    for suffix, val in suffixValPairs:
        pv = cavity.genAcclPV("ACQ_" + suffix)
        if float(cagetPV(enablePV)) != val:
            print("Setting {SUFFIX}".format(SUFFIX=suffix))
            caputPV(pv, str(val))

        
def checkAndSetOnTime(cavity):
    print("Checking RF Pulse On Time...")
    onTimePV = cavity.genAcclPV("PULSE_ONTIME")
    onTime = cagetPV(onTimePV)
    if onTime != "70":
        print("Setting RF Pulse On Time to 70ms")
        caputPV(onTimePV, "70")
        
def checkCryo(cavity, numHours, checkForFlatness=True):
    print("\nDetermining Required JT Valve Position...")
    csvReader = parseRawData(datetime.now() - timedelta(hours=numHours),
                             int((60 / MYSAMPLER_TIME_INTERVAL)
                                 * (numHours * 60)),
                             [cavity.dsLevelPV, cavity.valvePV])

    csvReader.next()
    valveVals = []
    llVals = []

    for row in csvReader:
        try:
            valveVals.append(float(row.pop()))
            llVals.append(float(row.pop()))
        except ValueError:
            pass

    m, b, _, _, _ = linregress(range(len(valveVals)), valveVals)

    if not checkForFlatness or (checkForFlatness and log10(abs(m)) < 5):
        desPos = round(mean(valveVals), 1)
        waitForLL(cavity)
        waitForJT(cavity, desPos)
        print("\nCryo at required values")

    else:
        print("Need to figure out new JT valve position")

        waitForLL(cavity)

        writeAndWait("\nWaiting 1 hour 45 minutes for LL to stabilize...")

        start = datetime.now()
        while((datetime.now() - start).total_seconds() < 6300):
            writeAndWait(".", 5)
            
        checkCryo(cavity, 0.25, False)


def writeAndWait(message, timeToWait=0):
    stdout.write(message)
    stdout.flush()
    sleep(timeToWait)


def waitForLL(cavity):
    writeAndWait("\nWaiting for downstream liquid level to be {LL}%..."
                 .format(LL=DESIRED_LL))

    while abs(DESIRED_LL - float(cagetPV(cavity.dsLevelPV))) > 1:
        writeAndWait(".", 5)

    print("\ndownstream liquid level at required value")


def waitForJT(cavity, desPosJT):
    # type: (Cryomodule.Cavity, float) -> None

    writeAndWait("\nWaiting for JT Valve to be locked at {POS}..."
                 .format(POS=desPosJT))

    mode = cagetPV(cavity.jtModePV)

    if mode == "0":
        while float(cagetPV(cavity.jtPosSetpointPV)) != desPosJT:
            writeAndWait(".", 5)

    else:

        while float(cagetPV(cavity.cvMinPV)) != desPosJT:
            writeAndWait(".", 5)

        while float(cagetPV(cavity.cvMaxPV)) != desPosJT:
            writeAndWait(".", 5)

    print("\nJT Valve locked")


def setPowerSSA(cavity, turnOn):
    # type: (Cryomodule.Cavity, bool) -> None

    # Using double curly braces to trick it into a partial formatting
    ssaFormatPV = cavity.genAcclPV("SSA:{SUFFIX}")

    def genPV(suffix):
        return ssaFormatPV.format(SUFFIX=suffix)

    ssaStatusPV = genPV("StatusMsg")

    value = cagetPV(ssaStatusPV)

    if turnOn:
        stateMap = {"desired": "3", "opposite": "2", "pv": "PowerOn"}
    else:
        stateMap = {"desired": "2", "opposite": "3", "pv": "PowerOff"}

    if value != stateMap["desired"]:
        if value == stateMap["opposite"]:
            print("\nSetting SSA power...")
            caputPV(genPV(stateMap["pv"]), "1")

            # can't use parentheses with asserts, apparently
            assert cagetPV(ssaStatusPV) == stateMap["desired"], \
                "Could not set SSA Power"
        else:
            print("\nResetting SSA...")
            caputPV(genPV("FaultReset"), "1")
            assert cagetPV(ssaStatusPV) in ["2", "3"], \
                "Could not reset SSA"
            setPowerSSA(cavity, turnOn)

    print("SSA power set\n")


def setModeRF(cavity, modeDesired):
    # type: (Cryomodule.Cavity, str) -> None

    rfModePV = cavity.genAcclPV("RFMODECTRL")

    if cagetPV(rfModePV) is not modeDesired:
        caputPV(rfModePV, modeDesired)
        assert cagetPV(rfModePV) == modeDesired, "Unable to set RF mode"


def setStateRF(cavity, turnOn):
    # type: (Cryomodule.Cavity, bool) -> None

    rfStatePV = cavity.genAcclPV("RFSTATE")
    rfControlPV = cavity.genAcclPV("RFCTRL")

    rfState = cagetPV(rfStatePV)

    desiredState = ("1" if turnOn else "0")

    if rfState != desiredState:
        print("\nSetting RF State...")
        caputPV(rfControlPV, desiredState)
        #assert cagetPV(rfStatePV) == desiredState,\
            #"Unable to set RF state"

    print("RF state set\n")


def pushGoButton(cavity):
    # type: (Cryomodule.Cavity) -> None
    rfStatePV = cavity.genAcclPV("PULSEONSTRT")
    caputPV(rfStatePV, "1")
    sleep(2)
    assert cagetPV(rfStatePV) == "1", \
        "Unable to set RF state"


def checkDrive(cavity):
    # type: (Cryomodule.Cavity) -> None

    print("Checking drive...")

    drivePV = cavity.genAcclPV("SEL_ASET")
    currDrive = float(cagetPV(drivePV))

    while (float(cagetPV(cavity.gradPV)) < 1) or (currDrive < 15):
        
        print("Increasing drive...")
        driveDes = str(currDrive + 1)

        caputPV(drivePV, driveDes)
        pushGoButton(cavity)

        currDrive = float(cagetPV(drivePV))

    print("Drive set")


def phaseCavity(cavity):
    # type: (Cryomodule.Cavity) -> None

    waveformFormatStr = cavity.genAcclPV("{INFIX}:AWF")

    def getWaveformPV(infix):
        return waveformFormatStr.format(INFIX=infix)

    # get rid of trailing zeros - might be more elegant way of doing this
    def trimWaveform(inputWaveform):
        try:
            maxValIdx = inputWaveform.index(max(inputWaveform))
            del inputWaveform[maxValIdx:]

            first = inputWaveform.pop(0)
            while inputWaveform[0] >= first:
                first = inputWaveform.pop(0)
        except IndexError:
            pass

    def getAndTrimWaveforms():
        res = []

        for suffix in ["REV", "FWD", "CAV"]:
            res.append(cagetPV(getWaveformPV(suffix), startIdx=2))
            res[-1] = list(map(lambda x: float(x), res[-1]))
            trimWaveform(res[-1])

        return res

    def getLine(inputWaveform, lbl):
        return ax.plot(range(len(inputWaveform)), inputWaveform, label=lbl)

    revWaveform, fwdWaveform, cavWaveform = getAndTrimWaveforms()

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

    phasePV = cavity.genAcclPV("SEL_POFF")

    minVal = min(revWaveform)

    print("Minimum reverse waveform value: {MIN}".format(MIN=minVal))
    step = 1

    while abs(minVal) > 0.5:
        val = float(cagetPV(phasePV))

        print("step: {STEP}".format(STEP=step))
        newVal = val + step
        caputPV(phasePV, str(newVal))

        if float(cagetPV(phasePV)) != newVal:
            writeAndFlushStdErr("Mismatch between desired and actual phase")

        revWaveform, fwdWaveform, cavWaveform = getAndTrimWaveforms()

        lineWaveformPairs = [(lineRev, revWaveform), (lineCav, cavWaveform),
                             (lineFwd, fwdWaveform)]

        for line, waveform in lineWaveformPairs:
            line.set_data(range(len(waveform)), waveform)

        ax.set_autoscale_on(True)
        ax.autoscale_view(True, True, True)

        fig.canvas.draw()
        fig.canvas.flush_events()

        prevMin = minVal
        minVal = min(revWaveform)
        print("Minimum reverse waveform value: {MIN}".format(MIN=minVal))

        # I think this accounts for inflection points? Hopefully the decrease
        # in step size addresses the potential for it to get stuck
        if (prevMin <= 0 < minVal) or (prevMin >= 0 > minVal):
            step *= -0.5

        elif abs(minVal) > abs(prevMin) + 0.01:
            step *= -1


def lowerAmplitude(cavity):
    print("Lowering amplitude")
    caputPV(cavity.genAcclPV("ADES"), "2")


def walkToGradient(cavity, desiredGradient):
    amplitudePV = cavity.genAcclPV("ADES")
    step = 0.5
    gradient = float(cagetPV(cavity.gradPV))
    prevGradient = gradient
    diff = gradient - desiredGradient
    prevDiff = diff
    print("Walking gradient...")

    while abs(diff) > 0.05:
        gradient = float(cagetPV(cavity.gradPV))

        if gradient < (prevGradient / 2):
            raise AssertionError("Detected a quench - aborting")

        currAmp = float(cagetPV(amplitudePV))
        diff = gradient - desiredGradient
        mult = 1 if (diff <= 0) else -1

        if (prevDiff >= 0 > diff) or (prevDiff <= 0 < diff):
            step *= (0.5 if step > 0.01 else 1.5)

        caputPV(amplitudePV, str(currAmp + mult*step))

        prevDiff = diff
        sleep(2.5)

    print("Gradient at desired value")

def holdGradient(cavity, desiredGradient):
    # type: (Cryomodule.Cavity, float) -> datetime

    amplitudePV = cavity.genAcclPV("ADES")

    startTime = datetime.now()

    step = 0.01
    prevDiff = float(cagetPV(cavity.gradPV)) - desiredGradient

    print("\nStart time: {START}".format(START=startTime))

    stdout.write("\nHolding gradient for 40 minutes...")
    stdout.flush()

    hitTarget = False

    while (datetime.now() - startTime).total_seconds() < 2400:
        stdout.write(".")

        gradient = float(cagetPV(cavity.gradPV))
        
        if hitTarget and gradient <= (desiredGradient / 4):
            raise AssertionError("Detected a quench - aborting")

        currAmp = float(cagetPV(amplitudePV))

        diff = gradient - desiredGradient

        if abs(diff) <= 0.01:
            hitTarget = True

        mult = 1 if (diff <= 0) else -1

        if (prevDiff >= 0 > diff) or (prevDiff <= 0 < diff):
            step *= (0.5 if step > 0.01 else 1.5)

        caputPV(amplitudePV, str(currAmp + mult * step))

        prevDiff = diff

        sleep(15)
        stdout.flush()

    print("\nEnd Time: {END}".format(END=datetime.now()))
    duration = (datetime.now() - startTime).total_seconds() / 3600
    print("Duration in hours: {DUR}".format(DUR=duration))
    return startTime


def powerDown(cavity):
    try:
        print("\nPowering down...")
        setStateRF(cavity, False)
        setPowerSSA(cavity, False)
        caputPV(cavity.genAcclPV("SEL_ASET"), "15")
        lowerAmplitude(cavity)

    except(CalledProcessError, IndexError, OSError,
           ValueError, AssertionError) as e:
        writeAndFlushStdErr("Powering down failed with error:\n{E}\n"
                            .format(E=e))


if __name__ == "__main__":
    # noinspection PyUnboundLocalVariable
    runQ0Meas(Cryomodule(int(input("SLAC CM: ")), int(input("JLAB CM: ")),
                         None, 0, 0).cavities[int(input("Cavity: "))],
              float(input("Desired Gradient: ")))
