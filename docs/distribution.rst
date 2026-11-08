.. _parallelization:

Running tests across multiple CPUs
==================================

To send tests to multiple CPUs, use the ``-n`` (or ``--numprocesses``) option::

    pytest -n auto

This can lead to considerable speed ups, especially if your test suite takes a
noticeable amount of time.

With ``-n auto``, pytest-xdist will use as many processes as your computer
has physical CPU cores.

Use ``-n logical`` to use the number of *logical* CPU cores rather than
physical ones. This currently requires either Python 3.13 or higher, or the
`psutil <https://pypi.org/project/psutil/>`__ package to be installed. If
neither method is available or if they all fail to determine the number of
logical CPUs, fall back to ``-n auto`` behavior.

Pass a number, e.g. ``-n 8``, to specify the number of processes explicitly.

Use ``-n 0`` to disable xdist and run all tests in the main process.

To specify a different meaning for ``-n auto`` and ``-n logical`` for your
tests, you can:

* Set the environment variable ``PYTEST_XDIST_AUTO_NUM_WORKERS`` to the
  desired number of processes. This is specific to xdist.

  Alternatively, use the standard ``-X cpu_count`` option to the Python
  interpreter or set the environment variable ``PYTHON_CPU_COUNT`` to affect
  the entire Python process, as documented for Python 3.13. xdist honors
  these settings even on Python 3.12 and lower.

* Implement the ``pytest_xdist_auto_num_workers``
  `pytest hook <https://docs.pytest.org/en/latest/how-to/writing_plugins.html>`__
  (a ``pytest_xdist_auto_num_workers(config)`` function in e.g. ``conftest.py``)
  that returns the number of processes to use.
  The hook can use ``config.option.numprocesses`` to determine if the user
  asked for ``"auto"`` or ``"logical"``, and it can return ``None`` to fall
  back to the default.

If both the hook and overrides are specified, the hook takes priority over
the ``PYTEST_XDIST_AUTO_NUM_WORKERS`` environment variable, which in turn
takes priority over the ``-X cpu_count`` option, which in turn takes
priority over the ``PYTHON_CPU_COUNT`` environment variable.


Parallelization can be configured further with these options:

* ``--maxprocesses=maxprocesses``: limit the maximum number of workers to
  process the tests.

* ``--max-worker-restart``: maximum number of workers that can be restarted
  when crashed (set to zero to disable this feature).

* ``--ramp=DURATION``: gradually start worker test execution over a duration.
  Workers still start and collect tests normally, but each worker waits before
  its first test according to its position in the worker pool. The duration is
  specified in seconds by default and also accepts ``s``, ``m``, and ``h``
  suffixes, for example ``--ramp=10s`` or ``--ramp=5m``.

The test distribution algorithm is configured with the ``--dist`` command-line option:

.. _distribution modes:

* ``--dist load`` **(default)**: Sends pending tests to any worker that is
  available, without any guaranteed order. Scheduling can be fine-tuned with
  the `--maxschedchunk` option, see output of `pytest --help`.

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
  tests with same ``xdist_group`` name run in the same worker. If a test has
  multiple groups, they will be joined together into a new group,
  the order of the marks doesn't matter. This works along with marks from fixtures
  and from the pytestmark global variable.

  .. code-block:: python

      @pytest.mark.xdist_group(name="group1")
      def test1():
          pass


      class TestA:
          @pytest.mark.xdist_group("group1")
          def test2():
              pass

  This will make sure ``test1`` and ``TestA::test2`` will run in the same worker.

  .. code-block:: python

      @pytest.fixture(
          scope="session",
          params=[
              pytest.param(
                  "chrome",
                  marks=pytest.mark.xdist_group("chrome"),
              ),
              pytest.param(
                  "firefox",
                  marks=pytest.mark.xdist_group("firefox"),
              ),
              pytest.param(
                  "edge",
                  marks=pytest.mark.xdist_group("edge"),
              ),
          ],
      )
      def setup_container():
          pass


      @pytest.mark.xdist_group(name="data-store")
      def test_data_store(setup_container):
          ...

  This will generate 3 new groups: ``chrome_data-store``, ``data-store_firefox`` and ``data-store_edge`` (the markers are lexically sorted before being merged together).

  Tests without the ``xdist_group`` mark are distributed normally as in the ``--dist=load`` mode.

* ``--dist worksteal``: Initially, tests are distributed evenly among all
  available workers. When a worker completes most of its assigned tests and
  doesn't have enough tests to continue (currently, every worker needs at least
  two tests in its queue), an attempt is made to reassign ("steal") a portion
  of tests from some other worker's queue. The results should be similar to
  the ``load`` method, but ``worksteal`` should handle tests with significantly
  differing duration better, and, at the same time, it should provide similar
  or better reuse of fixtures.

* ``--dist no``: The normal pytest execution mode, runs one test at a time (no distribution at all).

Experimental preloaded workers
------------------------------

On Linux and macOS, ``pytest -n 4 --worker-start-method=forkserver tests/unit``
starts a separate interpreter which prepares pytest's configuration and imports
initial conftest files once, then forks workers from that interpreter. Install
``pytest-xdist[psutil]`` to enable this mode. The default remains ``popen``.

Each worker inherits the prepared configuration and imports, but runs its own
configuration hooks, collection, fixtures and test execution. Only initial
conftest files are preloaded: pass the relevant test directory explicitly.
Nested conftest files discovered during collection still load in each worker.
The controller also imports its initial conftest files as usual.

During preload, ``PYTEST_XDIST_PRELOAD=1`` is set and no worker identity exists.
Code which reads a PID or worker identity at import time must instead do so in a
fixture or a worker configuration hook. Initial argument parsing and plugin
registration happen before the fork, including hooks such as
``pytest_addoption`` and ``pytest_load_initial_conftests``.

Preloaded code must be safe to fork. Create connections, event loops, thread
pools and other process-owned resources in worker fixtures, rather than during
imports. xdist rejects a preload which leaves multiple native threads, but
this check cannot certify arbitrary libraries as fork-safe. Set any native
library thread limits in the environment before invoking pytest. On macOS,
CoreFoundation, Cocoa and other system libraries can be unsafe after fork even
when Python appears single-threaded. This mode is explicitly experimental on
both platforms.

The Python standard random generator is handled by Python's fork machinery;
third-party random generators may inherit identical state. Seed these explicitly
in worker fixtures where independent streams are required. Preloaded objects
are frozen out of cyclic GC to preserve shared pages until worker exit.

Only plain local popen specifications and the standard xdist remote module are
supported. Remote hosts, proxy gateways and alternate interpreters are rejected.
Worker crashes are replaced from the original preload process. Collection and
all existing distribution modes keep their usual worker protocol.
