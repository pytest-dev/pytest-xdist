

.. image:: http://img.shields.io/pypi/v/pytest-xdist.svg
    :alt: PyPI version
    :target: https://pypi.python.org/pypi/pytest-xdist

.. image:: https://img.shields.io/conda/vn/conda-forge/pytest-xdist.svg
    :target: https://anaconda.org/conda-forge/pytest-xdist

.. image:: https://img.shields.io/pypi/pyversions/pytest-xdist.svg
    :alt: Python versions
    :target: https://pypi.python.org/pypi/pytest-xdist

.. image:: https://travis-ci.org/pytest-dev/pytest-xdist.svg?branch=master
    :alt: Travis CI build status
    :target: https://travis-ci.org/pytest-dev/pytest-xdist

.. image:: https://ci.appveyor.com/api/projects/status/56eq1a1avd4sdd7e/branch/master?svg=true
    :alt: AppVeyor build status
    :target: https://ci.appveyor.com/project/pytestbot/pytest-xdist

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/ambv/black

xdist: pytest distributed testing plugin
========================================

The `pytest-xdist`_ plugin extends pytest with some unique
test execution modes:

* test run parallelization_: if you have multiple CPUs or hosts you can use
  those for a combined test run.  This allows to speed up
  development or to use special resources of `remote machines`_.


* ``--looponfail``: run your tests repeatedly in a subprocess.  After each run
  pytest waits until a file in your project changes and then re-runs
  the previously failing tests.  This is repeated until all tests pass
  after which again a full run is performed.

* `Multi-Platform`_ coverage: you can specify different Python interpreters
  or different platforms and run tests in parallel on all of them.

Before running tests remotely, ``pytest`` efficiently "rsyncs" your
program source code to the remote place.  All test results
are reported back and displayed to your local terminal.
You may specify different Python versions and interpreters.

If you would like to know how pytest-xdist works under the covers, checkout
`OVERVIEW <https://github.com/pytest-dev/pytest-xdist/blob/master/OVERVIEW.md>`_.


Installation
------------

Install the plugin with::

    pip install pytest-xdist

or use the package in develop/in-place mode with
a checkout of the `pytest-xdist repository`_ ::

    pip install --editable .

.. _parallelization:

Speed up test runs by sending tests to multiple CPUs
----------------------------------------------------

To send tests to multiple CPUs, type::

    pytest -n NUM

Especially for longer running tests or tests requiring
a lot of I/O this can lead to considerable speed ups. This option can
also be set to ``auto`` for automatic detection of the number of CPUs.

If a test crashes the interpreter, pytest-xdist will automatically restart
that worker and report the failure as usual. You can use the
``--max-worker-restart`` option to limit the number of workers that can
be restarted, or disable restarting altogether using ``--max-worker-restart=0``.

Dividing tests up
^^^^^^^^^^^^^^^^^

In order to divide the tests up amongst the workers, ``pytest-xdist`` first puts sets of
them into "test groups". The tests within a test group are all run together in one shot,
so fixtures of larger scopes won't be run once for every single test. Instead, they'll
be run as many times as they need to for the tests within that test group. But, once
that test group is finished, it should be assumed that all cached fixture values from
that test group's execution are destroyed.

By default, there is no grouping logic and every individual test is placed in its own
test group, so using the ``-n`` option will send pending tests to any worker that is
available, without any guaranteed order. It should be assumed that when using this
approach, every single test is run entirely in isolation from the others, meaning the
tests can't rely on cached fixture values from larger-scoped fixtures.

Provided test grouping options
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default, ``pytest-xdist`` doesn't group any tests together, but it provides some
grouping options, based on simple criteria about a test's nodeid. so you can gunarantee
that certain tests are run in the same process. When they're run in the same process,
you gunarantee that larger-scoped fixtures are only executed as many times as would
normally be expected for the tests in the test group. But, once that test group is
finished, it should be assumed that all cached fixture values from that test group's
execution are destroyed.

Here's the options that are built in:

* ``--dist=loadscope``: tests will be grouped by **module** shown in each test's node
  for *test functions* and by the **class** shown in each test's nodeid for *test
  methods*. This feature was added in version ``1.19``.

* ``--dist=loadfile``: tests will be grouped by the **module** shown in each test's
  nodeid. This feature was added in version ``1.21``.

Defining custom load distribution logic
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``pytest-xdist`` iterates over the entire list of collected tests and usually determines
what group to put them in based off of their nodeid. There is no set number of test
groups, as it creates a new groups as needed. You can tap into this system to define
your own grouping logic by using the ``pytest_xdist_set_test_group_from_nodeid``.

If you define your own copy of that hook, it will be called once for every test, and the
nodeid for each test will be passed in. Whatever it returns is the test group for that
test. If a test group doesn't already exist with that name, then it will be created, so
anything can be used.

