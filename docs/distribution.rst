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
physical ones. This currently requires the `psutil <https://pypi.org/project/psutil/>`__ package to be installed;
if it is not or if it fails to determine the number of logical CPUs, fall back to ``-n auto`` behavior.

Pass a number, e.g. ``-n 8``, to specify the number of processes explicitly.

Use ``-n 0`` to disable xdist and run all tests in the main process.

To specify a different meaning for ``-n auto`` and ``-n logical`` for your
tests, you can:

* Set the environment variable ``PYTEST_XDIST_AUTO_NUM_WORKERS`` to the
  desired number of processes.

* Implement the ``pytest_xdist_auto_num_workers``
  `pytest hook <https://docs.pytest.org/en/latest/how-to/writing_plugins.html>`__
  (a ``pytest_xdist_auto_num_workers(config)`` function in e.g. ``conftest.py``)
  that returns the number of processes to use.
  The hook can use ``config.option.numprocesses`` to determine if the user
  asked for ``"auto"`` or ``"logical"``, and it can return ``None`` to fall
  back to the default.

If both the hook and environment variable are specified, the hook takes
priority.


Parallelization can be configured further with these options:

* ``--maxprocesses=maxprocesses``: limit the maximum number of workers to
  process the tests.

* ``--max-worker-restart``: maximum number of workers that can be restarted
  when crashed (set to zero to disable this feature).

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
