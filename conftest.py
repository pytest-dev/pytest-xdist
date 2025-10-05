import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--force-log-cli",
        action="store_true",
        help="Force enable log_cli even when xdist is active",
    )

def pytest_configure(config):
    # Detect if xdist (parallel execution) is active
    xdist_active = hasattr(config, "workerinput") or config.pluginmanager.hasplugin("xdist")
import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--force-log-cli",
        action="store_true",
        help="Force enable log_cli even when xdist is active",
    )

def pytest_configure(config):
    # Detect if xdist (parallel execution) is active
    xdist_active = hasattr(config, "workerinput") or config.pluginmanager.hasplugin("xdist")

    if not xdist_active or config.getoption("--force-log-cli"):
        # Normal run (no xdist): enable live logs
        config.option.log_cli = True
        config.option.log_cli_level = "INFO"
    else:
        # xdist active: disable live logs so we get the 'dots' progress
        config.option.log_cli = False

    if not xdist_active or config.getoption("--force-log-cli"):
        # Normal run (no xdist): enable live logs
        config.option.log_cli = True
        config.option.log_cli_level = "INFO"
    else:
        # xdist active: disable live logs so we get the 'dots' progress
        config.option.log_cli = False
