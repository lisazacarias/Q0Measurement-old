from __future__ import print_function, division
from builtins import input
from time import sleep
from sys import stdout, stderr
from subprocess import check_output, CalledProcessError, check_call
from os import devnull


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


def getYesNo(prompt):
    return input(prompt) in ["y", "Y"]


def writeAndFlushStdErr(message):
    stderr.write("\n{MSSG}\n".format(MSSG=message))
    stderr.flush()


def writeAndWait(message, timeToWait=0):
    # type: (str, float) -> None
    stdout.write(message)
    stdout.flush()
    sleep(timeToWait)


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
        raise CalledProcessError("caget failed too many times")


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
        raise CalledProcessError("caput failed too many times")