################################################################################
# A utility used to calculate Q0 for a set of cavities in a given cryomodules
# using the change in 2K helium liquid level (LL) per unit time
# Authors: Lisa Zacarias, Ben Ripman
################################################################################

from __future__ import division, print_function
from datetime import datetime
from json import dumps
from decimal import Decimal
from csv import reader, writer
from collections import OrderedDict
from subprocess import check_output, CalledProcessError
from re import compile, findall
from os import walk
from os.path import isfile, join, abspath, dirname
from fnmatch import fnmatch
from time import sleep

from matplotlib import pyplot as plt
from numpy import polyfit, linspace
from sys import stderr
from scipy.stats import linregress
from cryomodule import (Cryomodule, Container, Cavity, DataSession,
                        MYSAMPLER_TIME_INTERVAL, Q0DataSession)
from copy import deepcopy

# # Set True to use a known data set for debugging and/or demoing
# # Set False to prompt the user for real data
# IS_DEMO = True

# The LL readings get wonky when the upstream liquid level dips below 66
# UPSTREAM_LL_LOWER_LIMIT = 66

# Used to reject data where the JT valve wasn't at the correct position
# VALVE_POSITION_TOLERANCE = 2

# # Used to reject data where the cavity gradient wasn't at the correct value
# GRAD_TOLERANCE = 0.7

# # Used to reject data where the cavity heater wasn't at the correct value
# HEATER_TOLERANCE = 1

# # We fetch data from the JLab archiver with a program called MySampler, which
# # samples the chosen PVs at a user-specified time interval. Increase to improve
# # statistics, decrease to lower the size of the CSV files and speed up
# # MySampler data acquisition.
# MYSAMPLER_TIME_INTERVAL = 1

# # The minimum acceptable run length is fifteen minutes  (900 seconds)
# MIN_RUN_DURATION = 900

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


# def parseRawData(startTime, numPoints, signals,
#                  timeInt=MYSAMPLER_TIME_INTERVAL):
#     print("\nGetting data from the archive...\n")
#     rawData = getArchiveData(startTime, numPoints, signals, timeInt)
#
#     if not rawData:
#         return None
#
#     else:
#         rawDataSplit = rawData.splitlines()
#         rows = ["\t".join(rawDataSplit.pop(0).strip().split())]
#         rows.extend(list(map(lambda x: reformatDate(x), rawDataSplit)))
#         return reader(rows, delimiter='\t')


