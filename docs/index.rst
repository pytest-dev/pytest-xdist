pytest-xdist
============

The `pytest-xdist`_ plugin extends pytest with new test execution modes, the most used being distributing
tests across multiple CPUs to speed up test execution::

    pytest -n auto

With this call, pytest will spawn a number of workers processes equal to the number of available CPUs, and distribute
the tests randomly across them.

.. note::
    Due to how pytest-xdist is implemented, the ``-s/--capture=no`` option does not work.


Installation
------------

Install the plugin with::

    pip install pytest-xdist


To use ``psutil`` for detection of the number of CPUs available, install the ``psutil`` extra::

    pip install pytest-xdist[psutil]

Features
--------

* Test run :ref:`parallelization`: tests can be executed across  multiple CPUs or hosts.
  This allows to speed up development or to use special resources of :ref:`remote machines`.

* ``--looponfail``: run your tests repeatedly in a subprocess.  After each run
  pytest waits until a file in your project changes and then re-runs
  the previously failing tests.  This is repeated until all tests pass
  after which again a full run is performed (DEPRECATED).

* :ref:`Multi-Platform` coverage: you can specify different Python interpreters
  or different platforms and run tests in parallel on all of them.

  Before running tests remotely, ``pytest`` efficiently "rsyncs" your
  program source code to the remote place.
  You may specify different Python versions and interpreters. It does not
  installs/synchronize dependencies however.

  **Note**: this mode exists mostly for backward compatibility, as modern development
  relies on continuous integration for multi-platform testing.



.. toctree::
    :maxdepth: 2
    :caption: Contents:

    distribution
    subprocess
    remote
    crash
    how-to
    how-it-works
    known-limitations
    changelog
