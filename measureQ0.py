################################################################################
# A utility used to calculate Q0 for a set of cavities in a given cryomodules
# using the change in 2K helium liquid level (LL) per unit time
# Authors: Lisa Zacarias, Ben Ripman
################################################################################

from __future__ import division
from __future__ import print_function
from datetime import datetime, timedelta
from csv import reader, writer
from subprocess import check_output, CalledProcessError
from re import compile, findall
from os import walk
from os.path import isfile, join, abspath, dirname
from fnmatch import fnmatch
from matplotlib import pyplot as plt
from numpy import polyfit, linspace
from sys import stderr
from scipy.stats import linregress
from json import dumps
from time import sleep
from cryomodule import Cryomodule

# The LL readings get wonky when the upstream liquid level dips below 66
UPSTREAM_LL_LOWER_LIMIT = 66

# Used to reject data where the JT valve wasn't at the correct position
VALVE_POSITION_TOLERANCE = 2

# Used to reject data where the cavity gradient wasn't at the correct value
GRADIENT_TOLERANCE = 0.7

# We fetch data from the JLab archiver with a program called mySampler, which
# samples the chosen PVs at a user-specified time interval
SAMPLING_INTERVAL = 1

# The minimum run length was empirically found to be ~750 (long enough to
# ensure the runs we detect are usable data and not just noise)
RUN_LENGTH_LOWER_LIMIT = 750 / SAMPLING_INTERVAL

# Set True to use a known data set for debugging and/or demoing
# Set False to prompt the user for real data
IS_DEMO = True

# Trying to make this compatible with both 2.7 and 3 (input in 3 is the same as
# raw_input in 2.7, but input in 2.7 calls evaluate)
if hasattr(__builtins__, 'raw_input'):
    input = raw_input

# Used in custom input functions just below
ERROR_MESSAGE = "Please provide valid input"


def get_float_lim(prompt, low_lim, high_lim):
    return getNumericalInput(prompt, low_lim, high_lim, float)


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


def get_str_lim(prompt, acceptable_strings):
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
                # fileDict[idx] = join(root, name)
                numFiles += 1

    fileDict[numFiles] = "Generate a new CSV"
    return fileDict


def buildCryModObj(cryomoduleSLAC, cryomoduleLERF, valveLockedPos,
                   refHeaterVal):
    print("\n*** Now we'll start building a calibration file " +
          "- please be patient ***\n")

    startTimeCalib = buildDatetimeFromInput("Start time for calibration run:")

    upperLimit = (datetime.now() - startTimeCalib).total_seconds() / 3600
    duration = get_float_lim("Duration of calibration run in hours: ",
                             RUN_LENGTH_LOWER_LIMIT / 3600, upperLimit)
    endTimeCalib = startTimeCalib + timedelta(hours=duration)

    cryoModuleObj = Cryomodule(cryModNumSLAC=cryomoduleSLAC,
                               cryModNumJLAB=cryomoduleLERF,
                               calFileName=None,
                               refValvePos=valveLockedPos,
                               refHeaterVal=refHeaterVal)

    fileName = generateCSV(startTimeCalib, endTimeCalib, cryoModuleObj)

    if not fileName:
        return None

    else:
        cryoModuleObj.dataFileName = fileName
        return cryoModuleObj


def buildDatetimeFromInput(prompt):
    print(prompt)

    now = datetime.now()
    # The signature is: get_int_limited(prompt, low_lim, high_lim)
    year = get_int_lim("Year: ".rjust(16), 2019, now.year)

    month = get_int_lim("Month: ".rjust(16), 1,
                        now.month if year == now.year else 12)

    day = get_int_lim("Day: ".rjust(16), 1,
                      now.day if (year == now.year
                                  and month == now.month) else 31)

    hour = get_int_lim("Hour: ".rjust(16), 0, 23)
    minute = get_int_lim("Minute: ".rjust(16), 0, 59)

    return datetime(year, month, day, hour, minute)