################################################################################
# generateCSV is a function that takes either a Cryomodule or Cavity object and
# generates a CSV data file for it if one doesn't already exist (or overwrites
# the previously existing file if the user desires)
#
# @param startTime, endTime: datetime objects
# @param object: Cryomodule or Cryomodule.Cavity
################################################################################
# def generateCSV(startTime, endTime, obj, timeInt=MYSAMPLER_TIME_INTERVAL):
#     numPoints = int((endTime - startTime).total_seconds()
#                     / timeInt)
#
#     # Define a file name for the CSV we're saving. There are calibration files
#     # and q0 measurement files. Both include a time stamp in the format
#     # year-month-day--hour-minute. They also indicate the number of data points.
#     suffixStr = "{start}{nPoints}.csv"
#     suffix = suffixStr.format(start=startTime.strftime("_%Y-%m-%d--%H-%M_"),
#                               nPoints=numPoints)
#     cryoModStr = "CM{cryMod}".format(cryMod=obj.cryModNumSLAC)
#
#     if isinstance(obj, Cryomodule.Cavity):
#         # e.g. q0meas_CM12_cav2_2019-03-03--12-00_10800.csv
#         fileNameString = "data/q0meas_{cryoMod}_cav{cavityNum}{suff}"
#         fileName = fileNameString.format(cryoMod=cryoModStr,
#                                          cavityNum=obj.cavNum,
#                                          suff=suffix)
#
#     else:
#         # e.g. calib_CM12_2019-02-25--11-25_18672.csv
#         fileNameString = "data/calib_{cryoMod}{suff}"
#         fileName = fileNameString.format(cryoMod=cryoModStr, suff=suffix)
#
#     if isfile(fileName):
#         return fileName
#
#     csvReader = parseRawData(startTime, numPoints, obj.getPVs(), timeInt)
#
#     if not csvReader:
#         return None
#
#     else:
#
#         header = csvReader.next()
#         trimmedHeader = deepcopy(header)
#
#         heaterCols = []
#
#         for heaterPV in obj.heaterDesPVs:
#             index = header.index(heaterPV)
#             heaterCols.append(index)
#
#         heaterActCols = []
#
#         for heaterActPV in obj.heaterActPVs:
#             index = header.index(heaterActPV)
#             heaterActCols.append(index)
#
#         colsToDelete = sorted(heaterCols + heaterActCols, reverse=True)
#
#         for index in colsToDelete:
#             del trimmedHeader[index]
#
#         trimmedHeader.append("Electric Heat Load Setpoint")
#         trimmedHeader.append("Electric Heat Load Readback")
#
#         with open(fileName, 'wb') as f:
#             csvWriter = writer(f, delimiter=',')
#             csvWriter.writerow(trimmedHeader)
#
#             for row in csvReader:
#                 trimmedRow = deepcopy(row)
#
#                 heatLoadSetpoint = 0
#
#                 for col in heaterCols:
#                     try:
#                         heatLoadSetpoint += float(row[col])
#                     except ValueError:
#                         heatLoadSetpoint = None
#                         break
#
#                 heatLoadAct = 0
#
#                 for col in heaterActCols:
#                     try:
#                         heatLoadAct += float(row[col])
#                     except ValueError:
#                         heatLoadAct = None
#                         break
#
#                 for index in colsToDelete:
#                     del trimmedRow[index]
#
#                 trimmedRow.append(str(heatLoadSetpoint))
#                 trimmedRow.append(str(heatLoadAct))
#                 csvWriter.writerow(trimmedRow)
#
#         return fileName


################################################################################
# getArchiveData runs a shell command to get archive data. The syntax we're
# using is:
#
#     mySampler -b "%Y-%m-%d %H:%M:%S" -s 1s -n[numPoints] [pv1] [pv2] ...[pvn]
#
# where the "-b" denotes the start time, "-s 1s" says that the desired time step
# between data points is 1 second, -n[numPoints] tells us how many points we
# want, and [pv1]...[pvn] are the PVs we want archived
#
# Ex:
#     mySampler -b "2019-03-28 14:16" -s 30s -n11 R121PMES R221PMES
#
# @param startTime: datetime object
# @param signals: list of PV strings
################################################################################
# def getArchiveData(startTime, numPoints, signals,
#                    timeInt=MYSAMPLER_TIME_INTERVAL):
#     cmd = (['mySampler', '-b'] + [startTime.strftime("%Y-%m-%d %H:%M:%S")]
#            + ['-s', str(timeInt) + 's', '-n' + str(numPoints)]
#            + signals)
#     try:
#         return check_output(cmd)
#     except (CalledProcessError, OSError) as e:
#         stderr.write("mySampler failed with error: " + str(e) + "\n")
#         return None


# def reformatDate(row):
#     try:
#         # This clusterfuck regex is pretty much just trying to find strings that
#         # match %Y-%m-%d %H:%M:%S and making them %Y-%m-%d-%H:%M:%S instead
#         # (otherwise the csv parser interprets it as two different columns)
#         regex = compile("[0-9]{4}-[0-9]{2}-[0-9]{2}"
#                         + " [0-9]{2}:[0-9]{2}:[0-9]{2}")
#         res = findall(regex, row)[0].replace(" ", "-")
#         reformattedRow = regex.sub(res, row)
#         return "\t".join(reformattedRow.strip().split())
#
#     except IndexError:
#         stderr.write("Could not reformat date for row: " + str(row) + "\n")
#         return "\t".join(row.strip().split())


