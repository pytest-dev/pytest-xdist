"""
xdist hooks.

Additionally, pytest-xdist will also decorate a few other hooks
with the worker instance that executed the hook originally:

``pytest_runtest_logreport``: ``rep`` parameter has a ``node`` attribute.

You can use this hooks just as you would use normal pytest hooks, but some care
must be taken in plugins in case ``xdist`` is not installed. Please see:

    http://pytest.org/en/latest/writing_plugins.html#optionally-using-hooks-from-3rd-party-plugins
"""
import pytest


def pytest_xdist_setupnodes(config, specs):
    """ called before any remote node is set up. """


def pytest_xdist_newgateway(gateway):
    """ called on new raw gateway creation. """


def pytest_xdist_rsyncstart(source, gateways):
    """ called before rsyncing a directory to remote gateways takes place. """


def pytest_xdist_rsyncfinish(source, gateways):
    """ called after rsyncing a directory to remote gateways takes place. """


@pytest.mark.firstresult
def pytest_xdist_getremotemodule():
    """ called when creating remote node"""


def pytest_configure_node(node):
    """ configure node information before it gets instantiated. """


def pytest_testnodeready(node):
    """ Test Node is ready to operate. """


def pytest_testnodedown(node, error):
    """ Test Node is down. """


def pytest_xdist_node_collection_finished(node, ids):
    """called by the master node when a node finishes collecting.
    """


@pytest.mark.firstresult
def pytest_xdist_make_scheduler(config, log):
    """ return a node scheduler implementation """


@pytest.mark.trylast
def pytest_xdist_set_test_group_from_nodeid(nodeid):
    """Set the test group of a test using its nodeid.

    This will determine which tests are grouped up together and distributed to
    workers at the same time. This will be called for every test, and whatever
    is returned will be the name of the test group that test belongs to. In
    order to have tests be grouped together, this function must return the same
    value for each nodeid for each test.

    For example, given the following nodeids::

        test/test_something.py::test_form_upload[image-chrome]
        test/test_something.py::test_form_upload[image-firefox]
        test/test_something.py::test_form_upload[video-chrome]
        test/test_something.py::test_form_upload[video-firefox]
        test/test_something_else.py::test_form_upload[image-chrome]
        test/test_something_else.py::test_form_upload[image-firefox]
        test/test_something_else.py::test_form_upload[video-chrome]
        test/test_something_else.py::test_form_upload[video-firefox]

    In order to have the ``chrome`` related tests run together and the
    ``firefox`` tests run together, but allow them to be separated by file,
    this could be done::

        def pytest_xdist_set_test_group_from_nodeid(nodeid):
            browser_names = ['chrome', 'firefox']
            nodeid_params = nodeid.split('[', 1)[-1].rstrip(']').split('-')
            for name in browser_names:
                if name in nodeid_params:
                    return "{test_file}[{browser_name}]".format(
                        test_file=nodeid.split("::", 1)[0],
                        browser_name=name,
                    )

    This would then defer to the default distribution logic for any tests this
    can't apply to (i.e. if this would return ``None`` for a given ``nodeid``).
    """

@pytest.mark.trylast
def pytest_xdist_order_test_groups(workqueue):
    """Sort the queue of test groups to determine the order they will be executed in.

    The ``workqueue`` is an ``OrderedDict`` containing all of the test groups in the
    order they will be handed out to the workers. Groups that are listed first will be
    handed out to workers first. The ``workqueue`` only needs to be modified and doesn't
    need to be returned.

    This can be useful when you want to run longer tests first.
    """