################################################################################
# generateCSV is a function that takes either a Cryomodule or Cavity object and
# generates a CSV data file for it if one doesn't already exist (or overwrites
# the previously existing file if the user desires)
#
# @param startTime, endTime: datetime objects
# @param object: Cryomodule or Cryomodule.Cavity
################################################################################
def generateCSV(startTime, endTime, obj):
    numPoints = int((endTime - startTime).total_seconds() / SAMPLING_INTERVAL)

    # Define a file name for the CSV we're saving. There are calibration files
    # and q0 measurement files. Both include a time stamp in the format
    # year-month-day--hour-minute. They also indicate the number of data points.
    suffixStr = "{start}{nPoints}.csv"
    suffix = suffixStr.format(start=startTime.strftime("_%Y-%m-%d--%H-%M_"),
                              nPoints=numPoints)
    cryoModStr = "CM{cryMod}".format(cryMod=obj.cryModNumSLAC)

    if isinstance(obj, Cryomodule.Cavity):
        # e.g. q0meas_CM12_cav2_2019-03-03--12-00_10800.csv
        fileNameString = "q0meas_{cryoMod}_cav{cavityNum}{suff}"
        fileName = fileNameString.format(cryoMod=cryoModStr,
                                         cavityNum=obj.cavityNumber,
                                         suff=suffix)

    else:
        # e.g. calib_CM12_2019-02-25--11-25_18672.csv
        fileNameString = "calib_{cryoMod}{suff}"
        fileName = fileNameString.format(cryoMod=cryoModStr, suff=suffix)

    if isfile(fileName):
        overwrite = get_str_lim("Overwrite previous CSV file '" + fileName
                                + "' (y/n)? ",
                                acceptable_strings=['y', 'n']) == 'y'
        if not overwrite:
            return fileName

    print("\nGetting data from the archive...\n")
    rawData = getArchiveData(startTime, numPoints, obj.getPVs())

    if not rawData:
        return None

    else:

        rawDataSplit = rawData.splitlines()
        rows = ["\t".join(rawDataSplit.pop(0).strip().split())]
        rows.extend(list(map(lambda x: reformatDate(x), rawDataSplit)))
        csvReader = reader(rows, delimiter='\t')

        with open(fileName, 'wb') as f:
            csvWriter = writer(f, delimiter=',')
            for row in csvReader:
                csvWriter.writerow(row)

        return fileName


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
#     mySampler -b "201-03-28 14:16" -s 30s -n11 R121PMES R221PMES
#
# @param startTime: datetime object
# @param signals: list of PV strings
################################################################################
def getArchiveData(startTime, numPoints, signals):
    cmd = (['mySampler', '-b'] + [startTime.strftime("%Y-%m-%d %H:%M:%S")]
           + ['-s', str(SAMPLING_INTERVAL) + 's', '-n'] + [str(numPoints)]
           + signals)
    try:
        return check_output(cmd)
    except (CalledProcessError, OSError) as e:
        stderr.write("mySampler failed with error: " + str(e) + "\n")
        return None


def reformatDate(row):
    try:
        # This clusterfuck regex is pretty much just trying to find strings that
        # match %Y-%m-%d %H:%M:%S and making them %Y-%m-%d-%H:%M:%S instead
        # (otherwise the csv parser interprets it as two different columns)
        regex = compile("[0-9]{4}-[0-9]{2}-[0-9]{2}"
                        + " [0-9]{2}:[0-9]{2}:[0-9]{2}")
        res = findall(regex, row)[0].replace(" ", "-")
        reformattedRow = regex.sub(res, row)
        return "\t".join(reformattedRow.strip().split())
    except IndexError:
        stderr.write("Could not reformat date for row: " + str(row) + "\n")
        return "\t".join(row.strip().split())


# parseDataFromCSV parses CSV data to populate the given object's data buffers
# @param obj: either a Cryomodule or Cavity object
def parseDataFromCSV(obj):
    columnDict = {}

    with open(obj.dataFileName) as csvFile:

        csvReader = reader(csvFile)
        header = csvReader.next()

        # Figures out the CSV column that has that PV's data and maps it
        for pv, dataBuffer in obj.pvBufferMap.items():
            linkBufferToPV(pv, dataBuffer, columnDict, header)

        if isinstance(obj, Cryomodule):
            # We do the calibration using a cavity heater (usually cavity 1)
            # instead of RF, so we use the heater PV to parse the calibration
            # data using the different heater settings
            heaterPV = obj.cavities[obj.calCavNum].heaterPV
            linkBufferToPV(heaterPV, obj.heaterBuffer, columnDict, header)

        try:
            # Data fetched from the JLab archiver has the timestamp column
            # labeled "Date"
            timeIdx = header.index("Date")
            datetimeFormatStr = "%Y-%m-%d-%H:%M:%S"

        except ValueError:
            # Data exported from MyaPlot has the timestamp column labeled "time"
            timeIdx = header.index("time")
            datetimeFormatStr = "%Y-%m-%d %H:%M:%S"

        timeZero = datetime.utcfromtimestamp(0)

        for row in csvReader:
            dt = datetime.strptime(row[timeIdx], datetimeFormatStr)

            # TODO use this to make the plots more human-friendly
            obj.timeBuffer.append(dt)

            # We use the Unix time to make the math easier during data
            # processing
            obj.unixTimeBuffer.append((dt - timeZero).total_seconds())

            # Actually parsing the CSV data into the buffers
            for col, idxBuffDict in columnDict.items():
                try:
                    idxBuffDict["buffer"].append(float(row[idxBuffDict["idx"]]))
                except ValueError:
                    stderr.write("Could not parse row: " + str(row) + "\n")


