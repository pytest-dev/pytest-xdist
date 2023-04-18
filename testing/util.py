import warnings


class MyWarning2(UserWarning):
    pass


def generate_warning() -> None:
    warnings.warn(MyWarning2("hello"))
