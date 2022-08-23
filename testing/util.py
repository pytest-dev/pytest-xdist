import warnings


class MyWarning2(UserWarning):
    pass


def generate_warning():
    warnings.warn(MyWarning2("hello"))
