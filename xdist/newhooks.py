
def pytest_gwmanage_newgateway(gateway, platinfo):
    """ called on new raw gateway creation. """ 

def pytest_gwmanage_rsyncstart(source, gateways):
    """ called before rsyncing a directory to remote gateways takes place. """

def pytest_gwmanage_rsyncfinish(source, gateways):
    """ called after rsyncing a directory to remote gateways takes place. """

def pytest_configure_node(node):
    """ configure node information before it gets instantiated. """

def pytest_testnodeready(node):
    """ Test Node is ready to operate. """

def pytest_testnodedown(node, error):
    """ Test Node is down. """

def pytest_rescheduleitems(items):
    """ reschedule Items from a node that went down. """

def pytest_looponfailinfo(failreports, rootdirs):
    """ info for repeating failing tests. """

