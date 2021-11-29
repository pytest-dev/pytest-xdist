============
pytest-xdist
============

.. image:: http://img.shields.io/pypi/v/pytest-xdist.svg
    :alt: PyPI version
    :target: https://pypi.python.org/pypi/pytest-xdist

.. image:: https://img.shields.io/conda/vn/conda-forge/pytest-xdist.svg
    :target: https://anaconda.org/conda-forge/pytest-xdist

.. image:: https://img.shields.io/pypi/pyversions/pytest-xdist.svg
    :alt: Python versions
    :target: https://pypi.python.org/pypi/pytest-xdist

.. image:: https://github.com/pytest-dev/pytest-xdist/workflows/build/badge.svg
    :target: https://github.com/pytest-dev/pytest-xdist/actions

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/ambv/black

The `pytest-xdist`_ plugin extends pytest with new test execution modes, the most used being distributing
tests across multiple CPUs to speed up test execution::

    pytest -n auto

With this call, pytest will spawn a number of workers processes equal to the number of available CPUs, and distribute
the tests randomly across them. There is also a number of `distribution modes`_ to choose from.

**NOTE**: due to how pytest-xdist is implemented, the ``-s/--capture=no`` option does not work.

.. contents:: **Table of Contents**

Installation
------------

Install the plugin with::

    pip install pytest-xdist


To use ``psutil`` for detection of the number of CPUs available, install the ``psutil`` extra::

    pip install pytest-xdist[psutil]


Features
--------

* Test run parallelization_: tests can be executed across  multiple CPUs or hosts.
  This allows to speed up development or to use special resources of `remote machines`_.

* ``--looponfail``: run your tests repeatedly in a subprocess.  After each run
  pytest waits until a file in your project changes and then re-runs
  the previously failing tests.  This is repeated until all tests pass
  after which again a full run is performed.

* `Multi-Platform`_ coverage: you can specify different Python interpreters
  or different platforms and run tests in parallel on all of them.

  Before running tests remotely, ``pytest`` efficiently "rsyncs" your
  program source code to the remote place.
  You may specify different Python versions and interpreters. It does not
  installs/synchronize dependencies however.

  **Note**: this mode exists mostly for backward compatibility, as modern development
  relies on continuous integration for multi-platform testing.

.. _parallelization:

Running tests across multiple CPUs
----------------------------------

To send tests to multiple CPUs, use the ``-n`` (or ``--numprocesses``) option::

    pytest -n 8

Pass ``-n auto`` to use as many processes as your computer has CPU cores. This
can lead to considerable speed ups, especially if your test suite takes a
noticeable amount of time.

The test distribution algorithm is configured with the ``--dist`` command-line option:

.. _distribution modes:

* ``--dist load`` **(default)**: Sends pending tests to any worker that is
  available, without any guaranteed order.

* ``--dist loadscope``: Tests are grouped by **module** for *test functions*
  and by **class** for *test methods*. Groups are distributed to available
  workers as whole units. This guarantees that all tests in a group run in the
  same process. This can be useful if you have expensive module-level or
  class-level fixtures. Grouping by class takes priority over grouping by
  module.

* ``--dist loadfile``: Tests are grouped by their containing file. Groups are
  distributed to available workers as whole units. This guarantees that all
  tests in a file run in the same worker.

* ``--dist loadgroup``: Tests are grouped by the ``xdist_group`` mark. Groups are
  distributed to available workers as whole units. This guarantees that all
  tests with same ``xdist_group`` name run in the same worker.

  .. code-block:: python

      @pytest.mark.xdist_group(name="group1")
      def test1():
          pass

      class TestA:
          @pytest.mark.xdist_group("group1")
          def test2():
              pass

  This will make sure ``test1`` and ``TestA::test2`` will run in the same worker.
  Tests without the ``xdist_group`` mark are distributed normally as in the ``--dist=load`` mode.

* ``--dist no``: The normal pytest execution mode, runs one test at a time (no distribution at all).


Running tests in a Python subprocess
------------------------------------

To instantiate a ``python3.9`` subprocess and send tests to it, you may type::

    pytest -d --tx popen//python=python3.9

