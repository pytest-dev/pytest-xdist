pytest-xdist 3.2.0 (2023-02-07)
===============================

Improved Documentation
----------------------

- `#863 <https://github.com/pytest-dev/pytest-xdist/issues/863>`_: Document limitations for debugging due to standard I/O of workers not being forwarded. Also, mention remote debugging as a possible workaround.


Features
--------

- `#855 <https://github.com/pytest-dev/pytest-xdist/issues/855>`_: Users can now configure ``load`` scheduling precision using ``--maxschedchunk`` command
  line option.

- `#858 <https://github.com/pytest-dev/pytest-xdist/issues/858>`_: New ``worksteal`` scheduler, based on the idea of `work stealing <https://en.wikipedia.org/wiki/Work_stealing>`_. It's similar to ``load`` scheduler, but it should handle tests with significantly differing duration better, and, at the same time, it should provide similar or better reuse of fixtures.


Trivial Changes
---------------

- `#870 <https://github.com/pytest-dev/pytest-xdist/issues/870>`_: Make the tests pass even when ``$PYTEST_XDIST_AUTO_NUM_WORKERS`` is set.


pytest-xdist 3.1.0 (2022-12-01)
===============================

Features
--------

- `#789 <https://github.com/pytest-dev/pytest-xdist/issues/789>`_: Users can now set a default distribution mode in their configuration file:

  .. code-block:: ini

      [pytest]
      addopts = --dist loadscope

- `#842 <https://github.com/pytest-dev/pytest-xdist/issues/842>`_: Python 3.11 is now officially supported.


Removals
--------

- `#842 <https://github.com/pytest-dev/pytest-xdist/issues/842>`_: Python 3.6 is no longer supported.


pytest-xdist 3.0.2 (2022-10-25)
===============================

Bug Fixes
---------

- `#813 <https://github.com/pytest-dev/pytest-xdist/issues/813>`_: Cancel shutdown when a crashed worker is restarted.


Deprecations
------------

- `#825 <https://github.com/pytest-dev/pytest-xdist/issues/825>`_: The ``--rsyncdir`` command line argument and ``rsyncdirs`` config variable are deprecated.

  The rsync feature will be removed in pytest-xdist 4.0.

- `#826 <https://github.com/pytest-dev/pytest-xdist/issues/826>`_: The ``--looponfail`` command line argument and ``looponfailroots`` config variable are deprecated.

  The loop-on-fail feature will be removed in pytest-xdist 4.0.


Improved Documentation
----------------------

- `#791 <https://github.com/pytest-dev/pytest-xdist/issues/791>`_: Document the ``pytest_xdist_auto_num_workers`` hook.

- `#796 <https://github.com/pytest-dev/pytest-xdist/issues/796>`_: Added known limitations section to documentation.

- `#829 <https://github.com/pytest-dev/pytest-xdist/issues/829>`_: Document the ``-n logical`` option.


Features
--------

- `#792 <https://github.com/pytest-dev/pytest-xdist/issues/792>`_: The environment variable ``PYTEST_XDIST_AUTO_NUM_WORKERS`` can now be used to
  specify the default for ``-n auto`` and ``-n logical``.

- `#812 <https://github.com/pytest-dev/pytest-xdist/issues/812>`_: Partially restore old initial batch distribution algorithm in ``LoadScheduling``.

  pytest orders tests for optimal sequential execution - i. e. avoiding
  unnecessary setup and teardown of fixtures. So executing tests in consecutive
  chunks is important for optimal performance.

  In v1.14, initial test distribution in ``LoadScheduling`` was changed to
  round-robin, optimized for the corner case, when the number of tests is less
  than ``2 * number of nodes``. At the same time, it became worse for all other
  cases.

  For example: if some tests use some "heavy" fixture, and these tests fit into
  the initial batch, with round-robin distribution the fixture will be created
  ``min(n_tests, n_workers)`` times, no matter how many other tests there are.

  With the old algorithm (before v1.14), if there are enough tests not using
  the fixture, the fixture was created only once.

  So restore the old behavior for typical cases where the number of tests is
  much greater than the number of workers (or, strictly speaking, when there
  are at least 2 tests for every node).