# def parseAdvInputFile(inputFile):
#     csvReader = reader(open(inputFile))
#     header = csvReader.next()
#     slacNumIdx = header.index("SLAC Cryomodule Number")
#
#     cryoModules = {}
#     cryModIdxMap = {}
#     cavIdxMap = {}
#
#     baseIdxKeys = [("startIdx", "Start"), ("endIdx", "End"),
#                    ("refHeatIdx", "Reference Heat Load"),
#                    ("jtIdx", "JT Valve Position"),
#                    ("timeIntIdx", "MySampler Time Interval")]
#
#     cavIdxKeys = baseIdxKeys + [("cavNumIdx", "Cavity"),
#                                 ("gradIdx", "Gradient"),
#                                 ("rfIdx", "RF Heat Load"),
#                                 ("elecIdx", "Electric Heat Load")]
#
#     calIdxKeys = baseIdxKeys + [("jlabNumIdx", "JLAB Number")]
#
#     cryModFileIdx = header.index("Calibration Index")
#
#     calibIndices = {}
#     figStartIdx = 1
#     for row in csvReader:
#         slacNum = int(row[slacNumIdx])
#         calibIdx = int(row[cryModFileIdx])
#
#         if slacNum not in cryoModules:
#             populateIdxMap("calibrationsCM{CM_SLAC}.csv", cryModIdxMap,
#                            calIdxKeys, slacNum)
#
#             cryoModules[slacNum] = addDataFileAdv("calibrationsCM{CM_SLAC}.csv",
#                                                   cryModIdxMap[slacNum],
#                                                   slacNum, calibIdx, None)
#
#         else:
#             if slacNum not in calibIndices:
#                 addDataFileAdv("calibrationsCM{CM_SLAC}.csv",
#                                cryModIdxMap[slacNum], slacNum, calibIdx,
#                                cryoModules[slacNum])
#
#
#         cryoModule = cryoModules[slacNum]
#         print("\n---------- {CM} ----------\n".format(CM=cryoModule.name))
#
#         if slacNum not in calibIndices:
#             cryoModule.axis = processData(cryoModule)
#             calibIndices[slacNum] = calibIdx
#
#         calibCurveAxis = cryoModule.axis
#
#         for _, cavity in cryoModule.cavities.items():
#             cavIdx = header.index("Cavity {NUM} Index"
#                                   .format(NUM=cavity.cavNum))
#             try:
#                 cavIdx = int(row[cavIdx])
#
#                 if slacNum not in cavIdxMap:
#                     populateIdxMap("q0MeasurementsCM{CM_SLAC}.csv", cavIdxMap,
#                                    cavIdxKeys, slacNum)
#
#                 addDataFileAdv("q0MeasurementsCM{CM_SLAC}.csv",
#                                cavIdxMap[slacNum], slacNum, cavIdx, cavity)
#
#                 print("\n---------- {CM} {CAV} ----------\n"
#                       .format(CM=cryoModule.name, CAV=cavity.name))
#                 cavity.clear()
#                 processData(cavity)
#                 cavity.printReport()
#
#                 updateCalibCurve(calibCurveAxis, cavity, cryoModule)
#
#             except ValueError:
#                 pass
#
#         lastFigNum = len(plt.get_fignums()) + 1
#         for i in range(figStartIdx, lastFigNum):
#             plt.figure(i)
#             plt.savefig("figures/{CM}_{FIG}.png".format(CM=cryoModule.name,
#                                                         FIG=i))
#         figStartIdx = lastFigNum


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


