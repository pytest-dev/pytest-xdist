"""
    Implement -f aka looponfailing for py.test.

    NOTE that we try to avoid loading and depending on application modules
    within the controlling process (the one that starts repeatedly test
    processes) otherwise changes to source code can crash
    the controlling process which should best never happen.
"""

import py
import sys
import execnet
from py._test.session import gettopdir
from xdist import util

def looponfail_main(config):
    remotecontrol = RemoteControl(config)
    # XXX better configure rootdir
    rootdirs = [gettopdir(config.args)]
    statrecorder = util.StatRecorder(rootdirs)
    try:
        while 1:
            remotecontrol.loop_once()
            if not remotecontrol.failures and remotecontrol.wasfailing:
                continue # the last failures passed, let's immediately rerun all
            statrecorder.waitonchange(checkinterval=2.0)
    except KeyboardInterrupt:
        print()

class RemoteControl(object):
    def __init__(self, config):
        self.config = config
        self.remote_topdir = None
        self.failures = []

    def trace(self, *args):
        if self.config.option.debug:
            msg = " ".join([str(x) for x in args])
            py.builtin.print_("RemoteControl:", msg)

    def initgateway(self):
        return execnet.makegateway("popen")

    def setup(self, out=None):
        if out is None:
            out = py.io.TerminalWriter()
        if hasattr(self, 'gateway'):
            raise ValueError("already have gateway %r" % self.gateway)
        self.trace("setting up slave session")
        self.gateway = self.initgateway()
        self.channel = channel = self.gateway.remote_exec(init_slave_session,
            args=self.config.args,
            option_dict=vars(self.config.option),
        )
        remote_outchannel = channel.receive()
        def write(s):
            out._file.write(s)
            out._file.flush()
        remote_outchannel.setcallback(write)

    def ensure_teardown(self):
        if hasattr(self, 'channel'):
            if not self.channel.isclosed():
                self.trace("closing", self.channel)
                self.channel.close()
            del self.channel
        if hasattr(self, 'gateway'):
            self.trace("exiting", self.gateway)
            self.gateway.exit()
            del self.gateway

    def runsession(self):
        try:
            self.trace("sending", (self.remote_topdir, self.failures))
            self.channel.send((self.remote_topdir, self.failures))
            try:
                return self.channel.receive()
            except self.channel.RemoteError:
                e = sys.exc_info()[1]
                self.trace("ERROR", e)
                raise
        finally:
            self.ensure_teardown()

    def loop_once(self):
        self.setup()
        self.wasfailing = self.failures and len(self.failures)
        result = self.runsession()
        topdir, failures, reports, collection_failed = result
        if collection_failed:
            reports = ["Collection failed, keeping previous failure set"]
        else:
            self.remote_topdir, self.failures = topdir, failures

        repr_pytest_looponfailinfo(
            failreports=reports,
            rootdirs=[self.remote_topdir],)

def repr_pytest_looponfailinfo(failreports, rootdirs):
    tr = py.io.TerminalWriter()
    if failreports:
        tr.sep("#", "LOOPONFAILING", bold=True)
        for report in failreports:
            if report:
                tr.line(report, red=True)
    tr.sep("#", "waiting for changes", bold=True)
    for rootdir in rootdirs:
        tr.line("### Watching:   %s" %(rootdir,), bold=True)


def init_slave_session(channel, args, option_dict):
    import os, sys
    import py
    outchannel = channel.gateway.newchannel()
    sys.stdout = sys.stderr = outchannel.makefile('w')
    channel.send(outchannel)
    # prune sys.path to not contain relative paths
    newpaths = []
    for p in sys.path:
        if p:
            if not os.path.isabs(p):
                p = os.path.abspath(p)
            newpaths.append(p)
    sys.path[:] = newpaths

    #fullwidth, hasmarkup = channel.receive()
    config = py.test.config
    config.option.__dict__.update(option_dict)
    config._preparse(args)
    config.args = args
    from xdist.looponfail import SlaveFailSession
    SlaveFailSession(config, channel).main()

class SlaveFailSession:
    def __init__(self, config, channel):
        self.config = config
        self.channel = channel
        self.recorded_failures = []
        self.collection_failed = False
        config.pluginmanager.register(self)
        config.option.looponfail = False
        config.option.usepdb = False

    def DEBUG(self, *args):
        if self.config.option.debug:
            print(" ".join(map(str, args)))

    def pytest_perform_collection(self, session):
        self.session = session
        self.collection = session.collection
        self.topdir, self.trails = self.current_command
        if self.topdir and self.trails:
            self.topdir = py.path.local(self.topdir)
            self.collection.topdir = self.topdir
            nodes = []
            for trail in self.trails:
                names = self.collection._parsearg(trail, base=self.topdir)
                try:
                    self.collection.genitems(
                        [self.collection._topcollector], names, nodes)
                except self.config.Error:
                    pass # ignore collect errors / vanished tests
            self.collection.items = nodes
            return True
        self.topdir = session.collection.topdir

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.recorded_failures.append(report)

    def pytest_collectreport(self, report):
        if report.failed:
            self.recorded_failures.append(report)
            self.collection_failed = True

    def main(self):
        self.DEBUG("SLAVE: received configuration, waiting for command trails")
        try:
            command = self.channel.receive()
        except KeyboardInterrupt:
            return # in the slave we can't do much about this
        self.DEBUG("received", command)
        self.current_command = command
        self.config.hook.pytest_cmdline_main(config=self.config)
        trails, failreports = [], []
        for rep in self.recorded_failures:
            trails.append(self.collection.getid(rep.getnode()))
            loc = rep._getcrashline()
            failreports.append(loc)
        topdir = str(self.topdir)
        self.channel.send((topdir, trails, failreports, self.collection_failed))