Removals
--------

- `#468 <https://github.com/pytest-dev/pytest-xdist/issues/468>`_: The ``--boxed`` command-line option has been removed. If you still need this functionality, install `pytest-forked <https://pypi.org/project/pytest-forked>`__ separately.


Trivial Changes
---------------

- `#468 <https://github.com/pytest-dev/pytest-xdist/issues/468>`_: The ``py`` dependency has been dropped.

- `#822 <https://github.com/pytest-dev/pytest-xdist/issues/822>`_: Replace internal usage of ``py.log`` with a custom solution (but with the same interface).

- `#823 <https://github.com/pytest-dev/pytest-xdist/issues/823>`_: Remove usage of ``py._pydir`` as an rsync candidate.

- `#824 <https://github.com/pytest-dev/pytest-xdist/issues/824>`_: Replace internal usages of ``py.path.local`` by ``pathlib.Path``.


pytest-xdist 2.5.0 (2021-12-10)
===============================

Deprecations and Removals
-------------------------

- `#468 <https://github.com/pytest-dev/pytest-xdist/issues/468>`_: The ``--boxed`` command line argument is deprecated. Install `pytest-forked <https://pypi.org/project/pytest-forked>`__ and use ``--forked`` instead. pytest-xdist 3.0.0 will remove the ``--boxed`` argument and ``pytest-forked`` dependency.


Features
--------

- `#722 <https://github.com/pytest-dev/pytest-xdist/issues/722>`_: Full compatibility with pytest 7 - no deprecation warnings or use of legacy features.

- `#733 <https://github.com/pytest-dev/pytest-xdist/issues/733>`_: New ``--dist=loadgroup`` option, which ensures all tests marked with ``@pytest.mark.xdist_group`` run in the same session/worker. Other tests run distributed as in ``--dist=load``.


Trivial Changes
---------------

- `#708 <https://github.com/pytest-dev/pytest-xdist/issues/708>`_: Use ``@pytest.hookspec`` decorator to declare hook options in ``newhooks.py`` to avoid warnings in ``pytest 7.0``.

- `#719 <https://github.com/pytest-dev/pytest-xdist/issues/719>`_: Use up-to-date ``setup.cfg``/``pyproject.toml`` packaging setup.

- `#720 <https://github.com/pytest-dev/pytest-xdist/issues/720>`_: Require pytest>=6.2.0.

- `#721 <https://github.com/pytest-dev/pytest-xdist/issues/721>`_: Started using type annotations and mypy checking internally. The types are incomplete and not published.


pytest-xdist 2.4.0 (2021-09-20)
===============================

Features
--------

- `#696 <https://github.com/pytest-dev/pytest-xdist/issues/696>`_: On Linux, the process title now changes to indicate the current worker state (running/idle).

  Depends on the `setproctitle <https://pypi.org/project/setproctitle/>`__ package, which can be installed with ``pip install pytest-xdist[setproctitle]``.

- `#704 <https://github.com/pytest-dev/pytest-xdist/issues/704>`_: Add support for Python 3.10.


pytest-xdist 2.3.0 (2021-06-16)
===============================

Deprecations and Removals
-------------------------

- `#654 <https://github.com/pytest-dev/pytest-xdist/issues/654>`_: Python 3.5 is no longer supported.


Features
--------

- `#646 <https://github.com/pytest-dev/pytest-xdist/issues/646>`_: Add ``--numprocesses=logical`` flag, which automatically uses the number of logical CPUs available, instead of physical CPUs with ``auto``.

  This is very useful for test suites which are not CPU-bound.

- `#650 <https://github.com/pytest-dev/pytest-xdist/issues/650>`_: Added new ``pytest_handlecrashitem`` hook to allow handling and rescheduling crashed items.


Bug Fixes
---------

- `#421 <https://github.com/pytest-dev/pytest-xdist/issues/421>`_: Copy the parent process sys.path into local workers, to work around execnet's python -c adding the current directory to sys.path.

- `#638 <https://github.com/pytest-dev/pytest-xdist/issues/638>`_: Fix issue caused by changing the branch name of the pytest repository.


Trivial Changes
---------------

