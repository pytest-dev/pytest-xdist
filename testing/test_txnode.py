
import py
import execnet
from xdist.txnode import TXNode
queue = py.builtin._tryimport("queue", "Queue")
Queue = queue.Queue

class EventQueue:
    def __init__(self, registry, queue=None):
        if queue is None:
            queue = Queue()
        self.queue = queue
        registry.register(self)

    def geteventargs(self, eventname, timeout=10.0):
        events = []
        while 1:
            try:
                eventcall = self.queue.get(timeout=timeout)
            except queue.Empty:
                #print "node channel", self.node.channel
                #print "remoteerror", self.node.channel._getremoteerror()
                py.builtin.print_("seen events", events)
                raise IOError("did not see %r events" % (eventname))
            else:
                name, args, kwargs = eventcall 
                assert isinstance(name, str)
                if name == eventname:
                    if args:
                        return args
                    return kwargs
                events.append(name)
                if name == "pytest_internalerror":
                    py.builtin.print_(str(kwargs["excrepr"]))

class MySetup:
    def __init__(self, request):
        self.id = 0
        self.request = request

    def geteventargs(self, eventname, timeout=10.0):
        eq = EventQueue(self.config.pluginmanager, self.queue)
        return eq.geteventargs(eventname, timeout=timeout)

    def makenode(self, config=None, xspec="popen"):
        if config is None:
            testdir = self.request.getfuncargvalue("testdir")
            config = testdir.reparseconfig([])
        self.config = config
        self.queue = Queue()
        self.xspec = execnet.XSpec(xspec)
        self.gateway = execnet.makegateway(self.xspec)
        self.id += 1
        self.gateway.id = str(self.id)
        self.nodemanager = None
        self.node = TXNode(self.nodemanager, self.gateway, self.config, putevent=self.queue.put)
        assert not self.node.channel.isclosed()
        return self.node 

    def xfinalize(self):
        if hasattr(self, 'node'):
            gw = self.node.gateway
            py.builtin.print_("exiting:", gw)
            gw.exit()

def pytest_funcarg__mysetup(request):
    mysetup = MySetup(request)
    #pyfuncitem.addfinalizer(mysetup.finalize)
    return mysetup

def test_node_hash_equality(mysetup):
    node = mysetup.makenode()
    node2 = mysetup.makenode()
    assert node != node2
    assert node == node
    assert not (node != node)

class TestMasterSlaveConnection:
    def test_crash_invalid_item(self, mysetup):
        node = mysetup.makenode()
        node.send(123) # invalid item 
        kwargs = mysetup.geteventargs("pytest_testnodedown")
        assert kwargs['node'] is node 
        #assert isinstance(kwargs['error'], execnet.RemoteError)

    def test_crash_killed(self, testdir, mysetup):
        if not hasattr(py.std.os, 'kill'):
            py.test.skip("no os.kill")
        item = testdir.getitem("""
            def test_func():
                import os
                os.kill(os.getpid(), 9)
        """)
        node = mysetup.makenode(item.config)
        node.send(item) 
        kwargs = mysetup.geteventargs("pytest_testnodedown")
        assert kwargs['node'] is node 
        assert "Not properly terminated" in str(kwargs['error'])

    def test_node_down(self, mysetup):
        node = mysetup.makenode()
        node.shutdown()
        kwargs = mysetup.geteventargs("pytest_testnodedown")
        assert kwargs['node'] is node 
        assert not kwargs['error']
        node.callback(node.ENDMARK)
        excinfo = py.test.raises(IOError, 
            "mysetup.geteventargs('testnodedown', timeout=0.01)")

    def test_send_on_closed_channel(self, testdir, mysetup):
        item = testdir.getitem("def test_func(): pass")
        node = mysetup.makenode(item.config)
        node.channel.close()
        py.test.raises(IOError, "node.send(item)")
        #ev = self.getcalls(pytest_internalerror)
        #assert ev.excinfo.errisinstance(IOError)

    def test_send_one(self, testdir, mysetup):
        item = testdir.getitem("def test_func(): pass")
        node = mysetup.makenode(item.config)
        node.send(item)
        kwargs = mysetup.geteventargs("pytest_runtest_logreport")
        rep = kwargs['report'] 
        assert rep.passed 
        py.builtin.print_(rep)
        assert rep.item == item

    def test_send_some(self, testdir, mysetup):
        items = testdir.getitems("""
            def test_pass(): 
                pass
            def test_fail():
                assert 0
            def test_skip():
                import py
                py.test.skip("x")
        """)
        node = mysetup.makenode(items[0].config)
        for item in items:
            node.send(item)
        for outcome in "passed failed skipped".split():
            kwargs = mysetup.geteventargs("pytest_runtest_logreport")
            report = kwargs['report']
            assert getattr(report, outcome) 

        node.sendlist(items)
        for outcome in "passed failed skipped".split():
            rep = mysetup.geteventargs("pytest_runtest_logreport")['report']
            assert getattr(rep, outcome) 

    def test_send_one_with_env(self, testdir, mysetup, monkeypatch):
        if execnet.XSpec("popen").env is None:
            py.test.skip("requires execnet 1.0.7 or above")
        monkeypatch.delenv('ENV1', raising=False)
        monkeypatch.delenv('ENV2', raising=False)
        monkeypatch.setenv('ENV3', 'var3')

        item = testdir.getitem("""
            def test_func():
                import os
                # ENV1, ENV2 set by xspec; ENV3 inherited from parent process
                assert os.getenv('ENV2') == 'var2'
                assert os.getenv('ENV1') == 'var1'
                assert os.getenv('ENV3') == 'var3'
        """)
        node = mysetup.makenode(item.config,
                xspec="popen//env:ENV1=var1//env:ENV2=var2")
        node.send(item)
        kwargs = mysetup.geteventargs("pytest_runtest_logreport")
        rep = kwargs['report']
        assert rep.passed

