import py

@py.test.mark.skipif("not hasattr(os, 'fork')")
def test_functional_boxed(testdir):
    p1 = testdir.makepyfile("""
        import os
        def test_function():
            os.kill(os.getpid(), 15)
    """)
    result = testdir.runpytest(p1, "--boxed")
    result.stdout.fnmatch_lines([
        "*CRASHED*",
        "*1 failed*"
    ])

class TestOptionEffects:
    def test_boxed_option_default(self, testdir):
        tmpdir = testdir.tmpdir.ensure("subdir", dir=1)
        config = testdir.reparseconfig()
        config.initsession()
        assert not config.option.boxed
        py.test.importorskip("execnet")
        config = testdir.reparseconfig(['-d', tmpdir])
        config.initsession()
        assert not config.option.boxed

    def test_is_not_boxed_by_default(self, testdir):
        config = testdir.reparseconfig([testdir.tmpdir])
        assert not config.option.boxed