- `#592 <https://github.com/pytest-dev/pytest-xdist/issues/592>`_: Replace master with controller where ever possible.

- `#643 <https://github.com/pytest-dev/pytest-xdist/issues/643>`_: Use 'main' to refer to pytest default branch in tox env names.


pytest-xdist 2.2.1 (2021-02-09)
===============================

Bug Fixes
---------

- `#623 <https://github.com/pytest-dev/pytest-xdist/issues/623>`_: Gracefully handle the pending deprecation of Node.fspath by using config.rootpath for topdir.


pytest-xdist 2.2.0 (2020-12-14)
===============================

Features
--------

- `#608 <https://github.com/pytest-dev/pytest-xdist/issues/608>`_: Internal errors in workers are now propagated to the master node.


pytest-xdist 2.1.0 (2020-08-25)
===============================

Features
--------

- `#585 <https://github.com/pytest-dev/pytest-xdist/issues/585>`_: New ``pytest_xdist_auto_num_workers`` hook can be implemented by plugins or ``conftest.py`` files to control the number of workers when ``--numprocesses=auto`` is given in the command-line.


Trivial Changes
---------------

- `#585 <https://github.com/pytest-dev/pytest-xdist/issues/585>`_: ``psutil`` has proven to make ``pytest-xdist`` installation in certain platforms and containers problematic, so to use it for automatic number of CPUs detection users need to install the ``psutil`` extra::

      pip install pytest-xdist[psutil]


pytest-xdist 2.0.0 (2020-08-12)
===============================

Deprecations and Removals
-------------------------

- `#541 <https://github.com/pytest-dev/pytest-xdist/issues/541>`_: Drop backward-compatibility "slave" aliases related to worker nodes.  We deliberately moved away from this terminology years ago, and it seems like the right time to finish the deprecation and removal process.

- `#569 <https://github.com/pytest-dev/pytest-xdist/issues/569>`_: ``pytest-xdist`` no longer supports Python 2.7.


Features
--------

- `#504 <https://github.com/pytest-dev/pytest-xdist/issues/504>`_: New functions ``xdist.is_xdist_worker``, ``xdist.is_xdist_master``, ``xdist.get_xdist_worker_id``, to easily identify the current node.


Bug Fixes
---------

- `#471 <https://github.com/pytest-dev/pytest-xdist/issues/471>`_: Fix issue with Rsync reporting in quiet mode.

- `#553 <https://github.com/pytest-dev/pytest-xdist/issues/553>`_: When using ``-n auto``, count the number of physical CPU cores instead of logical ones.


Trivial Changes
---------------

- `#541 <https://github.com/pytest-dev/pytest-xdist/issues/541>`_: ``pytest-xdist`` now requires ``pytest>=6.0``.


pytest-xdist 1.34.0 (2020-07-27)
================================

Features
--------

- `#549 <https://github.com/pytest-dev/pytest-xdist/issues/549>`_: Make ``--pdb`` imply ``--dist no``, as the two options cannot really work together at the moment.


Bug Fixes
---------

- `#478 <https://github.com/pytest-dev/pytest-xdist/issues/478>`_: Fix regression with duplicated arguments via $PYTEST_ADDOPTS in 1.30.0.

- `#558 <https://github.com/pytest-dev/pytest-xdist/issues/558>`_: Fix ``rsyncdirs`` usage with pytest 6.0.

- `#562 <https://github.com/pytest-dev/pytest-xdist/issues/562>`_: Do not trigger the deprecated ``pytest_warning_captured`` in pytest 6.0+.


pytest-xdist 1.33.0 (2020-07-09)
================================

Features
--------

- `#554 <https://github.com/pytest-dev/pytest-xdist/issues/554>`_: Fix warnings support for upcoming pytest 6.0.


Trivial Changes
---------------

- `#548 <https://github.com/pytest-dev/pytest-xdist/issues/548>`_: SCM and CI files are no longer included in the source distribution.


pytest-xdist 1.32.0 (2020-05-03)
================================

Deprecations and Removals
-------------------------

- `#475 <https://github.com/pytest-dev/pytest-xdist/issues/475>`_: Drop support for EOL Python 3.4.


Features
--------

