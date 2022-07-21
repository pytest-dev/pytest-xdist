Known limitations
-----------------
pytest-xdist has some limitations that may be supported in pytest but can't be supported in pytest-xdist.

Order and amount of test must be consistent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Is is not possible to have tests that differ in order or their amount across workers.

This is especially true with ``pytest.mark.parametrize``.
When parametrize is used with set or other unordered iterable-like/generator pytest-xdist fails.


Example
.. code-block:: python
    import pytest

    @pytest.mark.parametrize("param",{"a","b"})
    def test_pytest_parametrize_unordered(param):
        pass

In the example above, the fact that ``set``s are not necessarily ordered can cause different workers
to collect tests in different order, which will throw an error.

Quick workarounds to ordering limitation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A solution to this is to guarantee that the parametrized values have the same order.

There are two simple solution:
# to convert your set to array.
# sort your set (your items must be sortable)

Array approach
.. code-block:: python

    import pytest

    @pytest.mark.parametrize("param", ["a","b"])
    def test_pytest_parametrize_unordered(param):
        pass

Sorted approach
.. code-block:: python

    import pytest

    @pytest.mark.parametrize("param", sorted({"a","b"}))
    def test_pytest_parametrize_unordered(param):
        pass
