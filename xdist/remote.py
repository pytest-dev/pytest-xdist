"""
    Implement --dist=* testing
"""

import py
import sys
import execnet
import kwlog
from py._plugin import pytest_runner as runner # XXX load dynamically

class SlaveController(object):
    ENDMARK = -1

    def __init__(self, nodemanager, gateway, config, putevent):
        #self.nodemanager = nodemanager
        self.putevent = putevent
        self.gateway = gateway
        self.config = config
        self.status = None
        self._down = False
        self.status = "gateway-init"

    def __repr__(self):
        return "<%s id=%s status=%s>" %(self.__class__.__name__,
            self.gateway.id, self.status)

    def trace(self, *args):
        if self.config.option.debug:
            msg = " ".join([str(x) for x in args])
            py.builtin.print_("SlaveController:", msg)

    def setup(self):
        self.trace("setting up slave session")
        assert self.status == "gateway-init"
        self.channel = self.gateway.remote_exec(init_slave_session,
            args=self.config.args,
            option_dict=vars(self.config.option),
        )
        self.status = "slave-init"
        if self.putevent:
            self.channel.setcallback(self.process_from_remote,
                endmarker=self.ENDMARK)

    def ensure_teardown(self):
        if hasattr(self, 'channel'):
            if not self.channel.isclosed():
                self.trace("closing", self.channel)
                self.channel.close()
            #del self.channel
        if hasattr(self, 'gateway'):
            self.trace("exiting", self.gateway)
            self.gateway.exit()
            #del self.gateway

    def send_runtest(self, nodeid):
        self.sendcommand("runtests", ids=[nodeid])

    def shutdown(self):
        if not self._down and not self.channel.isclosed():
            self.sendcommand("shutdown")

    def sendcommand(self, name, **kwargs):
        """ send a named parametrized command to the other side. """
        self.trace("sending command %s(**%s)" % (name, kwargs))
        self.channel.send((name, kwargs))

    def notify_inproc(self, eventname, **kwargs):
        self.trace("queuing %s(**%s)" % (eventname, kwargs))
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
                self.trace("ignoring %s(%s)" %(eventname, kwargs))
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
    #kwlog.Producer("slave").DEBUG("option dict", config.option.__dict__)
    config.args = args
    return config

class SlaveInteractor:
    def __init__(self, config, channel):
        self.config = config
        self.log = kwlog.Producer("slave")
        kwlog.setconsumer(self.log, None)
        self.log.info("initializing SlaveInteractor")
        self.channel = channel
        config.pluginmanager.register(self)

    def sendevent(self, name, **kwargs):
        self.log.debug("sending", name, kwargs)
        self.channel.send((name, kwargs))

    def pytest_internalerror(self, excrepr):
        for line in str(excrepr).split("\n"):
            self.log.debug("IERROR> " + line)

    def pytest_sessionstart(self, session):
        self.session = session
        self.collection = session.collection
        self.sendevent("slaveready")

    def pytest_sessionfinish(self):
        self.sendevent("slavefinished", slaveoutput={})

    def pytest_perform_collection(self, session):
        self.sendevent("collectionstart")

    def pytest_runtest_mainloop(self, session):
        self.log.debug("entering main loop")
        while 1:
            name, kwargs = self.channel.receive()
            self.log.debug("received command %s(**%s)" % (name, kwargs))
            if name == "runtests":
                ids = kwargs['ids']
                for nodeid in ids:
                    for item in self.collection.getbyid(nodeid):
                        self.config.hook.pytest_runtest_protocol(item=item)
            elif name == "shutdown":
                break
        return True

    def pytest_log_finishcollection(self, collection):
        self.log.debug("pytest_log_finishcollection")
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

