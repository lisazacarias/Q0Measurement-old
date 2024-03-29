from __future__ import print_function, division

from _csv import reader as _reader
from datetime import datetime
from json import dumps

from builtins import input
from time import sleep
from sys import stdout, stderr
from subprocess import check_output, CalledProcessError, check_call
from os import devnull
from csv import reader
from re import compile, findall
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from typing import List, Callable, Union, Dict, Tuple, Optional

# Set True to use a known data set for debugging and/or demoing
# Set False to prompt the user for real data

TEST_MODE = True

# The relationship between the LHE content of a cryomodule and the readback from
# the liquid level sensors isn't linear over the full range of the sensors. We
# have chosen to gather all our data with the downstream sensor reading between
# 90% and 95%.
MIN_DS_LL = 90
MAX_DS_LL = 95

UPSTREAM_LL_LOWER_LIMIT = 66

# Used to reject data where the JT valve wasn't at the correct position
VALVE_POSITION_TOLERANCE = 2

# Used to reject data where the cavity heater wasn't at the correct value
HEATER_TOLERANCE = 1

# The minimum acceptable run length is fifteen minutes  (900 seconds)
MIN_RUN_DURATION = 900

# Used to reject data where the cavity gradient wasn't at the correct value
GRAD_TOLERANCE = 0.7

# We fetch data from the JLab archiver with a program called MySampler, which
# samples the chosen PVs at a user-specified time interval. Increase to improve
# statistics, decrease to lower the size of the CSV files and speed up
# MySampler data acquisition.
MYSAMPLER_TIME_INTERVAL = 1

# Used in custom input functions
ERROR_MESSAGE = "Please provide valid input"

# This is used to suppress the output of the caput function.
FNULL = open(devnull, "w")

# The number of distinct heater settings we're using for cryomodule calibrations
NUM_CAL_RUNS = 5


def isYes(prompt):
    return getStrLim(prompt + " (y/n) ", ["Y", "y", "N", "n"]) in ["y", "Y"]


def getStrLim(prompt, acceptable_strings):
    # type: (str, List[str]) -> str

    response = get_input(prompt, str)

    while response not in acceptable_strings:
        stderr.write(ERROR_MESSAGE + "\n")
        sleep(0.01)
        response = get_input(prompt, str)

    return response


def writeAndFlushStdErr(message):
    # type: (str) -> None
    stderr.write("\n{MSSG}\n".format(MSSG=message))
    stderr.flush()


def writeAndWait(message, timeToWait=0):
    # type: (str, float) -> None
    stdout.write(message)
    stdout.flush()
    sleep(timeToWait)


def get_float_lim(prompt, low_lim, high_lim):
    # type: (str, float, float) -> float
    return getNumericalInput(prompt, low_lim, high_lim, float)


def getNumInputFromLst(prompt, lst, inputType):
    # type: (str, List[Union[int, float]], Callable) -> Union[float, int]
    response = get_input(prompt, inputType)
    while response not in lst:
        stderr.write(ERROR_MESSAGE + "\n")
        # Need to pause briefly for some reason to make sure the error message
        # shows up before the next prompt
        sleep(0.01)
        response = get_input(prompt, inputType)

    return response


def getNumericalInput(prompt, lowLim, highLim, inputType):
    # type: (str, Union[int, float], Union[int, float], Callable) -> Union[int, float]
    response = get_input(prompt, inputType)

    while response < lowLim or response > highLim:
        stderr.write(ERROR_MESSAGE + "\n")
        sleep(0.01)
        response = get_input(prompt, inputType)

    return response


def get_input(prompt, desired_type):
    # type: (str, Callable) -> Union[int, float, str]

    response = input(prompt)

    try:
        response = desired_type(response)
    except ValueError:
        stderr.write(str(desired_type) + " required\n")
        sleep(0.01)
        return get_input(prompt, desired_type)

    return response


def get_int_lim(prompt, low_lim, high_lim):
    # type: (str, int, int) -> int
    return getNumericalInput(prompt, low_lim, high_lim, int)


# PyEpics doesn't work at LERF yet...
# noinspection PyArgumentList
def cagetPV(pv, startIdx=1, attempt=1):
    # type: (str, int, int) -> [str]

    if attempt < 4:
        try:
            out = check_output(["caget", pv, "-n"]).split()[startIdx:]
            if startIdx == 1:
                return out.pop()
            elif startIdx >= 2:
                return out
        except CalledProcessError as _:
            sleep(2)
            print("Retrying caget")
            return cagetPV(pv, startIdx, attempt + 1)

    else:
        raise CalledProcessError("caget failed too many timeStamps")


# noinspection PyArgumentList
def caputPV(pv, val, attempt=1):
    # type: (str, str, int) -> int

    if attempt < 4:
        try:
            out = check_call(["caput", pv, val], stdout=FNULL)
            sleep(2)
            return out
        except CalledProcessError:
            sleep(2)
            print("Retrying caput")
            return caputPV(pv, val, attempt + 1)
    else:
        raise CalledProcessError("caput failed too many timeStamps")


