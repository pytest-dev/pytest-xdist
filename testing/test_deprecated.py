import py

def test_dist_conftest_options(testdir):
    p1 = testdir.tmpdir.ensure("dir", 'p1.py')
    p1.dirpath("__init__.py").write("")
    p1.dirpath("conftest.py").write(py.code.Source("""
        import py
        from py.builtin import print_
        print_("importing conftest", __file__)
        Option = py.test.config.Option 
        option = py.test.config.addoptions("someopt", 
            Option('--someopt', action="store_true", 
                    dest="someopt", default=False))
        dist_rsync_roots = ['../dir']
        print_("added options", option)
        print_("config file seen from conftest", py.test.config)
    """))
    p1.write(py.code.Source("""
        import py
        from %s import conftest
        from py.builtin import print_
        def test_1(): 
            print_("config from test_1", py.test.config)
            print_("conftest from test_1", conftest.__file__)
            print_("test_1: py.test.config.option.someopt", py.test.config.option.someopt)
            print_("test_1: conftest", conftest)
            print_("test_1: conftest.option.someopt", conftest.option.someopt)
            assert conftest.option.someopt 
    """ % p1.dirpath().purebasename ))
    result = testdir.runpytest('-d', '--tx=popen', p1, '--someopt')
    assert result.ret == 0
    result.stderr.fnmatch_lines([
        "*Deprecation*pytest_addoptions*",
    ])
    result.stdout.fnmatch_lines([
        "*1 passed*", 
    ])