# def parseBasicInputFile(inputFile):
#     csvReader = reader(open(inputFile))
#     header = csvReader.next()
#     slacNumIdx = header.index("SLAC Cryomodule Number")
#
#     cryoModules = {}
#     cryModIdxMap = {}
#     cavIdxMap = {}
#
#     baseIdxKeys = [("startIdx", "Start"), ("endIdx", "End"),
#                    ("refHeatIdx", "Reference Heat Load"),
#                    ("jtIdx", "JT Valve Position"),
#                    ("timeIntIdx", "MySampler Time Interval")]
#
#     cavIdxKeys = baseIdxKeys + [("cavNumIdx", "Cavity"),
#                                 ("gradIdx", "Gradient"),
#                                 ("rfIdx", "RF Heat Load"),
#                                 ("elecIdx", "Electric Heat Load")]
#
#     calIdxKeys = baseIdxKeys + [("jlabNumIdx", "JLAB Number")]
#
#     for row in csvReader:
#         slacNum = int(row[slacNumIdx])
#
#         print("---- CM{CM} ----".format(CM=slacNum))
#
#         if slacNum in cryoModules:
#             # TODO make more intuitive
#             reuseCalibration = getStrLim("Reuse previous calibration? (y/n): ",
#                                          ["y", "n", "Y", "N"]) in ["y", "Y"]
#
#             if not reuseCalibration:
#                 # TODO cryModIdxMap or cryModIdxMap[slacNum]?
#                 addDataFile("calibrationsCM{CM_SLAC}.csv",
#                             cryModIdxMap[slacNum], slacNum,
#                             cryoModules=cryoModules)
#
#         else:
#             populateIdxMap("calibrationsCM{CM_SLAC}.csv", cryModIdxMap,
#                            calIdxKeys, slacNum)
#
#             addDataFile("calibrationsCM{CM_SLAC}.csv", cryModIdxMap[slacNum],
#                         slacNum, cryoModules=cryoModules)
#
#         for _, cavity in cryoModules[slacNum].cavities.items():
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
#                     populateIdxMap("q0MeasurementsCM{CM_SLAC}.csv", cavIdxMap,
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
#                                     cavIdxMap[slacNum], slacNum, cavity=cavity)
#
#                 cavity.refGradVal = gradDes
#
#             except ValueError:
#                 pass
#
#     for _, cryoModule in cryoModules.items():
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
#
#     plt.draw()
#     plt.show()
#
#     # lastFigNum = len(plt.get_fignums())
#     # for i in range(startFigNum, lastFigNum):
#     #     plt.figure(i)
#     #     plt.savefig("figures/{CM}_{FIG}.png".format(CM=cryoModuleObj.name,
#     #                                                 FIG=i))
#     #
#     # return lastFigNum


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

        # obj.dataFileName = generateCSV(startTime, endTime, obj,
        #                                timeInterval)

    file = fileFormatter.format(CM_SLAC=slacNum)
    row = open(file).readlines()[idx - 1]
    selectedRow = reader([row]).next()

    if not container:
        jlabIdx = indices["jlabNumIdx"]
        container = Cryomodule(cryModNumSLAC=slacNum,
                               cryModNumJLAB=int(selectedRow[jlabIdx]))
                               # refHeatLoad=float(selectedRow[heatIdx]),
                               # refValvePos=float(selectedRow[jtIdx]),
                               # calFileName=None)

    # container.refValvePos = float(selectedRow[jtIdx])

    # if isinstance(container, Cavity):
    #     try:
    #         container.refHeatLoad = float(selectedRow[heatIdx])
    #     except ValueError:
    #         container.refHeatLoad = container.parent.refHeatLoad

        # container.refGradVal = float(selectedRow[indices["gradIdx"]])

    return addFileToObj(container, selectedRow)


