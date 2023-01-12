Known limitations
=================

pytest-xdist has some limitations that may be supported in pytest but can't be supported in pytest-xdist.

Order and amount of test must be consistent
-------------------------------------------

It is not possible to have tests that differ in order or their amount across workers.

This is especially true with ``pytest.mark.parametrize``, when values are produced with sets or other unordered iterables/generators.


Example:

.. code-block:: python

    import pytest


    @pytest.mark.parametrize("param", {"a", "b"})
    def test_pytest_parametrize_unordered(param):
        pass

In the example above, the fact that ``set`` are not necessarily ordered can cause different workers
to collect tests in different order, which will throw an error.

Workarounds
~~~~~~~~~~~

A solution to this is to guarantee that the parametrized values have the same order.

Some solutions:

* Convert your sequence to a ``list``.

  .. code-block:: python

    import pytest


    @pytest.mark.parametrize("param", ["a", "b"])
    def test_pytest_parametrize_unordered(param):
        pass

* Sort your sequence, guaranteeing order.

  .. code-block:: python

    import pytest


    @pytest.mark.parametrize("param", sorted({"a", "b"}))
    def test_pytest_parametrize_unordered(param):
        pass

Output (stdout and stderr) from workers
---------------------------------------

The ``-s``/``--capture=no`` option is meant to disable pytest capture, so users can then see stdout and stderr output in the terminal from tests and application code in real time.

However, this option does not work with ``pytest-xdist`` because `execnet <https://github.com/pytest-dev/execnet>`__ the underlying library used for communication between master and workers, does not support transferring stdout/stderr from workers.

Currently, there are no plans to support this in ``pytest-xdist``.

Debugging
~~~~~~~~~

This also means that debugging using PDB (or any other debugger that wants to use standard I/O) will not work. The ``--pdb`` option is disabled when distributing tests with ``pytest-xdist`` for this reason.

It is generally likely best to use ``pytest-xdist`` to find failing tests and then debug them without distribution; however, if you need to debug from within a worker process (for example, to address failures that only happen when running tests concurrently), remote debuggers (for example, `python-remote-pdb <https://github.com/ionelmc/python-remote-pdb>`__ or `python-web-pdb <https://github.com/romanvm/python-web-pdb>`__) have been reported to work for this purpose.
