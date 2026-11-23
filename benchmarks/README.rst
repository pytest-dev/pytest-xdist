Fast-test benchmark
===================

Run this opt-in benchmark to compare pytest-xdist overhead on fast, passing
tests. The script uses the pytest, pytest-xdist, and execnet installed in the
Python environment you invoke. Regular CI does not run the benchmark.

From a checkout, install it into your environment and run the script::

    python -m pip install -e .
    python benchmarks/fast_tests.py --label before > before.json

The default workloads each generate 3,000 passing test cases. The ``noop``
workload has an empty test body, ``busy`` runs a fixed Python loop in every test,
and ``mixed`` runs that loop in every tenth test. The actual loop duration
depends on the interpreter and hardware. Use ``--busy-iterations`` to set its
length and hold it fixed across the runs you compare.

For each repetition, the script shuffles the workload and worker-count
combinations with a seeded random generator and starts a fresh pytest
process for each combination. The default is five repetitions with
``-n 0`` (serial), ``-n 1``, ``-n 2``, and ``-n 4`` using load scheduling.
Each process uses a generated pytest configuration and explicitly loads
xdist with third-party plugin autoloading disabled. Run
``python benchmarks/fast_tests.py --help`` for the options.

The JSON records the configuration, Python version, installed distribution
versions, xdist source path, the individual samples in execution order, and a
median and range for each workload and worker count.

* Wall time includes process startup, collection, test execution, and shutdown.
* Controller CPU time is the CPU time of the pytest process across all its
  threads, measured from before importing pytest until pytest returns. For
  ``-n 0``, this includes running the tests in that process.
* Total CPU time comes from the operating system's reaped child process
  accounting. On Unix systems that propagate worker usage to the controller,
  this includes both the controller and its reaped workers. It is ``null`` if
  Python's ``resource`` module is unavailable.

To compare revisions, run the same script with the same options, interpreter,
and dependency versions on the same machine. Install each checkout into its
own environment or set ``PYTHONPATH`` to the other checkout's ``src`` directory.
When overriding the source this way, check ``xdist_source`` and use ``--label``
to record the revision because the installed version metadata still refers to
the installed distribution. Alternate revisions between benchmark invocations
and compare samples for the same workload and worker count. The range indicates
run-to-run variation, and the script makes no timing assertions.
