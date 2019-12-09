from setuptools import setup

setup(
    py_modules=["foobarplugin"],
    entry_points={"pytest11": ["foobarplugin = foobarplugin"]},
)
