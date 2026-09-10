from xdist.scheduler.loadscope import LoadScopeScheduling


def test_split_scope_uses_module_boundary_for_colon_parameters():
    scheduler = LoadScopeScheduling.__new__(LoadScopeScheduling)

    assert (
        scheduler._split_scope("tests/test_example.py::test_ip[::1]")
        == "tests/test_example.py"
    )


def test_split_scope_keeps_class_scope():
    scheduler = LoadScopeScheduling.__new__(LoadScopeScheduling)

    assert (
        scheduler._split_scope("tests/test_example.py::TestExample::test_one[::1]")
        == "tests/test_example.py::TestExample"
    )
