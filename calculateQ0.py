################################################################################
# A utility used to calculate Q0 for a set of cavities in a given cryomodules
# using the change in 2K helium liquid level (LL) per unit time
# Authors: Lisa Zacarias, Ben Ripman
################################################################################

from __future__ import division, print_function
from datetime import datetime
from json import dumps
from csv import reader
from os import walk
from os.path import join, abspath, dirname
from fnmatch import fnmatch
from time import sleep

from matplotlib import pyplot as plt
from numpy import linspace
from sys import stderr
from cryomodule import (Cryomodule, Container, Cavity, DataSession,
                        MYSAMPLER_TIME_INTERVAL, Q0DataSession)

# Used in custom input functions just below
ERROR_MESSAGE = "Please provide valid input"

# Trying to make this compatible with both 2.7 and 3 (input in 3 is the same as
# raw_input in 2.7, but input in 2.7 calls evaluate)
# This somehow broke having it in a separate util file, so moved it here
if hasattr(__builtins__, 'raw_input'):
    input = raw_input


def get_float_lim(prompt, low_lim, high_lim):
    return getNumericalInput(prompt, low_lim, high_lim, float)


def getNumInputFromLst(prompt, lst, inputType):
    response = get_input(prompt, inputType)
    while response not in lst:
        stderr.write(ERROR_MESSAGE + "\n")
        # Need to pause briefly for some reason to make sure the error message
        # shows up before the next prompt
        sleep(0.01)
        response = get_input(prompt, inputType)

    return response


def getNumericalInput(prompt, lowLim, highLim, inputType):
    response = get_input(prompt, inputType)

    while response < lowLim or response > highLim:
        stderr.write(ERROR_MESSAGE + "\n")
        # Need to pause briefly for some reason to make sure the error message
        # shows up before the next prompt
        sleep(0.01)
        response = get_input(prompt, inputType)

    return response


def get_input(prompt, desired_type):
    response = input(prompt)

    try:
        response = desired_type(response)
    except ValueError:
        stderr.write(str(desired_type) + " required\n")
        sleep(0.01)
        return get_input(prompt, desired_type)

    return response


def get_int_lim(prompt, low_lim, high_lim):
    return getNumericalInput(prompt, low_lim, high_lim, int)


def getStrLim(prompt, acceptable_strings):
    response = get_input(prompt, str)

    while response not in acceptable_strings:
        stderr.write(ERROR_MESSAGE + "\n")
        sleep(0.01)
        response = get_input(prompt, str)

    return response


# Finds files whose names start with prefix and indexes them consecutively
# (instead of just using its index in the directory)
def findDataFiles(prefix):
    fileDict = {}
    numFiles = 1

    for root, dirs, files in walk(abspath(dirname(__file__))):
        for name in files:
            if fnmatch(name, prefix + "*"):
                fileDict[numFiles] = name
                # fileDict[numFiles] = join(root, name)
                numFiles += 1

    fileDict[numFiles] = "Generate a new CSV"
    return fileDict


