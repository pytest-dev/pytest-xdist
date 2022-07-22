Known limitations
=================

pytest-xdist has some limitations that may be supported in pytest but can't be supported in pytest-xdist.

Order and amount of test must be consistent
-------------------------------------------

Is is not possible to have tests that differ in order or their amount across workers.

This is especially true with ``pytest.mark.parametrize``, when values are produced with sets or other unordered iterables/generators.


Example:

.. code-block:: python

    import pytest

    @pytest.mark.parametrize("param", {"a","b"})
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