- `#524 <https://github.com/pytest-dev/pytest-xdist/issues/524>`_: Add `testrun_uid` fixture. This is a shared value that uniquely identifies a test run among all workers.
  This also adds a `PYTEST_XDIST_TESTRUNUID` environment variable that is accessible within a test as well as a command line option `--testrunuid` to manually set the value from outside.


pytest-xdist 1.31.0 (2019-12-19)
================================

Features
--------

- `#486 <https://github.com/pytest-dev/pytest-xdist/issues/486>`_: Add support for Python 3.8.


Bug Fixes
---------

- `#491 <https://github.com/pytest-dev/pytest-xdist/issues/491>`_: Fix regression that caused custom plugin command-line arguments to be discarded when using ``--tx`` mode.



pytest-xdist 1.30.0 (2019-10-01)
================================

Features
--------

- `#448 <https://github.com/pytest-dev/pytest-xdist/issues/448>`_: Initialization between workers and master nodes is now more consistent, which fixes a number of
  long-standing issues related to startup with the ``-c`` option.

  Issues:

  * `#6 <https://github.com/pytest-dev/pytest-xdist/issues/6>`__: Poor interaction between ``-n#`` and ``-c X.cfg``
  * `#445 <https://github.com/pytest-dev/pytest-xdist/issues/445>`__: pytest-xdist is not reporting the same nodeid as pytest does

  This however only works with **pytest 5.1 or later**, as it required changes in pytest itself.


Bug Fixes
---------

- `#467 <https://github.com/pytest-dev/pytest-xdist/issues/467>`_: Fix crash issues related to running xdist with the terminal plugin disabled.


pytest-xdist 1.29.0 (2019-06-14)
================================

Features
--------

- `#226 <https://github.com/pytest-dev/pytest-xdist/issues/226>`_: ``--max-worker-restart`` now assumes a more reasonable value (4 times the number of
  nodes) when not given explicitly. This prevents test suites from running forever when the suite crashes during collection.

- `#435 <https://github.com/pytest-dev/pytest-xdist/issues/435>`_: When the test session is interrupted due to running out of workers, the reason is shown in the test summary
  for easier viewing.

- `#442 <https://github.com/pytest-dev/pytest-xdist/issues/442>`_: Compatibility fix for upcoming pytest 5.0: ``session.exitstatus`` is now an ``IntEnum`` object.


Bug Fixes
---------

- `#435 <https://github.com/pytest-dev/pytest-xdist/issues/435>`_: No longer show an internal error when we run out of workers due to crashes.


pytest-xdist 1.28.0 (2019-04-02)
================================

Features
--------

- `#426 <https://github.com/pytest-dev/pytest-xdist/issues/426>`_: ``pytest-xdist`` now uses the new ``pytest_report_to_serializable`` and ``pytest_report_from_serializable``
  hooks from ``pytest 4.4`` (still experimental). This will make report serialization more reliable and
  extensible.

  This also means that ``pytest-xdist`` now requires ``pytest>=4.4``.


pytest-xdist 1.27.0 (2019-02-15)
================================

Features
--------

- `#374 <https://github.com/pytest-dev/pytest-xdist/issues/374>`_: The new ``pytest_xdist_getremotemodule`` hook allows overriding the module run on remote nodes.

- `#415 <https://github.com/pytest-dev/pytest-xdist/issues/415>`_: Improve behavior of ``--numprocesses=auto`` to work well with ``--pdb`` option.


pytest-xdist 1.26.1 (2019-01-28)
================================

Bug Fixes
---------

- `#406 <https://github.com/pytest-dev/pytest-xdist/issues/406>`_: Do not implement deprecated ``pytest_logwarning`` hook in pytest versions where it is deprecated.


pytest-xdist 1.26.0 (2019-01-11)
================================

Features
--------

- `#376 <https://github.com/pytest-dev/pytest-xdist/issues/376>`_: The current directory is no longer added ``sys.path`` for local workers, only for remote connections.

  This behavior is surprising because it makes xdist runs and non-xdist runs to potentially behave differently.


Bug Fixes
---------