def parseInputFile(inputFile):
    csvReader = reader(open(inputFile))
    header = csvReader.next()
    slacNumIdx = header.index("SLAC Cryomodule Number")

    dataSessions = {}
    cryModIdxMap = {}
    cavIdxMap = {}
    cryoModules ={}

    baseIdxKeys = [("startIdx", "Start"), ("endIdx", "End"),
                   ("refHeatIdx", "Reference Heat Load"),
                   ("jtIdx", "JT Valve Position"),
                   ("timeIntIdx", "MySampler Time Interval")]

    cavIdxKeys = baseIdxKeys + [("cavNumIdx", "Cavity"),
                                ("gradIdx", "Gradient"),
                                ("rfIdx", "RF Heat Load"),
                                ("elecIdx", "Electric Heat Load")]

    calIdxKeys = baseIdxKeys + [("jlabNumIdx", "JLAB Number")]

    if "Adv" in inputFile or "Demo" in inputFile:
        cryModFileIdx = header.index("Calibration Index")

        figStartIdx = 1
        for row in csvReader:
            slacNum = int(row[slacNumIdx])
            calibIdx = int(row[cryModFileIdx])

            if slacNum not in dataSessions:
                populateIdxMap("calibrationsCM{CM_SLAC}.csv", cryModIdxMap,
                               calIdxKeys, slacNum)

                sessionCalib = addDataFileAdv("calibrationsCM{CM_SLAC}.csv",
                                         cryModIdxMap[slacNum], slacNum,
                                         calibIdx, None)

                dataSessions[slacNum] = {calibIdx: sessionCalib}
                cryoModules[slacNum] = sessionCalib.container
                sessionCalib.processData()

            else:
                if calibIdx not in dataSessions[slacNum]:
                    sessionCalib = addDataFileAdv("calibrationsCM{CM_SLAC}.csv",
                                             cryModIdxMap[slacNum], slacNum,
                                             calibIdx, cryoModules[slacNum])
                    dataSessions[slacNum] = {calibIdx: sessionCalib}
                    sessionCalib.processData()

                sessionCalib = dataSessions[slacNum][calibIdx]

            cryoModule = cryoModules[slacNum]
            print("\n---------- {CM} ----------\n".format(CM=cryoModule.name))

            for _, cavity in cryoModule.cavities.items():
                cavIdx = header.index("Cavity {NUM} Index"
                                      .format(NUM=cavity.cavNum))
                try:
                    cavIdx = int(row[cavIdx])

                    if slacNum not in cavIdxMap:
                        populateIdxMap("q0MeasurementsCM{CM_SLAC}.csv",
                                       cavIdxMap, cavIdxKeys, slacNum)

                    sessionQ0 = addDataFileAdv("q0MeasurementsCM{CM_SLAC}.csv",
                                   cavIdxMap[slacNum], slacNum, cavIdx,
                                   cavity, sessionCalib)

                    sessionQ0.processData()

                    print("\n---------- {CM} {CAV} ----------\n"
                          .format(CM=cryoModule.name, CAV=cavity.name))
                    # cavity.clear()
                    # processData(cavity)
                    sessionQ0.printReport()

                    updateCalibCurve(sessionCalib.heaterCalibAxis, sessionQ0,
                                     sessionCalib)

                except ValueError:
                    pass

            lastFigNum = len(plt.get_fignums()) + 1
            for i in range(figStartIdx, lastFigNum):
                plt.figure(i)
                plt.savefig("figures/{CM}_{FIG}.png".format(CM=cryoModule.name,
                                                            FIG=i))
            figStartIdx = lastFigNum

    plt.draw()
    plt.show()

    # else:
    #     for row in csvReader:
    #         slacNum = int(row[slacNumIdx])
    #
    #         print("---- CM{CM} ----".format(CM=slacNum))
    #
    #         if slacNum in dataSessions:
    #             # TODO make more intuitive
    #             reuseCalibration = (getStrLim("Reuse previous calibration?"
    #                                           " (y/n): ", ["y", "n", "Y", "N"])
    #                                 in ["y", "Y"])
    #
    #             if not reuseCalibration:
    #                 # TODO cryModIdxMap or cryModIdxMap[slacNum]?
    #                 addDataFile("calibrationsCM{CM_SLAC}.csv",
    #                             cryModIdxMap[slacNum], slacNum,
    #                             cryoModules=dataSessions)
    #
    #         else:
    #             populateIdxMap("calibrationsCM{CM_SLAC}.csv", cryModIdxMap,
    #                            calIdxKeys, slacNum)
    #
    #             addDataFile("calibrationsCM{CM_SLAC}.csv",
    #                         cryModIdxMap[slacNum],
    #                         slacNum, cryoModules=dataSessions)
    #
    #         for _, cavity in dataSessions[slacNum].cavities.items():
    #             cavGradIdx = header.index("Cavity {NUM} Gradient"
    #                                       .format(NUM=cavity.cavNum))
    #
    #             try:
    #                 gradDes = float(row[cavGradIdx])
    #
    #                 print("\n---- Cavity {CAV} @ {GRAD} MV/m ----"
    #                       .format(CM=slacNum, CAV=cavity.cavNum, GRAD=gradDes))
    #
    #                 if not cavity.dataFileName:
    #                     populateIdxMap("q0MeasurementsCM{CM_SLAC}.csv",
    #                                    cavIdxMap,
    #                                    cavIdxKeys, slacNum)
    #                     addDataFile("q0MeasurementsCM{CM_SLAC}.csv",
    #                                 cavIdxMap[slacNum], slacNum, cavity=cavity)
    #
    #                 else:
    #                     reuseQ0Measurement = (getStrLim("Reuse previous Q0"
    #                                                       " Measurement? (y/n): ",
    #                                                     ["y", "n", "Y", "N"])
    #                                           in ["y", "Y"])
    #                     if not reuseQ0Measurement:
    #                         addDataFile("q0MeasurementsCM{CM_SLAC}.csv",
    #                                     cavIdxMap[slacNum], slacNum,
    #                                     cavity=cavity)
    #
    #                 cavity.refGradVal = gradDes
    #
    #             except ValueError:
    #                 pass
    #
    #     for _, cryoModule in dataSessions.items():
    #
    #         print("\n---------- {CM} ----------\n".format(CM=cryoModule.name))
    #         calibCurveAxis = processData(cryoModule)
    #
    #         for _, cavity in cryoModule.cavities.items():
    #             if cavity.dataFileName:
    #                 print("\n----------  {CM} {CAV} ----------\n"
    #                       .format(CM=cryoModule.name, CAV=cavity.name))
    #                 processData(cavity)
    #                 cavity.printReport()
    #
    #                 updateCalibCurve(calibCurveAxis, cavity, cryoModule)


