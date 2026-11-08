Add experimental ``--worker-start-method=forkserver`` for local Linux and macOS
workers. Initial conftest imports and pytest configuration are inherited from a
separate single-threaded preload process, reducing duplicated import memory.
Requires the ``psutil`` extra and fork-safe imports; the default remains ``popen``.