- `#379 <https://github.com/pytest-dev/pytest-xdist/issues/379>`_: Warning attributes are checked to make sure they can be dumped prior to
  serializing the warning for submission to the master node.


pytest-xdist 1.25.0 (2018-12-12)
================================

Deprecations and Removals
-------------------------

- `#372 <https://github.com/pytest-dev/pytest-xdist/issues/372>`_: Pytest versions older than 3.6 are no longer supported.


Features
--------

- `#373 <https://github.com/pytest-dev/pytest-xdist/issues/373>`_: Node setup information is hidden when pytest is run in quiet mode to reduce noise on many-core machines.

- `#388 <https://github.com/pytest-dev/pytest-xdist/issues/388>`_: ``mainargv`` is made available in ``workerinput`` from the host's ``sys.argv``.

  This can be used via ``request.config.workerinput["mainargv"]``.


Bug Fixes
---------

- `#332 <https://github.com/pytest-dev/pytest-xdist/issues/332>`_: Fix report of module-level skips (``pytest.skip(reason, allow_module_level=True)``).

- `#378 <https://github.com/pytest-dev/pytest-xdist/issues/378>`_: Fix support for gevent monkeypatching

- `#384 <https://github.com/pytest-dev/pytest-xdist/issues/384>`_: pytest 4.1 support: ``ExceptionInfo`` API changes.

- `#390 <https://github.com/pytest-dev/pytest-xdist/issues/390>`_: pytest 4.1 support: ``pytest_logwarning`` hook removed.


pytest-xdist 1.24.1 (2018-11-09)
================================

Bug Fixes
---------

- `#349 <https://github.com/pytest-dev/pytest-xdist/issues/349>`_: Correctly handle warnings created with arguments that can't be serialized during the transfer from workers to master node.


pytest-xdist 1.24.0 (2018-10-18)
================================

Features
--------

- `#337 <https://github.com/pytest-dev/pytest-xdist/issues/337>`_: New ``--maxprocesses`` command-line option that limits the maximum number of workers when using ``--numprocesses=auto``.


Bug Fixes
---------

- `#351 <https://github.com/pytest-dev/pytest-xdist/issues/351>`_: Fix scheduling deadlock in case of inter-test locking.


pytest-xdist 1.23.2 (2018-09-28)
================================

Bug Fixes
---------

- `#344 <https://github.com/pytest-dev/pytest-xdist/issues/344>`_: Fix issue where Warnings could cause pytest to fail if they do not set the args attribute correctly.


pytest-xdist 1.23.1 (2018-09-25)
================================

Bug Fixes
---------

- `#341 <https://github.com/pytest-dev/pytest-xdist/issues/341>`_: Fix warnings transfer between workers and master node with pytest >= 3.8.


pytest-xdist 1.23.0 (2018-08-23)
================================

Features
--------

- `#330 <https://github.com/pytest-dev/pytest-xdist/issues/330>`_: Improve collection performance by reducing the number of events sent to ``master`` node.


pytest-xdist 1.22.5 (2018-07-27)
================================

Bug Fixes
---------

- `#321 <https://github.com/pytest-dev/pytest-xdist/issues/321>`_: Revert change that dropped support for ``pytest<3.4`` and require ``six``.

  This change caused problems in some installations, and was a mistaken
  in the first place as we should not change version requirements
  in bug-fix releases unless they fix an actual bug.


pytest-xdist 1.22.4 (2018-07-27)
================================

Bug Fixes
---------

- `#305 <https://github.com/pytest-dev/pytest-xdist/issues/305>`_: Remove last references to obsolete ``py.code``.

  Remove some unnecessary references to ``py.builtin``.

- `#316 <https://github.com/pytest-dev/pytest-xdist/issues/316>`_: Workaround cpu detection on Travis CI.


pytest-xdist 1.22.3 (2018-07-23)
================================

Bug Fixes
---------

- Fix issue of virtualized or containerized environments not reporting the number of CPUs correctly. (`#9 <https://github.com/pytest-dev/pytest-xdist/issues/9>`_)


Trivial Changes
---------------

- Make all classes subclass from ``object`` and fix ``super()`` call in ``LoadFileScheduling``; (`#297 <https://github.com/pytest-dev/pytest-xdist/issues/297>`_)


