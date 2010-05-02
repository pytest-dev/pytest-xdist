"""loop on failing tests, distribute test runs to CPUs and hosts.

The `pytest-xdist`_ plugin extends py.test with some unique 
test execution modes:

* Looponfail: run your tests repeatedly in a subprocess.  After each run py.test
  waits until a file in your project changes and then re-runs the previously
  failing tests.  This is repeated until all tests pass after which again
  a full run is performed. 

* Load-balancing: if you have multiple CPUs or hosts you can use
  those for a combined test run.  This allows to speed up 
  development or to use special resources of remote machines.  

* Multi-Platform coverage: you can specify different Python interpreters
  or different platforms and run tests in parallel on all of them. 

Before running tests remotely, ``py.test`` efficiently synchronizes your 
program source code to the remote place.  All test results 
are reported back and displayed to your local test session.  
You may specify different Python versions and interpreters.

.. _`pytest-xdist`: http://pypi.python.org/pypi/pytest-xdist

Usage examples
---------------------

Speed up test runs by sending tests to multiple CPUs
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

To send tests to multiple CPUs, type::

    py.test -n NUM

Especially for longer running tests or tests requiring 
a lot of IO this can lead to considerable speed ups. 


Running tests in a Python subprocess 
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

To instantiate a python2.4 sub process and send tests to it, you may type::

    py.test -d --tx popen//python=python2.4

This will start a subprocess which is run with the "python2.4"
Python interpreter, found in your system binary lookup path. 

If you prefix the --tx option value like this::

    --tx 3*popen//python=python2.4

then three subprocesses would be created and tests
will be load-balanced across these three processes. 


Sending tests to remote SSH accounts
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Suppose you have a package ``mypkg`` which contains some 
tests that you can successfully run locally. And you
have a ssh-reachable machine ``myhost``.  Then    
you can ad-hoc distribute your tests by typing::

    py.test -d --tx ssh=myhostpopen --rsyncdir mypkg mypkg

This will synchronize your ``mypkg`` package directory 
to an remote ssh account and then locally collect tests 
and send them to remote places for execution.  

You can specify multiple ``--rsyncdir`` directories 
to be sent to the remote side. 

**NOTE:** For py.test to collect and send tests correctly
you not only need to make sure all code and tests
directories are rsynced, but that any test (sub) directory
also has an ``__init__.py`` file because internally
py.test references tests as a fully qualified python
module path.  **You will otherwise get strange errors** 
during setup of the remote side.

Sending tests to remote Socket Servers
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Download the single-module `socketserver.py`_ Python program 
and run it like this::

    python socketserver.py

It will tell you that it starts listening on the default
port.  You can now on your home machine specify this 
new socket host with something like this::

    py.test -d --tx socket=192.168.1.102:8888 --rsyncdir mypkg mypkg


.. _`atonce`:

Running tests on many platforms at once 
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

The basic command to run tests on multiple platforms is::

    py.test --dist=each --tx=spec1 --tx=spec2 

If you specify a windows host, an OSX host and a Linux
environment this command will send each tests to all 
platforms - and report back failures from all platforms
at once.   The specifications strings use the `xspec syntax`_. 

.. _`xspec syntax`: http://codespeak.net/execnet/trunk/basics.html#xspec

.. _`socketserver.py`: http://codespeak.net/svn/py/dist/py/execnet/script/socketserver.py

.. _`execnet`: http://codespeak.net/execnet

Specifying test exec environments in a conftest.py
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Instead of specifying command line options, you can 
put options values in a ``conftest.py`` file like this::

    pytest_option_tx = ['ssh=myhost//python=python2.5', 'popen//python=python2.5']
    pytest_option_dist = True

Any commandline ``--tx`` specifictions  will add to the list of available execution
environments. 

Specifying "rsync" dirs in a conftest.py
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

In your ``mypkg/conftest.py`` you may specify directories to synchronise
or to exclude::

    rsyncdirs = ['.', '../plugins']
    rsyncignore = ['_cache']

These directory specifications are relative to the directory
where the ``conftest.py`` is found.

"""

import sys
import py

