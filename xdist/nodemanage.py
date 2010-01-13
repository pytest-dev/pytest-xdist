import py
import sys, os
import xdist
from xdist.txnode import TXNode
from xdist.gwmanage import GatewayManager
import execnet
    
class NodeManager(object):
    def __init__(self, config, specs=None):
        self.config = config 
        if specs is None:
            specs = self._getxspecs()
        self.roots = self._getrsyncdirs()
        self.gwmanager = GatewayManager(specs, config.hook)
        self.nodes = []
        self._nodesready = py.std.threading.Event()

    def trace(self, msg):
        self.config.hook.pytest_trace(category="nodemanage", msg=msg)

    def config_getignores(self):
        return self.config.getconftest_pathlist("rsyncignore")

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
        old = self.config.topdir.chdir()  
        try:
            self.gwmanager.makegateways()
        finally:
            old.chdir()

    def setup_nodes(self, putevent):
        self.rsync_roots()
        self.trace("setting up nodes")
        for gateway in self.gwmanager.group:
            node = TXNode(gateway, self.config, putevent, slaveready=self._slaveready)
            gateway.node = node  # to keep node alive 
            self.trace("started node %r" % node)

    def _slaveready(self, node):
        #assert node.gateway == node.gateway
        #assert node.gateway.node == node
        self.nodes.append(node)
        self.trace("%s slave node ready %r" % (node.gateway.id, node))
        if len(self.nodes) == len(list(self.gwmanager.group)):
            self._nodesready.set()
   
    def wait_nodesready(self, timeout=None):
        self._nodesready.wait(timeout)
        if not self._nodesready.isSet():
            raise IOError("nodes did not get ready for %r secs" % timeout)

    def teardown_nodes(self):
        # XXX do teardown nodes? 
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
            raise config.Error(
                "MISSING test execution (tx) nodes: please specify --tx")
        return [execnet.XSpec(x) for x in xspeclist]

    def _getrsyncdirs(self):
        config = self.config
        candidates = [py._pydir] 
        candidates += [py.path.local(xdist.__file__).dirpath()]
        candidates += config.option.rsyncdir
        conftestroots = config.getconftest_pathlist("rsyncdirs")
        if conftestroots:
            candidates.extend(conftestroots)
        roots = []
        for root in candidates:
            root = py.path.local(root).realpath()
            if not root.check():
                raise config.Error("rsyncdir doesn't exist: %r" %(root,))
            if root not in roots:
                roots.append(root)
        return roots