def updateCalibCurve(calibCurveAxis, q0Session, calibSession):
    # type: (object, Q0DataSession, DataSession) -> None

    calibCurveAxis.plot(q0Session.runHeatLoads,
                        q0Session.adjustedRunSlopes,
                        marker="o", linestyle="None",
                        label="Projected Data for " + q0Session.container.name)

    calibCurveAxis.legend(loc='best', shadow=True, numpoints=1)

    minCavHeatLoad = min(q0Session.runHeatLoads)
    minCalibHeatLoad = min(calibSession.runElecHeatLoads)

    if minCavHeatLoad < minCalibHeatLoad:
        yRange = linspace(minCavHeatLoad, minCalibHeatLoad)
        calibCurveAxis.plot(yRange, [calibSession.calibSlope * i
                                     + calibSession.calibIntercept
                                     for i in yRange])

    maxCavHeatLoad = max(q0Session.runHeatLoads)
    maxCalibHeatLoad = max(calibSession.runElecHeatLoads)

    if maxCavHeatLoad > maxCalibHeatLoad:
        yRange = linspace(maxCalibHeatLoad, maxCavHeatLoad)
        calibCurveAxis.plot(yRange, [calibSession.calibSlope * i
                                     + calibSession.calibIntercept
                                     for i in yRange])


def addDataFileAdv(fileFormatter, indices, slacNum, idx, container,
                   sessionCalib=None):
    # type: (str, dict, int, int, Container, DataSession) -> DataSession
    startIdx = indices["startIdx"]
    endIdx = indices["endIdx"]
    jtIdx = indices["jtIdx"]
    heatIdx = indices["refHeatIdx"]

    def addFileToObj(container, selectedRow):
        # type: (Container, []) -> DataSession

        startTime = datetime.strptime(selectedRow[startIdx], "%m/%d/%y %H:%M")
        endTime = datetime.strptime(selectedRow[endIdx], "%m/%d/%y %H:%M")

        timeIntervalStr = selectedRow[indices["timeIntIdx"]]
        timeInterval = (int(timeIntervalStr) if timeIntervalStr
                        else MYSAMPLER_TIME_INTERVAL)

        try:
            refHeatLoad = float(selectedRow[heatIdx])
        except ValueError:
            refHeatLoad = sessionCalib.refHeatLoad

        if isinstance(container, Cavity):
            refGradVal = float(selectedRow[indices["gradIdx"]])
            return container.addDataSession(startTime, endTime, timeInterval,
                                            float(selectedRow[jtIdx]),
                                            refHeatLoad, refGradVal,
                                            sessionCalib)

        else:
            return container.addDataSession(startTime, endTime, timeInterval,
                                            float(selectedRow[jtIdx]),
                                            refHeatLoad)


    file = fileFormatter.format(CM_SLAC=slacNum)
    row = open(file).readlines()[idx - 1]
    selectedRow = reader([row]).next()

    if not container:
        jlabIdx = indices["jlabNumIdx"]
        container = Cryomodule(cryModNumSLAC=slacNum,
                               cryModNumJLAB=int(selectedRow[jlabIdx]))

    return addFileToObj(container, selectedRow)


def populateIdxMap(fileFormatter, idxMap, idxkeys, slacNum):
    file = fileFormatter.format(CM_SLAC=slacNum)
    with open(file) as csvFile:
        csvReader = reader(csvFile)
        header = csvReader.next()
        indices = {}
        for key, column in idxkeys:
            indices[key] = header.index(column)
        idxMap[slacNum] = indices


if __name__ == "__main__":
    # if IS_DEMO:
    #     parseAdvInputFile("inputDemo.csv")
    #
    # else:
    #     parseBasicInputFile("input.csv")

    parseInputFile("inputDemo.csv")
