
.. _`Multi-Platform`:
.. _`remote machines`:

Sending tests to remote SSH accounts
====================================

.. deprecated:: 3.0

.. warning::

    The ``rsync`` feature is deprecated because its implementation is faulty
    in terms of reproducing the development environment in the remote
    worker, and there is no clear solution moving forward.

    For that reason, ``rsync`` is scheduled to be removed in release 4.0, to let the team
    focus on a smaller set of features.

    Note that SSH and socket server are not planned for removal, as they are part
    of the ``execnet`` feature set.

Suppose you have a package ``mypkg`` which contains some
tests that you can successfully run locally. And you
have a ssh-reachable machine ``myhost``.  Then
you can ad-hoc distribute your tests by typing::

    pytest -d  --rsyncdir mypkg --tx ssh=myhostpopen mypkg/tests/unit/test_something.py

This will synchronize your :code:`mypkg` package directory
to a remote ssh account and then locally collect tests
and send them to remote places for execution.

You can specify multiple :code:`--rsyncdir` directories
to be sent to the remote side.

.. note::

  For pytest to collect and send tests correctly
  you not only need to make sure all code and tests
  directories are rsynced, but that any test (sub) directory
  also has an :code:`__init__.py` file because internally
  pytest references tests as a fully qualified python
  module path.  **You will otherwise get strange errors**
  during setup of the remote side.


You can specify multiple :code:`--rsyncignore` glob patterns
to be ignored when file are sent to the remote side.
There are also internal ignores: :code:`.*, *.pyc, *.pyo, *~`
Those you cannot override using rsyncignore command-line or
ini-file option(s).


Sending tests to remote Socket Servers
--------------------------------------

Download the single-module `socketserver.py`_ Python program
and run it like this::

    python socketserver.py

It will tell you that it starts listening on the default
port.  You can now on your home machine specify this
new socket host with something like this::

    pytest -d --tx socket=192.168.1.102:8888 --rsyncdir mypkg



Running tests on many platforms at once
---------------------------------------

The basic command to run tests on multiple platforms is::

    pytest --dist=each --tx=spec1 --tx=spec2

If you specify a windows host, an OSX host and a Linux
environment this command will send each tests to all
platforms - and report back failures from all platforms
at once. The specifications strings use the `xspec syntax`_.

.. _`xspec syntax`: https://codespeak.net/execnet/basics.html#xspec

.. _`execnet`: https://codespeak.net/execnet

.. _`socketserver.py`: https://raw.githubusercontent.com/pytest-dev/execnet/master/src/execnet/script/socketserver.py
