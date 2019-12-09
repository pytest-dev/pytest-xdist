from __future__ import print_function

import os
import sys

import pytest


def pytest_addoption(parser):
    print("adding --foobar option. [%s]" % os.getpid())
    parser.addoption("--foobar", action='store', dest='foobar_opt')


@pytest.mark.tryfirst
def pytest_load_initial_conftests(early_config):
    opt = early_config.known_args_namespace.foobar_opt
    print("--foobar=%s active! [%s]" % (opt, os.getpid()), file=sys.stderr)