For example, let's say you have the following tests::

    test/test_something.py::test_form_upload[image-chrome]
    test/test_something.py::test_form_upload[image-firefox]
    test/test_something.py::test_form_upload[video-chrome]
    test/test_something.py::test_form_upload[video-firefox]
    test/test_something_else.py::test_form_upload[image-chrome]
    test/test_something_else.py::test_form_upload[image-firefox]
    test/test_something_else.py::test_form_upload[video-chrome]
    test/test_something_else.py::test_form_upload[video-firefox]

In order to have the ``chrome`` related tests run together and the ``firefox`` tests run
together, but allow them to be separated by file, this could be done:

.. code-block:: python

    def pytest_xdist_set_test_group_from_nodeid(nodeid):
        browser_names = ['chrome', 'firefox']
        nodeid_params = nodeid.split('[', 1)[-1].rstrip(']').split('-')
        for name in browser_names:
            if name in nodeid_params:
                return "{test_file}[{browser_name}]".format(
                    test_file=nodeid.split("::", 1)[0],
                    browser_name=name,
                )

The tests would then be divided into these test groups:

.. code-block:: python

    {
        "test/test_something.py::test_form_upload[chrome]" : [
            "test/test_something.py::test_form_upload[image-chrome]",
            "test/test_something.py::test_form_upload[video-chrome]"
        ],
        "test/test_something.py::test_form_upload[firefox]": [
            "test/test_something.py::test_form_upload[image-firefox]",
            "test/test_something.py::test_form_upload[video-firefox]"
        ],
        "test/test_something_else.py::test_form_upload[firefox]": [
            "test/test_something_else.py::test_form_upload[image-firefox]",
            "test/test_something_else.py::test_form_upload[video-firefox]"
        ],
        "test/test_something_else.py::test_form_upload[chrome]": [
            "test/test_something_else.py::test_form_upload[image-chrome]",
            "test/test_something_else.py::test_form_upload[video-chrome]"
        ]
    }

You can also fall back on one of the default load distribution mechanism by passing the
arguments for them listed above when you call pytest. Because this example returns
``None`` if the nodeid doesn't meet any of the criteria, it will defer to whichever
mechanism you chose. So if you passed ``--dist=loadfile``, tests would otherwise be
divided up by file name.

Keep in mind, this is a means of optimization, not a means for determinism.

Controlling test group execution order
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Sometimes you may want to have certain test groups start before or after others. Once
the test groups have been determined, the ``OrderedDict`` they are stored in can have
its order modified through the ``pytest_xdist_order_test_groups`` hook. For example, in
order to move the test group named ``"groupA"`` to the end of the queue, this can be
done:

.. code-block:: python

    def pytest_xdist_order_test_groups(workqueue):
        workqueue.move_to_end("groupA")

Keep in mind, this is a means of optimization, not a means for determinism or filtering.
Removing test groups from this ``OrderedDict``, or adding new ones in after the fact can
have unforseen consequences.

If you want to filter out which tests get run, it is recommended to either rely on test
suite structure (so you can target the tests in specific locations), or by using marks
(so you can select or filter out based on specific marks with the ``-m`` flag).

Making session-scoped fixtures execute only once
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``pytest-xdist`` is designed so that each worker process will perform its own collection and execute
a subset of all tests. This means that tests in different processes requesting a high-level
scoped fixture (for example ``session``) will execute the fixture code more than once, which
breaks expectations and might be undesired in certain situations.

While ``pytest-xdist`` does not have a builtin support for ensuring a session-scoped fixture is
executed exactly once, this can be achieved by using a lock file for inter-process communication.

The example below needs to execute the fixture ``session_data`` only once (because it is
resource intensive, or needs to execute only once to define configuration options, etc), so it makes
use of a `FileLock <https://pypi.org/project/filelock/>`_ to produce the fixture data only once
when the first process requests the fixture, while the other processes will then read
the data from a file.

Here is the code:

.. code-block:: python

    import json

    import pytest
    from filelock import FileLock


    @pytest.fixture(scope="session")
    def session_data(tmp_path_factory, worker_id):
        if not worker_id:
            # not executing in with multiple workers, just produce the data and let
            # pytest's fixture caching do its job
            return produce_expensive_data()

        # get the temp directory shared by all workers
        root_tmp_dir = tmp_path_factory.getbasetemp().parent

        fn = root_tmp_dir / "data.json"
        with FileLock(str(fn) + ".lock"):
            if fn.is_file():
                data = json.loads(fn.read_text())
            else:
                data = produce_expensive_data()
                fn.write_text(json.dumps(data))
        return data


The example above can also be use in cases a fixture needs to execute exactly once per test session, like
initializing a database service and populating initial tables.

This technique might not work for every case, but should be a starting point for many situations
where executing a high-scope fixture exactly once is important.

Running tests in a Python subprocess
------------------------------------

