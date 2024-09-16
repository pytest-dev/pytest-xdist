# Testing pytest-xdist Scheduler Custumization
- Run with `python -m pytest test.py` to run tests
- Run with `python -m pytest test.py -n <max worker count> --dist customgroup --junit-xml results.xml -v` to use new scheduler + report to xml and have verbose terminal output
    - Verbose terminal output is semi-required when using customgroup. It allows the user to confirm the correct tests are running with the correct number of processes.

## Notes:
- Install local pytest with `python -m pip install .` or `python -m pip install -e .`
    - When ran from root of `pytest-xdist` repository

## Using Customgroup
- Add pytest mark `xdist_custom(name="<group_name>_<num_workers>")` to tests
    - Tests without this marking will use the maximum worker count specified by `-n` argument
- Add `xdist_custom` to `pytest.ini` to avoid warnings about unregistered marks
- Run tests as detailed above