pytest-xdist 1.22.2 (2018-02-26)
================================

Bug Fixes
---------

- Add backward compatibility for ``slaveoutput`` attribute to
  ``WorkerController`` instances. (`#285
  <https://github.com/pytest-dev/pytest-xdist/issues/285>`_)


pytest-xdist 1.22.1 (2018-02-19)
================================

Bug Fixes
---------

- Fix issue when using ``loadscope`` or ``loadfile`` where tests would fail to
  start if the first scope had only one test. (`#257
  <https://github.com/pytest-dev/pytest-xdist/issues/257>`_)


Trivial Changes
---------------

- Change terminology used by ``pytest-xdist`` to *master* and *worker* in
  arguments and messages (for example ``--max-worker-reset``). (`#234
  <https://github.com/pytest-dev/pytest-xdist/issues/234>`_)


pytest-xdist 1.22.0 (2018-01-11)
================================

Features
--------

- Add support for the ``pytest_runtest_logfinish`` hook which will be released
  in pytest 3.4. (`#266
  <https://github.com/pytest-dev/pytest-xdist/issues/266>`_)


pytest-xdist 1.21.0 (2017-12-22)
================================

Deprecations and Removals
-------------------------

- Drop support for EOL Python 2.6. (`#259
  <https://github.com/pytest-dev/pytest-xdist/issues/259>`_)


Features
--------

- New ``--dist=loadfile`` option which load-distributes test to workers grouped
  by the file the tests live in. (`#242
  <https://github.com/pytest-dev/pytest-xdist/issues/242>`_)


Bug Fixes
---------

- Fix accidental mutation of test report during serialization causing longrepr
  string-ification to break. (`#241
  <https://github.com/pytest-dev/pytest-xdist/issues/241>`_)


pytest-xdist 1.20.1 (2017-10-05)
================================

Bug Fixes
---------

- Fix hang when all worker nodes crash and restart limit is reached (`#45
  <https://github.com/pytest-dev/pytest-xdist/issues/45>`_)

- Fix issue where the -n option would still run distributed tests when pytest
  was run with the --collect-only option (`#5
  <https://github.com/pytest-dev/pytest-xdist/issues/5>`_)


pytest-xdist 1.20.0 (2017-08-17)
================================

Features
--------

- ``xdist`` now supports tests to log results multiple times, improving
  integration with plugins which require it like `pytest-rerunfailures
  <https://github.com/gocept/pytest-rerunfailures>`_ and `flaky
  <https://pypi.python.org/pypi/flaky>`_. (`#206 <https://github.com/pytest-
  dev/pytest-xdist/issues/206>`_)


Bug Fixes
---------

- Fix issue where tests were being incorrectly identified if a worker crashed
  during the ``teardown`` stage of the test. (`#124 <https://github.com/pytest-
  dev/pytest-xdist/issues/124>`_)


pytest-xdist 1.19.1 (2017-08-10)
================================

Bug Fixes
---------

- Fix crash when transferring internal pytest warnings from workers to the
  master node. (`#214 <https://github.com/pytest-dev/pytest-
  xdist/issues/214>`_)


pytest-xdist 1.19.0 (2017-08-09)
================================

Deprecations and Removals
-------------------------

- ``--boxed`` functionality has been moved to a separate plugin, `pytest-forked
  <https://github.com/pytest-dev/pytest-forked>`_. This release now depends on
  `` pytest-forked`` and provides ``--boxed`` as a backward compatibility
  option. (`#1 <https://github.com/pytest-dev/pytest-xdist/issues/1>`_)


Features
--------

- New ``--dist=loadscope`` option: sends group of related tests to the same
  worker. Tests are grouped by module for test functions and by class for test
  methods. See ``README.rst`` for more information. (`#191 <https://github.com
  /pytest-dev/pytest-xdist/issues/191>`_)

- Warnings are now properly transferred from workers to the master node. (`#92
  <https://github.com/pytest-dev/pytest-xdist/issues/92>`_)


Bug Fixes
---------

- Fix serialization of native tracebacks (``--tb=native``). (`#196
  <https://github.com/pytest-dev/pytest-xdist/issues/196>`_)


