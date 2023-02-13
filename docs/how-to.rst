How-tos
-------

This section show cases how to accomplish some specialized tasks with ``pytest-xdist``.

Identifying the worker process during a test
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*New in version 1.15.*

If you need to determine the identity of a worker process in
a test or fixture, you may use the ``worker_id`` fixture to do so:

.. code-block:: python

    @pytest.fixture()
    def user_account(worker_id):
        """use a different account in each xdist worker"""
        return "account_%s" % worker_id

When ``xdist`` is disabled (running with ``-n0`` for example), then
``worker_id`` will return ``"master"``.

Worker processes also have the following environment variables
defined:

.. envvar:: PYTEST_XDIST_WORKER

The name of the worker, e.g., ``"gw2"``.

.. envvar:: PYTEST_XDIST_WORKER_COUNT

The total number of workers in this session, e.g., ``"4"`` when ``-n 4`` is given in the command-line.

The information about the worker_id in a test is stored in the ``TestReport`` as
well, under the ``worker_id`` attribute.

Since version 2.0, the following functions are also available in the ``xdist`` module:


.. autofunction:: xdist.is_xdist_worker
.. autofunction:: xdist.is_xdist_controller
.. autofunction:: xdist.is_xdist_master
.. autofunction:: xdist.get_xdist_worker_id

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
        """create a unique database for this particular test run"""
        database_url = f"psql://myapp-{testrun_uid}"

        with Semaphore(f"/{testrun_uid}-lock", flags=O_CREAT, initial_value=1):
            if not database_exists(database_url):
                create_database(database_url)


    @pytest.fixture()
    def db(testrun_uid):
        """retrieve unique database"""
        database_url = f"psql://myapp-{testrun_uid}"
        return database_get_instance(database_url)


Additionally, during a test run, the following environment variable is defined:

.. envvar:: PYTEST_XDIST_TESTRUNUID

The unique id of the test run.

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


Creating one log file for each worker
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To create one log file for each worker with ``pytest-xdist``, you can leverage :envvar:`PYTEST_XDIST_WORKER`
to generate a unique filename for each worker.

Example:

.. code-block:: python

    # content of conftest.py
    def pytest_configure(config):
        worker_id = os.environ.get("PYTEST_XDIST_WORKER")
        if worker_id is not None:
            logging.basicConfig(
                format=config.getini("log_file_format"),
                filename=f"tests_{worker_id}.log",
                level=config.getini("log_file_level"),
            )


When running the tests with ``-n3``, for example, three files will be created in the current directory:
``tests_gw0.log``, ``tests_gw1.log`` and ``tests_gw2.log``.