def addDataFile(fileFormatter, indices, slacNum, cavity=None, cryoModules=None):

    def addFileToObj(obj, selectedRow):

        startTime = datetime.strptime(selectedRow[startIdx], "%m/%d/%y %H:%M")
        endTime = datetime.strptime(selectedRow[endIdx], "%m/%d/%y %H:%M")

        timeIntervalStr = selectedRow[indices["timeIntIdx"]]
        timeInterval = (int(timeIntervalStr) if timeIntervalStr
                        else MYSAMPLER_TIME_INTERVAL)

        obj.addDataSession(startTime, endTime, timeInterval)

        # obj.dataFileName = generateCSV(startTime, endTime, obj,
        #                                timeInterval)

    def printOptions():
        print(("\n" + dumps(options, indent=4) + "\n").replace('"', '')
              .replace(',', ''))

    def getSelection(suffix, duration):
        idx = max(options) + 1 if options else 1
        options[idx] = ("Launch new {TYPE} ({DUR} hours)".format(TYPE=suffix,
                                                                 DUR=duration))
        printOptions()
        selection = getNumInputFromLst(("Please select a {TYPE} option: "
                                        .format(TYPE=suffix)), options.keys(),
                                       int)
        return selection

    def addOption(lineNum, row):
        startTime = datetime.strptime(row[indices["startIdx"]],
                                      "%m/%d/%y %H:%M")
        endTime = datetime.strptime(row[indices["endIdx"]], "%m/%d/%y %H:%M")

        rate = row[indices["timeIntIdx"]]
        options[lineNum] = ("{START} to {END} ({RATE}s sample interval)"
                            .format(START=startTime, END=endTime,
                                    RATE=rate))

    def showMore():
        if options and (len(options) % 5 == 0):
            print("---- PARTIAL RESULTS ----")
            printOptions()
            return (getStrLim("Search for more options? (y/n): ",
                              ["y", "n", "Y", "N"]) in ["y", "Y"])
        return True

    file = fileFormatter.format(CM_SLAC=slacNum)
    rows = open(file).readlines()
    rows.reverse()
    rows.pop()

    fileReader = reader(rows)
    options = OrderedDict()

    startIdx = indices["startIdx"]
    endIdx = indices["endIdx"]
    jtIdx = indices["jtIdx"]

    if cavity:
        for row in fileReader:

            if not showMore():
                break

            grad = float(row[indices["gradIdx"]])
            cavNum = int(row[indices["cavNumIdx"]])

            if (grad != cavity.refGradVal) or (cavNum != cavity.cavNum):
                continue

            addOption(fileReader.line_num, row)

        selection = getSelection("Q0 Measurement", 2)

        if selection != max(options):
            cavRow = reader([rows[selection - 1]]).next()
            addFileToObj(cavity, cavRow)
            cavity.refValvePos = float(cavRow[jtIdx])

    else:
        for row in fileReader:

            if not showMore():
                break

            addOption(fileReader.line_num, row)

        selection = getSelection("calibration", 5)

        if selection != max(options):
            calibRow = reader([rows[selection - 1]]).next()
            jlabIdx = indices["jlabNumIdx"]
            heatIdx = indices["refHeatIdx"]

            try:
                cryoModuleObj = cryoModules[slacNum]
                cryoModuleObj.refValvePos = float(calibRow[jtIdx])
                cryoModuleObj.refHeatLoad = float(calibRow[heatIdx])
                addFileToObj(cryoModuleObj, calibRow)

            except KeyError:
                cryoModuleObj = Cryomodule(cryModNumSLAC=slacNum,
                                           cryModNumJLAB=int(calibRow[jlabIdx]),
                                           calFileName=None,
                                           refValvePos=float(calibRow[jtIdx]),
                                           refHeatLoad=float(calibRow[heatIdx]))

                addFileToObj(cryoModuleObj, calibRow)
                cryoModules[slacNum] = cryoModuleObj


def populateIdxMap(fileFormatter, idxMap, idxkeys, slacNum):
    file = fileFormatter.format(CM_SLAC=slacNum)
    with open(file) as csvFile:
        csvReader = reader(csvFile)
        header = csvReader.next()
        indices = {}
        for key, column in idxkeys:
            indices[key] = header.index(column)
        idxMap[slacNum] = indices