def linkBufferToPV(pv, dataBuffer, columnDict, header):
    try:
        columnDict[pv] = {"idx": header.index(pv), "buffer": dataBuffer}
    except ValueError:
        stderr.write("Column " + pv + " not found in CSV\n")


# @param obj: either a Cryomodule or Cavity object
def processData(obj):

    parseDataFromCSV(obj)
    populateRuns(obj)
    adjustForHeaterSettle(obj)

    if IS_DEMO:
        for idx, (startIdx, endIdx) in enumerate(obj.runIndices):
            startTime = obj.unixTimeBuffer[startIdx]
            endTime = obj.unixTimeBuffer[endIdx]
            runStr = "Duration of run {runNum}: {duration}"
            print(runStr.format(runNum=idx + 1,
                                duration=(endTime - startTime) / 60.0))
            heatStr = "Electric heat Load: {heat}"
            print(heatStr.format(heat=obj.runElecHeatLoads[idx]))

    return plotAndFitData(obj)


################################################################################
# populateRuns takes the data in an object's buffers and slices it into data
# "runs" based on cavity heater settings.
#
# @param obj: Either a Cryomodule or Cavity object
################################################################################
def populateRuns(obj):

    # noinspection PyShadowingNames
    def getRunEndCondition(idx, heaterVal):
        # Find inflection points for the desired heater setting
        prevHeaterVal = obj.heaterBuffer[idx - 1] if idx > 0 else heaterVal

        heaterChanged = (heaterVal != prevHeaterVal)
        liqLevelTooLow = (obj.upstreamLevelBuffer[idx]
                          < UPSTREAM_LL_LOWER_LIMIT)
        valveOutsideTol = (abs(obj.valvePosBuffer[idx] - obj.refValvePos)
                           > VALVE_POSITION_TOLERANCE)
        isLastElement = (idx == len(obj.heaterBuffer) - 1)

        # A "break" condition defining the end of a run if the desired heater
        # value changed, or if the upstream liquid level dipped below the
        # minimum, or if the valve position moved outside the tolerance, or if
        # we reached the end (which is a kinda jank way of "flushing" the last
        # run)
        return (heaterChanged or liqLevelTooLow or valveOutsideTol
                or isLastElement)

    # noinspection PyShadowingNames
    def checkAndFlushRun(endRunCondition, idx, runStartIdx):
        if endRunCondition:
            # Keeping only those runs with at least <cutoff> points
            if idx - runStartIdx > RUN_LENGTH_LOWER_LIMIT:

                obj.runIndices.append([runStartIdx, idx - 1])
                obj.runElecHeatLoads.append(obj.heaterBuffer[idx - 1]
                                            - obj.refHeaterVal)
            return idx

        return runStartIdx

    isCryomodule = isinstance(obj, Cryomodule)

    runStartIdx = 0

    if isCryomodule:
        for idx, heaterVal in enumerate(obj.heaterBuffer):
            endOfCryModRun = getRunEndCondition(idx, heaterVal)

            runStartIdx = checkAndFlushRun(endOfCryModRun, idx, runStartIdx)

    else:
        for idx, heaterVal in enumerate(obj.heaterBuffer):
            endOfCryModRun = getRunEndCondition(idx, heaterVal)

            try:
                gradientChanged = (abs(obj.gradientBuffer[idx]
                                       - obj.refGradientVal)
                                   > GRADIENT_TOLERANCE)
            except IndexError:
                gradientChanged = False

            runStartIdx = checkAndFlushRun(endOfCryModRun or gradientChanged,
                                           idx, runStartIdx)


# Sometimes the heat load takes a little while to settle, especially after large
# jumps in the heater settings, which renders the points taken during that time
# useless
def adjustForHeaterSettle(obj):
    heaterBuffer = obj.heaterBuffer
    runIndices = obj.runIndices

    for idx, (runStartIdx, _) in enumerate(runIndices):
        prevRunStartIdx = runIndices[idx-1][0] if idx > 0 else runStartIdx

        heaterDelta = (abs(heaterBuffer[runStartIdx]
                           - heaterBuffer[prevRunStartIdx]))
        # Scaling factor 27 is derived from the assumption that an 11W jump
        # leads to about 300 useless points (and that this scales linearly)
        cutoff = int(heaterDelta * 27)
        runIndices[idx][0] = runStartIdx + cutoff

        if IS_DEMO:
            print("cutoff: " + str(cutoff))


