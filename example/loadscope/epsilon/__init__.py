def epsilon1(arg1, arg2=1000):
    """Do epsilon1

    Usage:

    >>> epsilon1(10, 20)
    40
    >>> epsilon1(30)
    1040
    """
    return arg1 + arg2 + 10


def epsilon2(arg1, arg2=1000):
    """Do epsilon2

    Usage:

    >>> epsilon2(10, 20)
    -20
    >>> epsilon2(30)
    -980
    """
    return arg1 - arg2 - 10


def epsilon3(arg1, arg2=1000):
    """Do epsilon3

    Usage:

    >>> epsilon3(10, 20)
    200
    >>> epsilon3(30)
    30000
    """
    return arg1 * arg2
