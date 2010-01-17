import py
import pickle

def setglobals(request):
    oldconfig = py.test.config 
    print("setting py.test.config to None")
    py.test.config = None
    def resetglobals():
        py.builtin.print_("setting py.test.config to", oldconfig)
        py.test.config = oldconfig
    request.addfinalizer(resetglobals)

def pytest_funcarg__testdir(request):
    setglobals(request)
    return request.getfuncargvalue("testdir")

class ImmutablePickleTransport:
    def __init__(self, request):
        from xdist.mypickle import ImmutablePickler
        self.p1 = ImmutablePickler(uneven=0)
        self.p2 = ImmutablePickler(uneven=1)
        setglobals(request)

    def p1_to_p2(self, obj):
        return self.p2.loads(self.p1.dumps(obj))

    def p2_to_p1(self, obj):
        return self.p1.loads(self.p2.dumps(obj))

    def unifyconfig(self, config):
        p2config = self.p1_to_p2(config)
        p2config._initafterpickle(config.topdir)
        return p2config

pytest_funcarg__pickletransport = ImmutablePickleTransport

class TestImmutablePickling:
    def test_pickle_config(self, testdir, pickletransport):
        config1 = testdir.parseconfig()
        assert config1.topdir == testdir.tmpdir
        testdir.chdir()
        p2config = pickletransport.p1_to_p2(config1)
        assert p2config.topdir.realpath() == config1.topdir.realpath()
        config_back = pickletransport.p2_to_p1(p2config)
        assert config_back is config1

    def test_pickle_modcol(self, testdir, pickletransport):
        modcol1 = testdir.getmodulecol("def test_one(): pass")
        modcol2a = pickletransport.p1_to_p2(modcol1)
        modcol2b = pickletransport.p1_to_p2(modcol1)
        assert modcol2a is modcol2b

        modcol1_back = pickletransport.p2_to_p1(modcol2a)
        assert modcol1_back

    def test_pickle_func(self, testdir, pickletransport):
        modcol1 = testdir.getmodulecol("def test_one(): pass")
        item = modcol1.collect_by_name("test_one")
        testdir.chdir()
        item2a = pickletransport.p1_to_p2(item)
        assert item is not item2a # of course
        assert item2a.name == item.name
        modback = pickletransport.p2_to_p1(item2a.parent)
        assert modback is modcol1


def test_config__setstate__wired_correctly_in_childprocess(testdir):
    execnet = py.test.importorskip("execnet")
    from xdist.mypickle import PickleChannel
    gw = execnet.makegateway()
    channel = gw.remote_exec("""
        import py
        from xdist.mypickle import PickleChannel
        channel = PickleChannel(channel)
        config = channel.receive()
        assert py.test.config == config 
    """)
    channel = PickleChannel(channel)
    config = testdir.parseconfig()
    channel.send(config)
    channel.waitclose() # this will potentially raise 
    gw.exit()