def pytest_addoption(parser):
    group = parser.getgroup("xdist", "distributed and subprocess testing") 
    group._addoption('-f', '--looponfail',
           action="store_true", dest="looponfail", default=False,
           help="run tests in subprocess, wait for modified files "
                "and re-run failing test set until all pass.")
    group._addoption('-n', dest="numprocesses", metavar="numprocesses", 
           action="store", type="int", 
           help="shortcut for '--dist=load --tx=NUM*popen'")
    group.addoption('--boxed',
           action="store_true", dest="boxed", default=False,
           help="box each test run in a separate process (unix)") 
    group._addoption('--dist', metavar="distmode", 
           action="store", choices=['load', 'each', 'no'], 
           type="choice", dest="dist", default="no", 
           help=("set mode for distributing tests to exec environments.\n\n"
                 "each: send each test to each available environment.\n\n"
                 "load: send each test to available environment.\n\n"
                 "(default) no: run tests inprocess, don't distribute."))
    group._addoption('--tx', dest="tx", action="append", default=[], 
           metavar="xspec",
           help=("add a test execution environment. some examples: "
                 "--tx popen//python=python2.5 --tx socket=192.168.1.102:8888 "
                 "--tx ssh=user@codespeak.net//chdir=testcache"))
    group._addoption('-d', 
           action="store_true", dest="distload", default=False,
           help="load-balance tests.  shortcut for '--dist=load'")
    group.addoption('--rsyncdir', action="append", default=[], metavar="dir1", 
           help="add directory for rsyncing to remote tx nodes.")

# -------------------------------------------------------------------------
# distributed testing hooks
# -------------------------------------------------------------------------
def pytest_addhooks(pluginmanager):
    from xdist import newhooks
    pluginmanager.addhooks(newhooks)

# -------------------------------------------------------------------------
# distributed testing initialization
# -------------------------------------------------------------------------
def pytest_configure(config):
    if config.option.numprocesses:
        config.option.dist = "load"
        config.option.tx = ['popen'] * int(config.option.numprocesses)
    if config.option.distload:
        config.option.dist = "load"
    val = config.getvalue
    if not val("collectonly"):
        usepdb = config.option.usepdb  # a core option
        if val("looponfail"):
            if usepdb:
                raise config.Error("--pdb incompatible with --looponfail.")
            from xdist.remote import LooponfailingSession
            config.setsessionclass(LooponfailingSession)
        elif val("dist") != "no":
            if usepdb:
                raise config.Error("--pdb incompatible with distributing tests.")
            from xdist.dsession import DSession
            config.setsessionclass(DSession)

def pytest_runtest_protocol(item):
    if item.config.getvalue("boxed"):
        reports = forked_run_report(item)
        for rep in reports:
            item.ihook.pytest_runtest_logreport(report=rep)
        return True

def forked_run_report(item):
    # for now, we run setup/teardown in the subprocess 
    # XXX optionally allow sharing of setup/teardown 
    from py._plugin.pytest_runner import runtestprotocol
    EXITSTATUS_TESTEXIT = 4
    from xdist.mypickle import ImmutablePickler
    ipickle = ImmutablePickler(uneven=0)
    ipickle.selfmemoize(item.config)
    # XXX workaround the issue that 2.6 cannot pickle 
    # instances of classes defined in global conftest.py files
    ipickle.selfmemoize(item) 
    def runforked():
        try:
            reports = runtestprotocol(item, log=False)
        except KeyboardInterrupt: 
            py.std.os._exit(EXITSTATUS_TESTEXIT)
        return ipickle.dumps(reports)

    ff = py.process.ForkedFunc(runforked)
    result = ff.waitfinish()
    if result.retval is not None:
        return ipickle.loads(result.retval)
    else:
        if result.exitstatus == EXITSTATUS_TESTEXIT:
            py.test.exit("forked test item %s raised Exit" %(item,))
        return [report_process_crash(item, result)]

def report_process_crash(item, result):
    path, lineno = item._getfslineno()
    info = "%s:%s: running the test CRASHED with signal %d" %(
            path, lineno, result.signal)
    from py._plugin.pytest_runner import ItemTestReport
    return ItemTestReport(item, excinfo=info, when="???")