This will start a subprocess which is run with the ``python3.9``
Python interpreter, found in your system binary lookup path.

If you prefix the --tx option value like this::

    --tx 3*popen//python=python3.9

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

.. _`xspec syntax`: https://codespeak.net/execnet/basics.html#xspec

.. _`socketserver.py`: https://raw.githubusercontent.com/pytest-dev/execnet/master/execnet/script/socketserver.py

.. _`execnet`: https://codespeak.net/execnet


When tests crash
----------------

If a test crashes a worker, pytest-xdist will automatically restart that worker
and report the test’s failure. You can use the ``--max-worker-restart`` option
to limit the number of worker restarts that are allowed, or disable restarting
altogether using ``--max-worker-restart 0``.


How-tos
-------

Identifying the worker process during a test
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

Worker processes also have the following environment variables
defined:

* ``PYTEST_XDIST_WORKER``: the name of the worker, e.g., ``"gw2"``.
* ``PYTEST_XDIST_WORKER_COUNT``: the total number of workers in this session,
  e.g., ``"4"`` when ``-n 4`` is given in the command-line.

The information about the worker_id in a test is stored in the ``TestReport`` as
well, under the ``worker_id`` attribute.

Since version 2.0, the following functions are also available in the ``xdist`` module:

.. code-block:: python

    def is_xdist_worker(request_or_session) -> bool:
        """Return `True` if this is an xdist worker, `False` otherwise

        :param request_or_session: the `pytest` `request` or `session` object
        """

     def is_xdist_controller(request_or_session) -> bool:
        """Return `True` if this is the xdist controller, `False` otherwise

        Note: this method also returns `False` when distribution has not been
        activated at all.

        :param request_or_session: the `pytest` `request` or `session` object
        """

    def is_xdist_master(request_or_session) -> bool:
        """Deprecated alias for is_xdist_controller."""

    def get_xdist_worker_id(request_or_session) -> str:
        """Return the id of the current worker ('gw0', 'gw1', etc) or 'master'
        if running on the controller node.

        If not distributing tests (for example passing `-n0` or not passing `-n` at all)
        also return 'master'.

        :param request_or_session: the `pytest` `request` or `session` object
        """


Identifying workers from the system environment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*New in version 2.4*

If the `setproctitle`_ package is installed, ``pytest-xdist`` will use it to
update the process title (command line) on its workers to show their current
state.  The titles used are ``[pytest-xdist running] file.py/node::id`` and
``[pytest-xdist idle]``, visible in standard tools like ``ps`` and ``top`` on
Linux, Mac OS X and BSD systems.  For Windows, please follow `setproctitle`_'s
pointer regarding the Process Explorer tool.

This is intended purely as an UX enhancement, e.g. to track down issues with
long-running or CPU intensive tests.  Errors in changing the title are ignored
silently.  Please try not to rely on the title format or title changes in
external scripts.

.. _`setproctitle`: https://pypi.org/project/setproctitle/


Uniquely identifying the current test run
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*New in version 1.32.*

If you need to globally distinguish one test run from others in your
workers, you can use the ``testrun_uid`` fixture. For instance, let's say you
wanted to create a separate database for each test run:

.. code-block:: python

    import pytest
    from posix_ipc import Semaphore, O_CREAT

    @pytest.fixture(scope="session", autouse=True)
    def create_unique_database(testrun_uid):
        """ create a unique database for this particular test run """
        database_url = f"psql://myapp-{testrun_uid}"

        with Semaphore(f"/{testrun_uid}-lock", flags=O_CREAT, initial_value=1):
            if not database_exists(database_url):
                create_database(database_url)

    @pytest.fixture()
    def db(testrun_uid):
        """ retrieve unique database """
        database_url = f"psql://myapp-{testrun_uid}"
        return database_get_instance(database_url)


Additionally, during a test run, the following environment variable is defined:

* ``PYTEST_XDIST_TESTRUNUID``: the unique id of the test run.

Accessing ``sys.argv`` from the controller node in workers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To access the ``sys.argv`` passed to the command-line of the controller node, use
``request.config.workerinput["mainargv"]``.


Specifying test exec environments in an ini file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can use pytest's ini file configuration to avoid typing common options.
You can for example make running with three subprocesses your default like this:

