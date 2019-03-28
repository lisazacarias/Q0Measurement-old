from __future__ import print_function

"""user_input.py -- Contains the get_input function. Has debugging
functionality if called as __main__.
Author: Ben Ripman
Editor: Lisa Zacarias
"""

if hasattr(__builtins__, 'raw_input'):
    input = raw_input

ERROR_MESSAGE = "Please provide valid input"


def get_input(prompt, desired_type):
    """
        Uses the supplied prompt to pester the user until they give
        input of the desired type.
    """

    response = input(prompt)

    try:
        response = desired_type(response)
    except ValueError:
        print(str(desired_type) + " required")
        return get_input(prompt, desired_type)

    return response


def get_str_lim(prompt, acceptable_strings):
    """
        Only accepts input that is contained within the acceptable_strings
        list.
    """

    response = get_input(prompt, str)
    while response not in acceptable_strings:
        print(ERROR_MESSAGE)
        response = get_input(prompt, str)

    return response


def get_str(prompt):
    """
        Uses the supplied prompt to pester the user until they yield a
        string.
    """
    return get_input(prompt, str)


def get_int_lim(prompt, low_lim, high_lim):
    """ Only accepts input that is >= low_lim and <= high_lim. """
    response = get_input(prompt, int)

    while response < low_lim or response > high_lim:
        print(ERROR_MESSAGE)
        response = get_input(prompt, int)

    return response


def get_int(prompt):
    """
        Uses the supplied prompt to pester the user until they yield an
        integer.
    """
    return get_input(prompt, int)


def get_float_lim(prompt, low_lim, high_lim):
    """ Only accepts input that is >= low_lim and <= high_lim. """
    response = get_input(prompt, float)

    while response < low_lim or response > high_lim:
        print(ERROR_MESSAGE)
        response = get_input(prompt, float)

    return response


def get_float(prompt):
    """
        Uses the supplied prompt to pester the user until they yield a
        float.
    """
    return get_input(prompt, float)


def main():
    """ Tests various functions defined in this module. """
    print("\nHello world from user_input.py!\n")

    print("Let's try asking the user for some input.")
    get_str('Give me any string: ')
    get_str_lim('Give me a decision (y or n): ', ['y', 'n'])
    get_int('Give me any integer: ')
    get_int_lim('Give me a number between 1 and 10: ', 1, 10)
    get_float('Give me any float: ')
    get_float_lim('Give me a float between 0 and 1: ', 0, 1)

if __name__ == '__main__':
    main()