def makeTimeFromStr(row, idx):
    # type: (List[str], int) -> datetime
    return datetime.strptime(row[idx], "%m/%d/%y %H:%M")


def getTimeParams(row, indices):
    # type: (List[str], Dict[str, int]) -> Tuple[datetime, datetime, int]
    startTime = makeTimeFromStr(row, indices["startIdx"])
    endTime = makeTimeFromStr(row, indices["endIdx"])

    timeIntervalStr = row[indices["timeIntIdx"]]
    timeInterval = (int(timeIntervalStr) if timeIntervalStr
                    else MYSAMPLER_TIME_INTERVAL)

    return startTime, endTime, timeInterval


############################################################################
# getArchiveData runs a shell command to get archive data. The syntax we're
# using is:
#
#     mySampler -b "%Y-%m-%d %H:%M:%S" -s 1s -n[numPoints] [pv1] ... [pvn]
#
# where the "-b" denotes the start time, "-s 1s" says that the desired time
# step between data points is 1 second, -n[numPoints] tells us how many
# points we want, and [pv1]...[pvn] are the PVs we want archived
#
# Ex:
#     mySampler -b "2019-03-28 14:16" -s 30s -n11 R121PMES R221PMES
#
# @param startTime: datetime object
# @param signals: list of PV strings
############################################################################
def getArchiveData(startTime, numPoints, signals,
                   timeInt=MYSAMPLER_TIME_INTERVAL):
    # type: (datetime, int, List[str], int) -> Optional[str]
    cmd = (['mySampler', '-b'] + [startTime.strftime("%Y-%m-%d %H:%M:%S")]
           + ['-s', str(timeInt) + 's', '-n' + str(numPoints)]
           + signals)
    try:
        return check_output(cmd)

    except (CalledProcessError, OSError) as e:
        writeAndFlushStdErr("mySampler failed with error: " + str(e) + "\n")
        return None


def parseRawData(startTime, numPoints, signals,
                 timeInt=MYSAMPLER_TIME_INTERVAL):
    # type: (datetime, int, List[str], int) -> Optional[_reader]
    print("\nGetting data from the archive...\n")
    rawData = getArchiveData(startTime, numPoints, signals, timeInt)

    if not rawData:
        return None

    else:
        rawDataSplit = rawData.splitlines()
        rows = ["\t".join(rawDataSplit.pop(0).strip().split())]
        rows.extend(list(map(lambda x: reformatDate(x), rawDataSplit)))
        return reader(rows, delimiter='\t')


def reformatDate(row):
    # type: (str) -> unicode
    try:
        # This clusterfuck regex is pretty much just trying to find strings
        # that match %Y-%m-%d %H:%M:%S and making them %Y-%m-%d-%H:%M:%S
        # instead (otherwise the csv parser interprets it as two different
        # columns)
        regex = compile("[0-9]{4}-[0-9]{2}-[0-9]{2}"
                        + " [0-9]{2}:[0-9]{2}:[0-9]{2}")
        res = findall(regex, row)[0].replace(" ", "-")
        reformattedRow = regex.sub(res, row)
        return "\t".join(reformattedRow.strip().split())

    except IndexError:

        writeAndFlushStdErr("Could not reformat date for row: " + str(row)
                            + "\n")
        return "\t".join(row.strip().split())


def genAxis(title, xlabel, ylabel):
    # type: (str, str, str) -> Axes
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return ax


# A surprisingly ugly way to pretty print a dictionary
def printOptions(options):
    # type: (Dict[int, str]) -> None
    print(("\n" + dumps(options, indent=4) + "\n")
          .replace('"', '').replace(',', ''))


def addOption(csvRow, lineNum, indices, options):
    # type: (List[str], int, Dict[str, int], Dict[int, str]) -> None
    startTime = makeTimeFromStr(csvRow, indices["startIdx"])
    endTime = makeTimeFromStr(csvRow, indices["endIdx"])
    rate = csvRow[indices["timeIntIdx"]]
    options[lineNum] = ("{START} to {END} ({RATE}s sample interval)"
                        .format(START=startTime, END=endTime,
                                RATE=rate))


def getSelection(duration, suffix, options):
    # type: (float, str, Dict[int, str]) -> int
    # Running a new Q0 measurement or heater calibration is always
    # presented as the last option in the list
    options[max(options) + 1] = ("Launch new {TYPE} ({DUR} hours)"
                                 .format(TYPE=suffix, DUR=duration))
    printOptions(options)
    return getNumInputFromLst(("Please select a {TYPE} option: "
                               .format(TYPE=suffix)), options.keys(), int)


def drawAndShow():
    plt.draw()
    plt.show()
