When tests crash
================

If a test crashes a worker, pytest-xdist will automatically restart that worker
and report the test’s failure. You can use the ``--max-worker-restart`` option
to limit the number of worker restarts that are allowed, or disable restarting
altogether using ``--max-worker-restart 0``.
