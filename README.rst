
.. image:: https://travis-ci.org/pytest-dev/pytest-xdist.svg?branch=master
    :target: https://travis-ci.org/pytest-dev/pytest-xdist

.. image:: http://img.shields.io/pypi/v/pytest-xdist.svg
   :target: https://pypi.python.org/pypi/pytest-xdist

.. image:: https://ci.appveyor.com/api/projects/status/56eq1a1avd4sdd7e/branch/master?svg=true
    :target: https://ci.appveyor.com/project/pytestbot/pytest-xdist

xdist: pytest distributed testing plugin
=========================================

The `pytest-xdist`_ plugin extends py.test with some unique
test execution modes:

* test run parallelization_: if you have multiple CPUs or hosts you can use
  those for a combined test run.  This allows to speed up
  development or to use special resources of `remote machines`_.

* ``--boxed``: (not available on Windows) run each test in a boxed_
  subprocess to survive ``SEGFAULTS`` or otherwise dying processes

* ``--looponfail``: run your tests repeatedly in a subprocess.  After each run
  py.test waits until a file in your project changes and then re-runs
  the previously failing tests.  This is repeated until all tests pass
  after which again a full run is performed.

* `Multi-Platform`_ coverage: you can specify different Python interpreters
  or different platforms and run tests in parallel on all of them.

Before running tests remotely, ``py.test`` efficiently "rsyncs" your
program source code to the remote place.  All test results
are reported back and displayed to your local terminal.
You may specify different Python versions and interpreters.


Installation
-----------------------

Install the plugin with::

    easy_install pytest-xdist

    # or

    pip install pytest-xdist

or use the package in develope/in-place mode with
a checkout of the `pytest-xdist repository`_ ::

    python setup.py develop

Usage examples
---------------------

.. _parallelization:

Speed up test runs by sending tests to multiple CPUs
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

To send tests to multiple CPUs, type::

    py.test -n NUM

Especially for longer running tests or tests requiring
a lot of IO this can lead to considerable speed ups. This option can
also be set to ``auto`` for automatic detection of the number of CPUs.

If a test crashes the interpreter, pytest-xdist will automatically restart
that slave and report the failure as usual. You can use the
``--max-slave-restart`` option to limit the number of slaves that can
be restarted, or disable restarting altogether using ``--max-slave-restart=0``.


Running tests in a Python subprocess
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

To instantiate a python2.5 sub process and send tests to it, you may type::

    py.test -d --tx popen//python=python2.5

This will start a subprocess which is run with the "python2.5"
Python interpreter, found in your system binary lookup path.

If you prefix the --tx option value like this::

    --tx 3*popen//python=python2.5

then three subprocesses would be created and tests
will be load-balanced across these three processes.

.. _boxed:

Running tests in a boxed subprocess
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

If you have tests involving C or C++ libraries you might have to deal
with tests crashing the process.  For this case you may use the boxing
options::

    py.test --boxed

which will run each test in a subprocess and will report if a test
crashed the process.  You can also combine this option with
running multiple processes to speed up the test run and use your CPU cores::

    py.test -n3 --boxed

this would run 3 testing subprocesses in parallel which each
create new boxed subprocesses for each test.


.. _`remote machines`:

Sending tests to remote SSH accounts
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Suppose you have a package ``mypkg`` which contains some
tests that you can successfully run locally. And you
have a ssh-reachable machine ``myhost``.  Then
you can ad-hoc distribute your tests by typing::

    py.test -d --tx ssh=myhostpopen --rsyncdir mypkg mypkg

This will synchronize your :code:`mypkg` package directory
to an remote ssh account and then locally collect tests
and send them to remote places for execution.

You can specify multiple :code:`--rsyncdir` directories
to be sent to the remote side.

.. note::

  For py.test to collect and send tests correctly
  you not only need to make sure all code and tests
  directories are rsynced, but that any test (sub) directory
  also has an :code:`__init__.py` file because internally
  py.test references tests as a fully qualified python
  module path.  **You will otherwise get strange errors**
  during setup of the remote side.


You can specify multiple :code:`--rsyncignore` glob patterns
to be ignored when file are sent to the remote side.
There are also internal ignores: :code:`.*, *.pyc, *.pyo, *~`
Those you cannot override using rsyncignore command-line or
ini-file option(s).


Sending tests to remote Socket Servers
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Download the single-module `socketserver.py`_ Python program
and run it like this::

    python socketserver.py

It will tell you that it starts listening on the default
port.  You can now on your home machine specify this
new socket host with something like this::

    py.test -d --tx socket=192.168.1.102:8888 --rsyncdir mypkg mypkg


.. _`atonce`:
.. _`Multi-Platform`:


Running tests on many platforms at once
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

The basic command to run tests on multiple platforms is::

    py.test --dist=each --tx=spec1 --tx=spec2

If you specify a windows host, an OSX host and a Linux
environment this command will send each tests to all
platforms - and report back failures from all platforms
at once.   The specifications strings use the `xspec syntax`_.

.. _`xspec syntax`: http://codespeak.net/execnet/basics.html#xspec

.. _`socketserver.py`: http://bitbucket.org/hpk42/execnet/raw/2af991418160/execnet/script/socketserver.py

.. _`execnet`: http://codespeak.net/execnet

Identifying the worker process during a test
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


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

*New in version 1.15.*

Specifying test exec environments in an ini file
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

pytest (since version 2.0) supports ini-style cofiguration.
You can for example make running with three subprocesses
your default like this:

.. code-block:: ini

    [pytest]
    addopts = -n3

You can also add default environments like this:

.. code-block:: ini

    [pytest]
    addopts = --tx ssh=myhost//python=python2.5 --tx ssh=myhost//python=python2.6

and then just type::

    py.test --dist=each

to run tests in each of the environments.

Specifying "rsync" dirs in an ini-file
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

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

Issue and Bug Tracker
------------------------

Please use the `pytest issue tracker <https://github.com/pytest-dev/pytest-xdist/issues>`_
for reporting bugs in this plugin.
