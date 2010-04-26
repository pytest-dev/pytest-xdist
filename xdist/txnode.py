"""
    Manage setup, running and local representation of remote nodes/processes. 
"""
import py
from xdist.mypickle import PickleChannel
from py._test.session import Session

class TXNode(object):
    """ Represents a Test Execution environment in the controlling process. 
        - sets up a slave node through an execnet gateway 
        - manages sending of test-items and receival of results and events
        - creates events when the remote side crashes 
    """
    ENDMARK = -1

    def __init__(self, nodemanager, gateway, config, putevent):
        self.nodemanager = nodemanager
        self.config = config 
        self.putevent = putevent 
        self.gateway = gateway
        self.slaveinput = {}
        self.channel = install_slave(self)
        self.channel.setcallback(self.callback, endmarker=self.ENDMARK)
        self._down = False

    def __repr__(self):
        id = self.gateway.id
        status = self._down and 'true' or 'false'
        return "<TXNode %r down=%s>" %(id, status)

    def notify(self, eventname, *args, **kwargs):
        assert not args
        self.putevent((eventname, args, kwargs))
      
    def callback(self, eventcall):
        """ this gets called for each object we receive from 
            the other side and if the channel closes. 

            Note that channel callbacks run in the receiver
            thread of execnet gateways - we need to 
            avoid raising exceptions or doing heavy work.
        """
        try:
            if eventcall == self.ENDMARK:
                err = self.channel._getremoteerror()
                if not self._down:
                    if not err or isinstance(err, EOFError):
                        err = "Not properly terminated" # lost connection? 
                    self.notify("pytest_testnodedown", node=self, error=err)
                    self._down = True
                return
            eventname, args, kwargs = eventcall 
            if eventname == "slaveready":
                self.notify("pytest_testnodeready", node=self)
            elif eventname == "slavefinished":
                self._down = True
                self.slaveoutput = kwargs['slaveoutput']
                error = kwargs['error']
                self.notify("pytest_testnodedown", error=error, node=self)
            elif eventname in ("pytest_runtest_logreport", 
                               "pytest__teardown_final_logerror"):
                kwargs['report'].node = self
                self.notify(eventname, **kwargs)
            else:
                self.notify(eventname, **kwargs)
        except KeyboardInterrupt: 
            # should not land in receiver-thread
            raise 
        except:
            excinfo = py.code.ExceptionInfo()
            py.builtin.print_("!" * 20, excinfo)
            self.config.pluginmanager.notify_exception(excinfo)

    def send(self, item):
        assert item is not None
        self.channel.send(item)

    def sendlist(self, itemlist):
        self.channel.send(itemlist)

    def shutdown(self, kill=False):
        if kill:
            self.gateway.exit()
        else:
            self.channel.send(None)

# configuring and setting up slave node 
def install_slave(node):
    channel = node.gateway.remote_exec(source="""
        import os, sys 
        sys.path.insert(0, os.getcwd()) 
        from xdist.mypickle import PickleChannel
        from xdist.txnode import SlaveSession
        channel.send("basicimport")
        channel = PickleChannel(channel)
        import py
        config, slaveinput, basetemp, nodeid = channel.receive()
        config.slaveinput = slaveinput
        config.slaveoutput = {}
        if basetemp:
            config.basetemp = py.path.local(basetemp)
        config.nodeid = nodeid
        config.pluginmanager.do_configure(config)
        session = SlaveSession(config, channel, nodeid)
        session.dist_main()
    """)
    channel.receive()
    channel = PickleChannel(channel)
    basetemp = None
    config = node.config 
    config.hook.pytest_configure_node(node=node)
    if node.gateway.spec.popen:
        popenbase = config.ensuretemp("popen")
        basetemp = py.path.local.make_numbered_dir(prefix="slave-", 
            keep=0, rootdir=popenbase)
        basetemp = str(basetemp)
    channel.send((config, node.slaveinput, basetemp, node.gateway.id))
    return channel

class SlaveSession(Session):
    def __init__(self, config, channel, nodeid):
        self.channel = channel
        self.nodeid = nodeid
        super(SlaveSession, self).__init__(config=config)

    def __repr__(self):
        return "<%s channel=%s>" %(self.__class__.__name__, self.channel)

    def sendevent(self, eventname, *args, **kwargs):
        self.channel.send((eventname, args, kwargs))

    def pytest_runtest_logreport(self, report):
        self.sendevent("pytest_runtest_logreport", report=report)

    def pytest__teardown_final_logerror(self, report):
        self.sendevent("pytest__teardown_final_logerror", report=report)

    def pytest_keyboard_interrupt(self, excinfo):
        self._slaveerror = "SIGINT"

    def pytest_internalerror(self, excrepr):
        self._slaveerror = "internal-error"
        self.sendevent("pytest_internalerror", excrepr=excrepr)

    def dist_main(self):
        self.runner = self.config.pluginmanager.getplugin("pytest_runner")
        self.sendevent("slaveready")
        self.main(None)
        error = getattr(self, '_slaveerror', None)
        self.sendevent("slavefinished", error=error, 
                       slaveoutput=self.config.slaveoutput)
        
    def _mainloop(self, colitems):
        while 1:
            task = self.channel.receive()
            if task is None: 
                break
            if isinstance(task, list):
                for item in task:
                    self.run_single(item=item)
            else:
                self.run_single(item=task)

    def run_single(self, item):
        call = self.runner.CallInfo(item._reraiseunpicklingproblem, when='setup')
        if call.excinfo:
            # likely it is not collectable here because of
            # platform/import-dependency induced skips 
            # we fake a setup-error report with the obtained exception
            # and do not care about capturing or non-runner hooks 
            rep = self.runner.pytest_runtest_makereport(item=item, call=call)
            self.pytest_runtest_logreport(rep)
            return
        item.config.hook.pytest_runtest_protocol(item=item) 