To instantiate a python3.5 subprocess and send tests to it, you may type::

    pytest -d --tx popen//python=python3.5

This will start a subprocess which is run with the ``python3.5``
Python interpreter, found in your system binary lookup path.

If you prefix the --tx option value like this::

    --tx 3*popen//python=python3.5

then three subprocesses would be created and tests
will be load-balanced across these three processes.

.. _boxed:

Running tests in a boxed subprocess
-----------------------------------

This functionality has been moved to the
`pytest-forked <https://github.com/pytest-dev/pytest-forked>`_ plugin, but the ``--boxed`` option
is still kept for backward compatibility.

.. _`remote machines`:

Sending tests to remote SSH accounts
------------------------------------

Suppose you have a package ``mypkg`` which contains some
tests that you can successfully run locally. And you
have a ssh-reachable machine ``myhost``.  Then
you can ad-hoc distribute your tests by typing::

    pytest -d --tx ssh=myhostpopen --rsyncdir mypkg mypkg

This will synchronize your :code:`mypkg` package directory
to a remote ssh account and then locally collect tests
and send them to remote places for execution.

You can specify multiple :code:`--rsyncdir` directories
to be sent to the remote side.

.. note::

  For pytest to collect and send tests correctly
  you not only need to make sure all code and tests
  directories are rsynced, but that any test (sub) directory
  also has an :code:`__init__.py` file because internally
  pytest references tests as a fully qualified python
  module path.  **You will otherwise get strange errors**
  during setup of the remote side.


You can specify multiple :code:`--rsyncignore` glob patterns
to be ignored when file are sent to the remote side.
There are also internal ignores: :code:`.*, *.pyc, *.pyo, *~`
Those you cannot override using rsyncignore command-line or
ini-file option(s).


Sending tests to remote Socket Servers
--------------------------------------

Download the single-module `socketserver.py`_ Python program
and run it like this::

    python socketserver.py

It will tell you that it starts listening on the default
port.  You can now on your home machine specify this
new socket host with something like this::

    pytest -d --tx socket=192.168.1.102:8888 --rsyncdir mypkg mypkg


.. _`atonce`:
.. _`Multi-Platform`:


Running tests on many platforms at once
---------------------------------------

The basic command to run tests on multiple platforms is::

    pytest --dist=each --tx=spec1 --tx=spec2

If you specify a windows host, an OSX host and a Linux
environment this command will send each tests to all
platforms - and report back failures from all platforms
at once. The specifications strings use the `xspec syntax`_.

.. _`xspec syntax`: http://codespeak.net/execnet/basics.html#xspec

.. _`socketserver.py`: http://bitbucket.org/hpk42/execnet/raw/2af991418160/execnet/script/socketserver.py

.. _`execnet`: http://codespeak.net/execnet

Identifying the worker process during a test
--------------------------------------------

*New in version 1.15.*

If you need to determine the identity of a worker process in
a test or fixture, you may use the ``worker_id`` fixture to do so:

.. code-block:: python

    @pytest.fixture()
    def user_account(worker_id):
        """ use a different account in each xdist worker """
        return "account_%s" % worker_id

When ``xdist`` is disabled (running with ``-n0`` for example), then
``worker_id`` will return ``"master"``.

Additionally, worker processes have the following environment variables
defined:

* ``PYTEST_XDIST_WORKER``: the name of the worker, e.g., ``"gw2"``.
* ``PYTEST_XDIST_WORKER_COUNT``: the total number of workers in this session,
  e.g., ``"4"`` when ``-n 4`` is given in the command-line.

The information about the worker_id in a test is stored in the ``TestReport`` as
well, under the ``worker_id`` attribute.

Acessing ``sys.argv`` from the master node in workers
-----------------------------------------------------

To access the ``sys.argv`` passed to the command-line of the master node, use
``request.config.workerinput["mainargv"]``.


Specifying test exec environments in an ini file
------------------------------------------------

You can use pytest's ini file configuration to avoid typing common options.
You can for example make running with three subprocesses your default like this:

.. code-block:: ini

    [pytest]
    addopts = -n3

You can also add default environments like this:

.. code-block:: ini

    [pytest]
    addopts = --tx ssh=myhost//python=python3.5 --tx ssh=myhost//python=python3.6

and then just type::

    pytest --dist=each

to run tests in each of the environments.


Specifying "rsync" dirs in an ini-file
--------------------------------------

In a ``tox.ini`` or ``setup.cfg`` file in your root project directory
you may specify directories to include or to exclude in synchronisation:

.. code-block:: ini

    [pytest]
    rsyncdirs = . mypkg helperpkg
    rsyncignore = .hg

These directory specifications are relative to the directory
where the configuration file was found.

.. _`pytest-xdist`: http://pypi.python.org/pypi/pytest-xdist
.. _`pytest-xdist repository`: https://github.com/pytest-dev/pytest-xdist
.. _`pytest`: http://pytest.org
