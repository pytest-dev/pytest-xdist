import py, pytest
import sys, os
import execnet
import xdist.remote

from pytest.plugin import runner # XXX load dynamically

class NodeManager(object):
    def __init__(self, config, specs=None):
        self.config = config
        if specs is None:
            specs = self._getxspecs()
        self.roots = self._getrsyncdirs()
        self.gwmanager = GatewayManager(specs, config.hook)
        self._nodesready = py.std.threading.Event()

    def trace(self, msg):
        self.config.hook.pytest_trace(category="nodemanage", msg=msg)

    def config_getignores(self):
        return self.config.getini("rsyncignore")

    def rsync_roots(self):
        """ make sure that all remote gateways
            have the same set of roots in their
            current directory.
        """
        self.makegateways()
        options = {
            'ignores': self.config_getignores(),
            'verbose': self.config.option.verbose,
        }
        if self.roots:
            # send each rsync root
            for root in self.roots:
                self.gwmanager.rsync(root, **options)
        else:
            XXX # do we want to care for situations without explicit rsyncdirs?
            # we transfer our topdir as the root
            self.gwmanager.rsync(self.config.topdir, **options)
            # and cd into it
            self.gwmanager.multi_chdir(self.config.topdir.basename, inplacelocal=False)

    def makegateways(self):
        # we change to the topdir sot that
        # PopenGateways will have their cwd
        # such that unpickling configs will
        # pick it up as the right topdir
        # (for other gateways this chdir is irrelevant)
        self.trace("making gateways")
        #old = self.config.topdir.chdir()
        #try:
        self.gwmanager.makegateways()
        #finally:
        #    old.chdir()

    def setup_nodes(self, putevent):
        self.rsync_roots()
        self.trace("setting up nodes")
        for gateway in self.gwmanager.group:
            node = SlaveController(self, gateway, self.config, putevent)
            gateway.node = node  # to keep node alive
            node.setup()
            self.trace("started node %r" % node)

    def teardown_nodes(self):
        self.gwmanager.exit()

    def _getxspecs(self):
        config = self.config
        xspeclist = []
        for xspec in config.getvalue("tx"):
            i = xspec.find("*")
            try:
                num = int(xspec[:i])
            except ValueError:
                xspeclist.append(xspec)
            else:
                xspeclist.extend([xspec[i+1:]] * num)
        if not xspeclist:
            raise pytest.UsageError(
                "MISSING test execution (tx) nodes: please specify --tx")
        return [execnet.XSpec(x) for x in xspeclist]

    def _getrsyncdirs(self):
        config = self.config
        candidates = [py._pydir]
        candidates += config.option.rsyncdir
        conftestroots = config.getini("rsyncdirs")
        if conftestroots:
            candidates.extend(conftestroots)
        roots = []
        for root in candidates:
            root = py.path.local(root).realpath()
            if not root.check():
                raise pytest.UsageError("rsyncdir doesn't exist: %r" %(root,))
            if root not in roots:
                roots.append(root)
        return roots


class GatewayManager:
    """
        instantiating, managing and rsyncing to test hosts
    """
    EXIT_TIMEOUT = 10
    def __init__(self, specs, hook, defaultchdir="pyexecnetcache"):
        self.specs = []
        self.hook = hook
        self.group = execnet.Group()
        for spec in specs:
            if not isinstance(spec, execnet.XSpec):
                spec = execnet.XSpec(spec)
            if not spec.chdir and not spec.popen:
                spec.chdir = defaultchdir
            self.specs.append(spec)

    def makegateways(self):
        assert not list(self.group)
        for spec in self.specs:
            gw = self.group.makegateway(spec)
            self.hook.pytest_gwmanage_newgateway(gateway=gw)

    def rsync(self, source, notify=None, verbose=False, ignores=None):
        """ perform rsync to all remote hosts.
        """
        rsync = HostRSync(source, verbose=verbose, ignores=ignores)
        seen = py.builtin.set()
        gateways = []
        for gateway in self.group:
            spec = gateway.spec
            if spec.popen and not spec.chdir:
                # XXX this assumes that sources are python-packages
                # and that adding the basedir does not hurt
                gateway.remote_exec("""
                    import sys ; sys.path.insert(0, %r)
                """ % os.path.dirname(str(source))).waitclose()
                continue
            if spec not in seen:
                def finished():
                    if notify:
                        notify("rsyncrootready", spec, source)
                rsync.add_target_host(gateway, finished=finished)
                seen.add(spec)
                gateways.append(gateway)
        if seen:
            self.hook.pytest_gwmanage_rsyncstart(
                source=source,
                gateways=gateways,
            )
            rsync.send()
            self.hook.pytest_gwmanage_rsyncfinish(
                source=source,
                gateways=gateways,
            )

    def exit(self):
        self.group.terminate(self.EXIT_TIMEOUT)

class HostRSync(execnet.RSync):
    """ RSyncer that filters out common files
    """
    def __init__(self, sourcedir, *args, **kwargs):
        self._synced = {}
        ignores= None
        if 'ignores' in kwargs:
            ignores = kwargs.pop('ignores')
        self._ignores = ignores or []
        super(HostRSync, self).__init__(sourcedir=sourcedir, **kwargs)

    def filter(self, path):
        path = py.path.local(path)
        if not path.ext in ('.pyc', '.pyo'):
            if not path.basename.endswith('~'):
                if path.check(dotfile=0):
                    for x in self._ignores:
                        if path == x:
                            break
                    else:
                        return True

    def add_target_host(self, gateway, finished=None):
        remotepath = os.path.basename(self._sourcedir)
        super(HostRSync, self).add_target(gateway, remotepath,
                                          finishedcallback=finished,
                                          delete=True,)

    def _report_send_file(self, gateway, modified_rel_path):
        if self._verbose:
            path = os.path.basename(self._sourcedir) + "/" + modified_rel_path
            remotepath = gateway.spec.chdir
            py.builtin.print_('%s:%s <= %s' %
                              (gateway.spec, remotepath, path))


def make_reltoroot(roots, args):
    # XXX introduce/use public API for splitting py.test args
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
        self.slaveinput = {'slaveid': gateway.id}
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
        option_dict = vars(self.config.option)
        if spec.popen:
            name = "popen-%s" % self.gateway.id
            option_dict['basetemp'] = str(self.config.getbasetemp().join(name))
        self.config.hook.pytest_configure_node(node=self)
        self.channel = self.gateway.remote_exec(xdist.remote)
        self.channel.send((self.slaveinput, args, option_dict))
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

    def send_runtest_all(self):
        self.sendcommand("runtests_all",)

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
                self.notify_inproc(eventname, node=self, **kwargs)
            elif eventname == "slavefinished":
                self._down = True
                self.slaveoutput = kwargs['slaveoutput']
                self.notify_inproc("slavefinished", node=self)
            #elif eventname == "logstart":
            #    self.notify_inproc(eventname, node=self, **kwargs)
            elif eventname in ("testreport", "collectreport", "teardownreport"):
                rep = unserialize_report(eventname, kwargs['data'])
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

def unserialize_report(name, reportdict):
    d = reportdict
    if name == "testreport":
        return runner.TestReport(**d)
    elif name == "collectreport":
        return runner.CollectReport(**d)
    elif name == "teardownreport":
        return runner.TeardownErrorReport(**d)