.. code-block:: ini

    [pytest]
    addopts = -n3

You can also add default environments like this:

.. code-block:: ini

    [pytest]
    addopts = --tx ssh=myhost//python=python3.9 --tx ssh=myhost//python=python3.6

and then just type::

    pytest --dist=each

to run tests in each of the environments.


Specifying "rsync" dirs in an ini-file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
        if worker_id == "master":
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


How does xdist work?
--------------------

``xdist`` works by spawning one or more **workers**, which are
controlled by the **controller**. Each **worker** is responsible for
performing a full test collection and afterwards running tests as
dictated by the **controller**.

The execution flow is:

1. **controller** spawns one or more **workers** at the beginning of the
   test session. The communication between **controller** and **worker**
   nodes makes use of `execnet <https://codespeak.net/execnet/>`__ and
   its
   `gateways <https://codespeak.net/execnet/basics.html#gateways-bootstrapping-python-interpreters>`__.
   The actual interpreters executing the code for the **workers** might
   be remote or local.

2. Each **worker** itself is a mini pytest runner. **workers** at this
   point perform a full test collection, sending back the collected
   test-ids back to the **controller** which does not perform any
   collection itself.

3. The **controller** receives the result of the collection from all
   nodes. At this point the **controller** performs some sanity check to
   ensure that all **workers** collected the same tests (including
   order), bailing out otherwise. If all is well, it converts the list
   of test-ids into a list of simple indexes, where each index
   corresponds to the position of that test in the original collection
   list. This works because all nodes have the same collection list, and
   saves bandwidth because the **controller** can now tell one of the
   workers to just *execute test index 3* index of passing the full test
   id.

4. If **dist-mode** is **each**: the **controller** just sends the full
   list of test indexes to each node at this moment.

5. If **dist-mode** is **load**: the **controller** takes around 25% of
   the tests and sends them one by one to each **worker** in a round
   robin fashion. The rest of the tests will be distributed later as
   **workers** finish tests (see below).

6. Note that ``pytest_xdist_make_scheduler`` hook can be used to
   implement custom tests distribution logic.

7. **workers** re-implement ``pytest_runtestloop``: pytest’s default
   implementation basically loops over all collected items in the
   ``session`` object and executes the ``pytest_runtest_protocol`` for
   each test item, but in xdist **workers** sit idly waiting for
   **controller** to send tests for execution. As tests are received by
   **workers**, ``pytest_runtest_protocol`` is executed for each test.
   Here it worth noting an implementation detail: **workers** always
   must keep at least one test item on their queue due to how the
   ``pytest_runtest_protocol(item, nextitem)`` hook is defined: in order
   to pass the ``nextitem`` to the hook, the worker must wait for more
   instructions from controller before executing that remaining test. If
   it receives more tests, then it can safely call
   ``pytest_runtest_protocol`` because it knows what the ``nextitem``
   parameter will be. If it receives a “shutdown” signal, then it can
   execute the hook passing ``nextitem`` as ``None``.

8. As tests are started and completed at the **workers**, the results
   are sent back to the **controller**, which then just forwards the
   results to the appropriate pytest hooks: ``pytest_runtest_logstart``
   and ``pytest_runtest_logreport``. This way other plugins (for example
   ``junitxml``) can work normally. The **controller** (when in
   dist-mode **load**) decides to send more tests to a node when a test
   completes, using some heuristics such as test durations and how many
   tests each **worker** still has to run.

9. When the **controller** has no more pending tests it will send a
   “shutdown” signal to all **workers**, which will then run their
   remaining tests to completion and shut down. At this point the
   **controller** will sit waiting for **workers** to shut down, still
   processing events such as ``pytest_runtest_logreport``.

FAQ
---

**Question**: Why does each worker do its own collection, as opposed to having the
controller collect once and distribute from that collection to the
workers?

If collection was performed by controller then it would have to
serialize collected items to send them through the wire, as workers live
in another process. The problem is that test items are not easily
(impossible?) to serialize, as they contain references to the test
functions, fixture managers, config objects, etc. Even if one manages to
serialize it, it seems it would be very hard to get it right and easy to
break by any small change in pytest.