# parseDataFromCSV parses CSV data to populate the given object's data buffers
# @param obj: either a Cryomodule or Cavity object
# def parseDataFromCSV(obj):
#     columnDict = {}
#
#     with open(obj.dataFileName) as csvFile:
#
#         csvReader = reader(csvFile)
#         header = csvReader.next()
#
#         # Figures out the CSV column that has that PV's data and maps it
#         for pv, dataBuff in obj.pvBuffMap.items():
#             linkBuffToColumn(pv, dataBuff, columnDict, header)
#
#         linkBuffToColumn("Electric Heat Load Setpoint", obj.elecHeatDesBuff,
#                          columnDict, header)
#
#         linkBuffToColumn("Electric Heat Load Readback", obj.elecHeatActBuff,
#                          columnDict, header)
#
#         try:
#             # Data fetched from the JLab archiver has the timestamp column
#             # labeled "Date"
#             timeIdx = header.index("Date")
#             datetimeFormatStr = "%Y-%m-%d-%H:%M:%S"
#
#         except ValueError:
#             # Data exported from MyaPlot has the timestamp column labeled "time"
#             timeIdx = header.index("time")
#             datetimeFormatStr = "%Y-%m-%d %H:%M:%S"
#
#         timeZero = datetime.utcfromtimestamp(0)
#
#         for row in csvReader:
#             dt = datetime.strptime(row[timeIdx], datetimeFormatStr)
#
#             # del obj.timeBuff[:]
#             obj.timeBuff.append(dt)
#
#             # We use the Unix time to make the math easier during data
#             # processing
#             # del obj.unixTimeBuff[:]
#             obj.unixTimeBuff.append((dt - timeZero).total_seconds())
#
#             # Actually parsing the CSV data into the buffers
#             for col, idxBuffDict in columnDict.items():
#                 # del idxBuffDict["buffer"][:]
#                 try:
#                     idxBuffDict["buffer"].append(float(row[idxBuffDict["idx"]]))
#                 except ValueError:
#                     stderr.write("Could not fill buffer: " + str(col) + "\n")
#                     idxBuffDict["buffer"].append(None)


# def linkBuffToColumn(column, dataBuff, columnDict, header):
#     try:
#         columnDict[column] = {"idx": header.index(column), "buffer": dataBuff}
#     except ValueError:
#         stderr.write("Column " + column + " not found in CSV\n")


# # @param obj: either a Cryomodule or Cavity object
# def processData(dataSession):
#     # type: (DataSession) -> object
#     # parseDataFromCSV(obj)
#     obj.parseData(idx)
#     populateRuns(obj)
#
#     if not obj.runs:
#         print("{name} has no runs to process and plot.".format(name=obj.name))
#         return
#
#     adjustForSettle(obj)
#     processRuns(obj)
#
#     return plotAndFitData(obj)


################################################################################
# populateRuns takes the data in an object's buffers and slices it into data
# "runs" based on cavity heater settings.
#
# @param obj: Either a Cryomodule or Cavity object
################################################################################
# def populateRuns(obj):
#     # noinspection PyShadowingNames
#     def isEndOfCalibRun(idx, elecHeatLoad):
#         # Find inflection points for the desired heater setting
#         prevElecHeatLoad = (obj.elecHeatDesBuff[idx - 1]
#                             if idx > 0 else elecHeatLoad)
#
#         heaterChanged = (elecHeatLoad != prevElecHeatLoad)
#         liqLevelTooLow = (obj.usLevelBuff[idx]
#                           < UPSTREAM_LL_LOWER_LIMIT)
#         valveOutsideTol = (abs(obj.valvePosBuff[idx] - obj.refValvePos)
#                            > VALVE_POSITION_TOLERANCE)
#         isLastElement = (idx == len(obj.elecHeatDesBuff) - 1)
#
#         heatersOutsideTol = (abs(elecHeatLoad - obj.elecHeatActBuff[idx])
#                              >= HEATER_TOLERANCE)
#
#         # A "break" condition defining the end of a run if the desired heater
#         # value changed, or if the upstream liquid level dipped below the
#         # minimum, or if the valve position moved outside the tolerance, or if
#         # we reached the end (which is a kinda jank way of "flushing" the last
#         # run)
#         return (heaterChanged or liqLevelTooLow or valveOutsideTol
#                 or isLastElement or heatersOutsideTol)
#
#     # noinspection PyShadowingNames
#     def checkAndFlushRun(isEndOfRun, idx, runStartIdx):
#         if isEndOfRun:
#             runDuration = obj.unixTimeBuff[idx] - obj.unixTimeBuff[runStartIdx]
#
#             if runDuration >= MIN_RUN_DURATION:
#                 obj.addRun(runStartIdx, idx - 1)
#
#             return idx
#
#         return runStartIdx
#
#     isCryomodule = isinstance(obj, Cryomodule)
#
#     runStartIdx = 0
#
#     if isCryomodule:
#         for idx, elecHeatLoad in enumerate(obj.elecHeatDesBuff):
#             runStartIdx = checkAndFlushRun(isEndOfCalibRun(idx, elecHeatLoad),
#                                            idx, runStartIdx)
#
#     else:
#         for idx, elecHeatLoad in enumerate(obj.elecHeatDesBuff):
#
#             try:
#                 gradChanged = (abs(obj.gradBuff[idx] - obj.gradBuff[idx - 1])
#                                > GRAD_TOLERANCE) if idx != 0 else False
#             except TypeError:
#                 gradChanged = False
#
#             isEndOfQ0Run = isEndOfCalibRun(idx, elecHeatLoad) or gradChanged
#
#             runStartIdx = checkAndFlushRun(isEndOfQ0Run, idx, runStartIdx)