################################################################################
# plotAndFitData takes three related arrays, plots them, and fits some trend
# lines
#
# heatLoads, runs, and timeRuns are arrays that all have the same size such that
# heatLoads[i] corresponds to runs[i] corresponds to timeRuns[i]
#
# @param heatLoads: an array containing the heat load per data run
# @param runs: an array of arrays, where each runs[i] is a run of LL data for a
#              given heat load
# @param timeRuns: an array of arrays, where each timeRuns[i] is a list of
#                  timestamps that correspond to that run's LL data
# @param obj: Either a Cryomodule or Cavity object
#
# noinspection PyTupleAssignmentBalance
################################################################################
def plotAndFitData(obj):
    isCalibration = isinstance(obj, Cryomodule)

    if isCalibration:

        suffixString = " (Cryomodule {cryMod} Calibration)"
        suffix = suffixString.format(cryMod=obj.cryModNumSLAC)
    else:
        suffix = " (Cavity {cavNum})".format(cavNum=obj.cavityNumber)

    ax1 = genAxis("Liquid Level as a Function of Time" + suffix,
                  "Unix Time (s)", "Downstream Liquid Level (%)")

    for idx, (runStartIdx, runEndIdx) in enumerate(obj.runIndices):

        runData = obj.downstreamLevelBuffer[runStartIdx:runEndIdx]
        runTimes = obj.unixTimeBuffer[runStartIdx:runEndIdx]

        m, b, r_val, p_val, std_err = linregress(runTimes, runData)
        obj.runSlopes.append(m)

        # Print R^2 to diagnose whether or not we had a long enough data run
        if IS_DEMO:
            print("R^2: " + str(r_val ** 2))

        labelString = "{slope} %/s @ {heatLoad} W Electric Load"
        plotLabel = labelString.format(slope=round(m, 6),
                                       heatLoad=obj.runElecHeatLoads[idx])
        ax1.plot(runTimes, runData, label=plotLabel)

        ax1.plot(runTimes, [m * x + b for x in runTimes])

    if isCalibration:
        ax1.legend(loc='lower right')
        ax2 = genAxis("Rate of Change of Liquid Level as a Function of Heat"
                      " Load", "Heat Load (W)", "dLL/dt (%/s)")

        ax2.plot(obj.runElecHeatLoads, obj.runSlopes, marker="o",
                 linestyle="None", label="Calibration Data")

        m, b = polyfit(obj.runElecHeatLoads, obj.runSlopes, 1)
        obj.calibSlope = m
        obj.calibIntercept = b

        ax2.plot(obj.runElecHeatLoads,
                 [m * x + b for x in obj.runElecHeatLoads],
                 label="{slope} %/(s*W)".format(slope=round(m, 6)))

        ax2.legend(loc='upper right')

        return ax2

    else:
        ax1.legend(loc='upper right')


def genAxis(title, xlabel, ylabel):
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return ax


def addFileToCavity(cavity):
    print("\n*** Now we'll start building a Q0 measurement file " +
          "- please be patient ***\n")

    startTimeQ0Meas = buildDatetimeFromInput("Start time for the data run:")

    upperLimit = (datetime.now() - startTimeQ0Meas).total_seconds() / 3600

    duration = get_float_lim("Duration of data run in hours: ",
                             RUN_LENGTH_LOWER_LIMIT / 3600, upperLimit)

    endTimeCalib = startTimeQ0Meas + timedelta(hours=duration)

    cavity.dataFileName = generateCSV(startTimeQ0Meas, endTimeCalib, cavity)


# Given a gradient and a heat load, we can "calculate" Q0 by scaling a known
# Q0 value taken at a reference gradient and heat load
def calcQ0(gradient, inputHeatLoad, refGradient=16.0, refHeatLoad=9.6,
           refQ0=2.7E10):
    # TODO use Mike's more accurate Q0 spreadsheet calculation
    # TODO correct Q0 value for 2K line temperature variation
    return (refQ0 * (refHeatLoad / inputHeatLoad)
            * ((gradient / refGradient) ** 2))