pytest-xdist 1.18.2 (2017-07-28)
================================

Bug Fixes
---------

- Removal of unnecessary dependency on incorrect version of py. (`#105
  <https://github.com/pytest-dev/pytest-xdist/issues/105>`_)

- Fix bug in internal event-loop error handler in the master node. This bug
  would shadow the original errors making extremely hard/impossible for users
  to diagnose the problem properly. (`#175 <https://github.com/pytest-
  dev/pytest-xdist/issues/175>`_)


pytest-xdist 1.18.1 (2017-07-05)
================================

Bug Fixes
---------

- Fixed serialization of ``longrepr.sections`` during error reporting from
  workers. (`#171 <https://github.com/pytest-dev/pytest-xdist/issues/171>`_)

- Fix ``ReprLocal`` not being unserialized breaking --showlocals usages. (`#176
  <https://github.com/pytest-dev/pytest-xdist/issues/176>`_)


pytest-xdist 1.18.0 (2017-06-26)
================================

- ``pytest-xdist`` now requires ``pytest>=3.0.0``.

Features
--------

- Add long option `--numprocesses` as alternative for `-n`. (#168)


Bug Fixes
---------

- Fix serialization and deserialization dropping longrepr details. (#133)


pytest-xdist 1.17.1 (2017-06-10)
================================

Bug Fixes
---------

- Hot fix release reverting the change introduced by #124, unfortunately it
  broke a number of test suites so we are reversing this change while we
  investigate the problem. (#157)


Improved Documentation
----------------------

- Introduced ``towncrier`` for ``CHANGELOG`` management. (#154)

- Added ``HOWTORELEASE`` documentation. (#155)


1.17.0
------

- fix #124: xdist would mark test as complete after 'call' step. As a result,
  xdist could identify the wrong test as failing when test crashes at teardown.
  To address this issue, xdist now marks test as complete at teardown.

1.16.0
------

- ``pytest-xdist`` now requires pytest 2.7 or later.

- Add ``worker_id`` attribute in the TestReport

- new hook: ``pytest_xdist_make_scheduler(config, log)``, can return custom tests items
  distribution logic implementation. You can take a look at built-in ``LoadScheduling``
  and ``EachScheduling`` implementations. Note that required scheduler class public
  API may change in next ``pytest-xdist`` versions.

1.15.0
------

- new ``worker_id`` fixture, returns the id of the worker in a test or fixture.
  Thanks Jared Hellman for the PR.

- display progress during collection only when in a terminal, similar to pytest #1397 issue.
  Thanks Bruno Oliveira for the PR.

- fix internal error message when ``--maxfail`` is used (#62, #65).
  Thanks Collin RM Stocks and Bryan A. Jones for reports and Bruno Oliveira for the PR.


1.14
----

- new hook: ``pytest_xdist_node_collection_finished(node, ids)``, called when
  a worker has finished collection. Thanks Omer Katz for the request and
  Bruno Oliveira for the PR.

- fix README display on pypi

- fix #22: xdist now works if the internal tmpdir plugin is disabled.
  Thanks Bruno Oliveira for the PR.

- fix #32: xdist now works if looponfail or boxed are disabled.
  Thanks Bruno Oliveira for the PR.


1.13.1
-------

- fix a regression -n 0 now disables xdist again


1.13
-------------------------

- extended the tox matrix with the supported py.test versions

- split up the plugin into 3 plugin's
  to prepare the departure of boxed and looponfail.

  looponfail will be a part of core
  and forked boxed will be replaced
  with a more reliable primitive based on xdist

- conforming with new pytest-2.8 behavior of returning non-zero when all
  tests were skipped or deselected.

- new "--max-slave-restart" option that can be used to control maximum
  number of times pytest-xdist can restart slaves due to crashes. Thanks to
  Anatoly Bubenkov for the report and Bruno Oliveira for the PR.

- release as wheel

- "-n" option now can be set to "auto" for automatic detection of number
  of cpus in the host system. Thanks Suloev Dmitry for the PR.

1.12
-------------------------

- fix issue594: properly report errors when the test collection
  is random.  Thanks Bruno Oliveira.

- some internal test suite adaptation (to become forward
  compatible with the upcoming pytest-2.8)


1.11
-------------------------

- fix pytest/xdist issue485 (also depends on py-1.4.22):
  attach stdout/stderr on --boxed processes that die.

- fix pytest/xdist issue503: make sure that a node has usually
  two items to execute to avoid scoped fixtures to be torn down
  pre-maturely (fixture teardown/setup is "nextitem" sensitive).
  Thanks to Andreas Pelme for bug analysis and failing test.

- restart crashed nodes by internally refactoring setup handling
  of nodes.  Also includes better code documentation.
  Many thanks to Floris Bruynooghe for the complete PR.


1.10
-------------------------

- add glob support for rsyncignores, add command line option to pass
  additional rsyncignores. Thanks Anatoly Bubenkov.

- fix pytest issue382 - produce "pytest_runtest_logstart" event again
  in master. Thanks Aron Curzon.

- fix pytest issue419 by sending/receiving indices into the test
  collection instead of node ids (which are not necessarily unique
  for functions parametrized with duplicate values)

- send multiple "to test" indices in one network message to a slave
  and improve heuristics for sending chunks where the chunksize
  depends on the number of remaining tests rather than fixed numbers.
  This reduces the number of master -> node messages (but not the
  reverse direction)


1.9
-------------------------

- changed LICENSE to MIT

- fix duplicate reported test ids with --looponfailing
  (thanks Jeremy Thurgood)

- fix pytest issue41: re-run tests on all file changes, not just
  randomly select ones like .py/.c.

- fix pytest issue347: slaves running on top of Python3.2
  will set PYTHONDONTWRITEYBTECODE to 1 to avoid import concurrency
  bugs.

1.8
-------------------------

- fix pytest-issue93 - use the refined pytest-2.2.1 runtestprotocol
  interface to perform eager teardowns for test items.

1.7
-------------------------

- fix incompatibilities with pytest-2.2.0 (allow multiple
  pytest_runtest_logreport reports for a test item)

1.6
-------------------------

- terser collection reporting

- fix issue34 - distributed testing with -p plugin now works correctly

- fix race condition in looponfail mode where a concurrent file removal
  could cause a crash

1.5
-------------------------

- adapt to and require pytest-2.0 changes, rsyncdirs and rsyncignore can now
  only be specified in [pytest] sections of ini files, see "py.test -h"
  for details.
- major internal refactoring to match the pytest-2.0 event refactoring
  - perform test collection always at slave side instead of at the master
  - make python2/python3 bridging work, remove usage of pickling
- improve initial reporting by using line-rewriting
- remove all trailing whitespace from source

1.4
-------------------------

- perform distributed testing related reporting in the plugin
  rather than having dist-related code in the generic py.test
  distribution

- depend on execnet-1.0.7 which adds "env1:NAME=value" keys to
  gateway specification strings.

- show detailed gateway setup and platform information only when
  "-v" or "--verbose" is specified.

1.3
-------------------------

- fix --looponfailing - it would not actually run against the fully changed
  source tree when initial conftest files load application state.

- adapt for py-1.3.1's new --maxfailure option

1.2
-------------------------

- fix issue79: sessionfinish/teardown hooks are now called systematically
  on the slave side
- introduce a new data input/output mechanism to allow the master side
  to send and receive data from a slave.
- fix race condition in underlying pickling/unpickling handling
- use and require new register hooks facility of py.test>=1.3.0
- require improved execnet>=1.0.6 because of various race conditions
  that can arise in xdist testing modes.
- fix some python3 related pickling related race conditions
- fix PyPI description

1.1
-------------------------

- fix an indefinite hang which would wait for events although no events
  are pending - this happened if items arrive very quickly while
  the "reschedule-event" tried unconditionally avoiding a busy-loop
  and not schedule new work.

1.0
-------------------------

- moved code out of py-1.1.1 into its own plugin
- use a new, faster and more sensible model to do load-balancing
  of tests - now no magic "MAXITEMSPERHOST" is needed and load-testing
  works effectively even with very few tests.
- cleaned up termination handling
- make -x cause hard killing of test nodes to decrease wait time
  until the traceback shows up on first failure
