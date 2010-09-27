"""
    Implement --dist=* testing
"""

import py
import sys
import execnet
from py._plugin import pytest_runner as runner # XXX load dynamically

def make_reltoroot(roots, args):
    # XXX introduce/use public API for splitting args
    splitcode = "::"
    l = []
    for arg in args:
        parts = arg.split(splitcode)
        fspath = py.path.local(parts[0])
        for root in roots:
            x = fspath.relto(root)
            if x or fspath == root:
                parts[0] = root.basename + "/" + x
                break
        else:
            raise ValueError("arg %s not relative to an rsync root" % (arg,))
        l.append(splitcode.join(parts))
    return l
    
class SlaveController(object):
    ENDMARK = -1

    def __init__(self, nodemanager, gateway, config, putevent):
        self.nodemanager = nodemanager
        self.putevent = putevent
        self.gateway = gateway
        self.config = config
        self._down = False
        self.log = py.log.Producer("slavectl-%s" % gateway.id)
        if not self.config.option.debug:
            py.log.setconsumer(self.log._keywords, None)

    def __repr__(self):
        return "<%s %s>" %(self.__class__.__name__, self.gateway.id,)

    def setup(self):
        self.log("setting up slave session")
        spec = self.gateway.spec
        args = self.config.args
        if not spec.popen or spec.chdir:
            args = make_reltoroot(self.nodemanager.roots, args)
        self.channel = self.gateway.remote_exec(init_slave_session,
            args=args, option_dict=vars(self.config.option),
        )
        if self.putevent:
            self.channel.setcallback(self.process_from_remote,
                endmarker=self.ENDMARK)

    def ensure_teardown(self):
        if hasattr(self, 'channel'):
            if not self.channel.isclosed():
                self.log("closing", self.channel)
                self.channel.close()
            #del self.channel
        if hasattr(self, 'gateway'):
            self.log("exiting", self.gateway)
            self.gateway.exit()
            #del self.gateway

    def send_runtest(self, nodeid):
        self.sendcommand("runtests", ids=[nodeid])

    def shutdown(self):
        if not self._down and not self.channel.isclosed():
            self.sendcommand("shutdown")

    def sendcommand(self, name, **kwargs):
        """ send a named parametrized command to the other side. """
        self.log("sending command %s(**%s)" % (name, kwargs))
        self.channel.send((name, kwargs))

    def notify_inproc(self, eventname, **kwargs):
        self.log("queuing %s(**%s)" % (eventname, kwargs))
        self.putevent((eventname, kwargs))

    def process_from_remote(self, eventcall):
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
                    self.notify_inproc("errordown", node=self, error=err)
                    self._down = True
                return
            eventname, kwargs = eventcall
            if eventname in ("collectionstart"):
                self.log("ignoring %s(%s)" %(eventname, kwargs))
            elif eventname == "slaveready":
                self.notify_inproc(eventname, node=self)
            elif eventname == "slavefinished":
                self._down = True
                self.slaveoutput = kwargs['slaveoutput']
                self.notify_inproc("slavefinished", node=self)
            #elif eventname == "logstart":
            #    self.notify_inproc(eventname, node=self, **kwargs)
            elif eventname in ("testreport", "collectreport"):
                rep = unserialize_report(kwargs['data'])
                self.notify_inproc(eventname, node=self, rep=rep)
            elif eventname == "collectionfinish":
                self.notify_inproc(eventname, node=self, ids=kwargs['ids'])
            else:
                raise ValueError("unknown event: %s" %(eventname,))
        except KeyboardInterrupt:
            # should not land in receiver-thread
            raise
        except:
            excinfo = py.code.ExceptionInfo()
            py.builtin.print_("!" * 20, excinfo)
            self.config.pluginmanager.notify_exception(excinfo)

def init_slave_session(channel, args, option_dict):
    import py
    #outchannel = channel.gateway.newchannel()
    #sys.stdout = sys.stderr = outchannel.makefile('w')
    #channel.send(outchannel)
    #fullwidth, hasmarkup = channel.receive()
    from xdist.remote import remote_initconfig, SlaveInteractor
    config = remote_initconfig(py.test.config, option_dict, args)
    interactor = SlaveInteractor(config, channel)
    config.hook.pytest_cmdline_main(config=config)

def remote_initconfig(config, option_dict, args):
    config._preparse(args)
    config.option.__dict__.update(option_dict)
    config.option.looponfail = False
    config.option.usepdb = False
    config.option.dist = "no"
    config.option.distload = False
    config.option.numprocesses = None
    config.args = args
    return config
    
class SlaveInteractor:
    def __init__(self, config, channel):
        self.config = config
        self.log = py.log.Producer("slave")
        if not config.option.debug:
            py.log.setconsumer(self.log._keywords, None)
        self.channel = channel
        config.pluginmanager.register(self)

    def sendevent(self, name, **kwargs):
        self.log("sending", name, kwargs)
        self.channel.send((name, kwargs))

    def pytest_internalerror(self, excrepr):
        for line in str(excrepr).split("\n"):
            self.log("IERROR> " + line)

    def pytest_sessionstart(self, session):
        self.session = session
        self.collection = session.collection
        self.sendevent("slaveready")

    def pytest_sessionfinish(self):
        self.sendevent("slavefinished", slaveoutput={})

    def pytest_perform_collection(self, session):
        self.sendevent("collectionstart")

    def pytest_runtest_mainloop(self, session):
        self.log("entering main loop")
        while 1:
            name, kwargs = self.channel.receive()
            self.log("received command %s(**%s)" % (name, kwargs))
            if name == "runtests":
                ids = kwargs['ids']
                for nodeid in ids:
                    for item in self.collection.getbyid(nodeid):
                        self.config.hook.pytest_runtest_protocol(item=item)
            elif name == "shutdown":
                break
        return True

    def pytest_log_finishcollection(self, collection):
        self.log("pytest_log_finishcollection")
        ids = [collection.getid(item) for item in collection.items]
        self.sendevent("collectionfinish",
            topdir=str(collection.topdir),
            ids=ids)

    #def pytest_runtest_logstart(self, nodeid, location):
    #    self.sendevent("logstart", nodeid=nodeid, location=location)

    def pytest_runtest_logreport(self, report):
        data = serialize_report(report)
        self.sendevent("testreport", data=data)

    def pytest_collectreport(self, report):
        data = serialize_report(report)
        self.sendevent("collectreport", data=data)

def serialize_report(rep):
    d = rep.__dict__.copy()
    d['longrepr'] = rep.longrepr and str(rep.longrepr) or None
    for name in d:
        if isinstance(d[name], py.path.local):
            d[name] = str(d[name])
        elif name == "result":
            d[name] = None # for now
    return d

def unserialize_report(reportdict):
    d = reportdict
    if 'result' in d:
        return runner.CollectReport(**d)
    else:
        return runner.TestReport(**d)