################################################################################
# adjustForSettle cuts off data that's corrupted because the heat load on the
# 2 K helium bath is changing. (When the cavity heater setting or the RF
# gradient change, it takes time for that change to become visible to the
# helium because there are intermediate structures with heat capacity.)
################################################################################
def adjustForSettle(obj):
    # Approximates the expected heat load on a cavity from its RF gradient. A
    # cavity with the design Q of 2.7E10 should produce about 9.6 W of heat with
    # a gradient of 16 MV/m. The heat scales quadratically with the gradient. We
    # don't know the correct Q yet when we call this function so we assume the
    # design values.
    def approxHeatFromGrad(grad):
        # Gradients < 0 are non-physical so assume no heat load in that case.
        # The gradient values we're working with are readbacks from cavity
        # gradient PVs so it's possible that they could go negative.
        return ((grad / 16) ** 2) * 9.6 if grad > 0 else 0

    for i, run in enumerate(obj.runs):

        startIdx = run.startIdx
        elecHeatBuff = obj.elecHeatDesBuff

        if i == 0:
            totalHeatDelta = (elecHeatBuff[startIdx] - obj.refHeatLoad)
            totalHeatDelta += (approxHeatFromGrad(obj.gradBuff[startIdx])
                               if isinstance(obj, Cryomodule.Cavity) else 0)

        else:

            prevStartIdx = obj.runs[i - 1].startIdx

            elecHeatDelta = elecHeatBuff[startIdx] - elecHeatBuff[prevStartIdx]

            totalHeatDelta = abs(elecHeatDelta)

            if isinstance(obj, Cryomodule.Cavity):
                gradBuff = obj.gradBuff

                # Checking that gradBuff isn't empty because we have some old
                # data from before the gradient was being archived.
                if gradBuff:
                    currGrad = gradBuff[startIdx]
                    currGradHeatLoad = approxHeatFromGrad(currGrad)

                    prevGrad = gradBuff[prevStartIdx]
                    prevGradHeatLoad = approxHeatFromGrad(prevGrad)

                    gradHeatDelta = currGradHeatLoad - prevGradHeatLoad
                    totalHeatDelta = abs(elecHeatDelta + gradHeatDelta)

        # Calculate the number of data points to be chopped off the beginning of
        # the data run based on the expected change in the cryomodule heat load.
        # The scale factor is derived from the assumption that a 1 W change in
        # the heat load leads to about 25 useless points (and that this scales
        # linearly with the change in heat load, which isn't really true).
        # TODO scale this with sample rate
        cutoff = int(totalHeatDelta * 25)

        idx = obj.runs[i].startIdx
        startTime = obj.unixTimeBuff[idx]
        duration = 0

        while duration < cutoff:
            idx += 1
            duration = obj.unixTimeBuff[idx] - startTime

        obj.runs[i].startIdx = idx

        # if IS_DEMO:
        #     print("cutoff: " + str(cutoff))