def getQ0Measurements():
    if IS_DEMO:
        refHeaterVal = 1.91
        valveLockedPos = 17.5
        cryomoduleSLAC = 12
        cryomoduleLERF = 2
        fileName = "calib_CM12_2019-02-25--11-25_18672.csv"

        cryModObj = Cryomodule(cryomoduleSLAC, cryomoduleLERF,
                               fileName, valveLockedPos, refHeaterVal)

        cavities = [2, 4]

    else:
        print("Q0 Calibration Parameters:")
        # Signature is: get_float/get_int(prompt, low_lim, high_lim)
        refHeaterVal = get_float_lim("Reference Heater Value: ".rjust(32),
                                     0, 15)
        valveLockedPos = get_float_lim("JT Valve locked position: ".rjust(32),
                                       0, 100)
        cryomoduleSLAC = get_int_lim("SLAC Cryomodule Number: ".rjust(32),
                                     0, 33)
        cryomoduleLERF = get_int_lim("LERF Cryomodule Number: ".rjust(32),
                                     2, 3)

        print("\n---------- CRYOMODULE " + str(cryomoduleSLAC)
              + " ----------\n")

        calibFiles = findDataFiles("calib_CM" + str(cryomoduleSLAC))

        print("Options for Calibration Data:")

        print("\n" + dumps(calibFiles, indent=4) + "\n")

        option = get_int_lim(
            "Please choose one of the options above: ", 1, len(calibFiles))

        if option == len(calibFiles):
            cryModObj = buildCryModObj(cryomoduleSLAC, cryomoduleLERF,
                                       valveLockedPos, refHeaterVal)

        else:
            cryModObj = Cryomodule(cryomoduleSLAC, cryomoduleLERF,
                                   calibFiles[option], valveLockedPos,
                                   refHeaterVal)

        if not cryModObj:
            stderr.write("Calibration file generation failed - aborting\n")
            return

        else:
            numCavs = get_int_lim("Number of cavities to analyze: ", 0, 8)

            cavities = []
            for _ in range(numCavs):
                cavity = get_int_lim("Next cavity to analyze: ", 1, 8)
                while cavity in cavities:
                    cavity = get_int_lim(
                        "Please enter a cavity not previously entered: ", 1, 8)
                cavities.append(cavity)

    ax = processData(cryModObj)

    for cav in cavities:
        cavObj = cryModObj.cavities[cav]

        print("\n---------- CAVITY " + str(cav) + " ----------\n")

        cavObj.refGradientVal = get_float_lim("Gradient used during Q0" +
                                              " measurement: ", 0, 22)

        fileStr = "q0meas_CM{cryMod}_cav{cavNum}".format(cryMod=cryomoduleSLAC,
                                                         cavNum=cav)
        q0MeasFiles = findDataFiles(fileStr)

        print("Options for Q0 Meaurement Data:")

        print("\n" + dumps(q0MeasFiles, indent=4) + "\n")

        option = get_int_lim(
            "Please choose one of the options above: ", 1, len(q0MeasFiles))

        if option == len(q0MeasFiles):
            addFileToCavity(cavObj)
            if not cavObj.dataFileName:
                stderr.write("Q0 measurement file generation failed" +
                             " - aborting\n")
                return

        else:
            cavObj.dataFileName = q0MeasFiles[option]

        processData(cavObj)

        for idx, dLL in enumerate(cavObj.runSlopes):

            heatLoad = ((dLL - cryModObj.calibIntercept) / cryModObj.calibSlope)
            cavObj.runHeatLoads.append(heatLoad)

            rfHeatLoad = heatLoad - cavObj.runElecHeatLoads[idx]
            cavObj.runRFHeatLoads.append(rfHeatLoad)

            cavObj.runQ0s.append(calcQ0(cavObj.refGradientVal, rfHeatLoad))

        ax.plot(cavObj.runHeatLoads, cavObj.runSlopes, marker="o",
                linestyle="None", label="Projected Data for " + cavObj.name)
        ax.legend(loc="lower left")

        minCavHeatLoad = min(cavObj.runHeatLoads)
        minCalibHeatLoad = min(cryModObj.runElecHeatLoads)

        if minCavHeatLoad < minCalibHeatLoad:
            yRange = linspace(minCavHeatLoad, minCalibHeatLoad)
            ax.plot(yRange, [cryModObj.calibSlope * i + cryModObj.calibIntercept
                             for i in yRange])

        maxCavHeatLoad = max(cavObj.runHeatLoads)
        maxCalibHeatLoad = max(cryModObj.runElecHeatLoads)

        if maxCavHeatLoad > maxCalibHeatLoad:
            yRange = linspace(maxCalibHeatLoad, maxCavHeatLoad)
            ax.plot(yRange, [cryModObj.calibSlope * i + cryModObj.calibIntercept
                             for i in yRange])

        print(cavObj)

    plt.draw()

    # for i in plt.get_fignums():
    #     plt.figure(i)
    #     plt.savefig("figure%d.png" % i)

    plt.show()


if __name__ == "__main__":
    getQ0Measurements()
