Running tests in a Python subprocess
====================================

To instantiate a ``python3.9`` subprocess and send tests to it, you may type::

    pytest -d --tx popen//python=python3.9

This will start a subprocess which is run with the ``python3.9``
Python interpreter, found in your system binary lookup path.

If you prefix the --tx option value like this::

    --tx 3*popen//python=python3.9

then three subprocesses would be created and tests
will be load-balanced across these three processes.