# # noinspection PyTupleAssignmentBalance
# def processRuns(obj):
#     isCalibration = isinstance(obj, Cryomodule)
#
#     for run in obj.runs:
#
#         run.slope, run.intercept, r_val, p_val, std_err = linregress(run.times,
#                                                                      run.data)
#
#         # Print R^2 to diagnose whether or not we had a long enough data run
#         print("R^2: " + str(r_val ** 2))
#
#     if isCalibration:
#
#         # TODO we should consider whether all runs should be weighted equally
#         # TODO we should probably adjust the calib slope to intersect the origin
#
#         # We're dealing with a cryomodule here so we need to calculate the
#         # fit for the heater calibration curve.
#         obj.calibSlope, yIntercept = polyfit(obj.runElecHeatLoads,
#                                              obj.runSlopes, 1)
#
#         xIntercept = -yIntercept / obj.calibSlope
#
#         obj.delta = -xIntercept
#         print("Delta = " + str(obj.delta))
#
#         obj.calibIntercept = 0
#
#
#     if IS_DEMO:
#         for i, run in enumerate(obj.runs):
#             startTime = obj.unixTimeBuff[run.startIdx]
#             endTime = obj.unixTimeBuff[run.endIdx]
#             runStr = "Duration of run {runNum}: {duration}"
#             print(runStr.format(runNum=(i + 1),
#                                 duration=((endTime - startTime) / 60.0)))


# ################################################################################
# # plotAndFitData takes three related arrays, plots them, and fits some trend
# # lines
# #
# # heatLoads, runs, and timeRuns are arrays that all have the same size such that
# # heatLoads[i] corresponds to runs[i] corresponds to timeRuns[i]
# #
# # @param heatLoads: an array containing the heat load per data run
# # @param runs: an array of arrays, where each runs[i] is a run of LL data for a
# #              given heat load
# # @param timeRuns: an array of arrays, where each timeRuns[i] is a list of
# #                  timestamps that correspond to that run's LL data
# # @param obj: Either a Cryomodule or Cavity object
# ################################################################################
# def plotAndFitData(obj):
#     # TODO improve plots with human-readable time
#
#     plt.rcParams.update({'legend.fontsize': 'small'})
#
#     isCalibration = isinstance(obj, Cryomodule)
#
#     if isCalibration:
#         suffix = " ({name} Heater Calibration)".format(name=obj.name)
#     else:
#         suffix = " ({name})".format(name=obj.name)
#
#     liquidVsTimeAxis = genAxis("Liquid Level vs. Time" + suffix,
#                                "Unix Time (s)", "Downstream Liquid Level (%)")
#
#     for run in obj.runs:
#
#         # First we plot the actual run data
#         liquidVsTimeAxis.plot(run.times, run.data, label=run.label)
#
#         # Then we plot the linear fit to the run data
#         liquidVsTimeAxis.plot(run.times, [run.slope * x + run.intercept
#                                          for x in run.times])
#
#     if isCalibration:
#         liquidVsTimeAxis.legend(loc='best')
#         heaterCalibAxis = genAxis("Liquid Level Rate of Change vs. Heat Load",
#                                   "Heat Load (W)", "dLL/dt (%/s)")
#
#         heaterCalibAxis.plot(obj.runElecHeatLoads, obj.runSlopes, marker="o",
#                              linestyle="None", label="Heater Calibration Data")
#
#         slopeStr = '{:.2e}'.format(Decimal(obj.calibSlope))
#         labelStr = "Calibration Fit:  {slope} %/(s*W)".format(slope=slopeStr)
#
#         heaterCalibAxis.plot(obj.runElecHeatLoads,
#                              [obj.calibSlope * x + obj.calibIntercept
#                               for x in obj.runElecHeatLoads], label=labelStr)
#
#         heaterCalibAxis.legend(loc='best')
#
#         return heaterCalibAxis
#
#     else:
#         liquidVsTimeAxis.legend(loc='best')


# def genAxis(title, xlabel, ylabel):
#     fig = plt.figure()
#     ax = fig.add_subplot(111)
#     ax.set_title(title)
#     ax.set_xlabel(xlabel)
#     ax.set_ylabel(ylabel)
#     return ax


if __name__ == "__main__":
    # if IS_DEMO:
    #     parseAdvInputFile("inputDemo.csv")
    #
    # else:
    #     parseBasicInputFile("input.csv")

    parseInputFile("inputDemo.csv")
