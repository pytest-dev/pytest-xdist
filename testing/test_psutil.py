import sys
import os
import copy
import psutil

from os.path import join, dirname
from contextlib import suppress

is_win = sys.platform == 'win32'


def test_run_executable():
    verbose_file = join(dirname(__file__), 'verbose_output.py')
    prog = sys.executable

    for x in range(100):
        _run_executable(prog, [verbose_file]):


def _run_executable(prog, args, run_from_path=False, runtime=5):
    """
    Run executable created by PyInstaller.
    :param args: CLI options to pass to the created executable.
    """
    # Run the test in a clean environment to make sure they're really self-contained.
    prog_env = copy.deepcopy(os.environ)
    prog_env['PATH'] = ''
    del prog_env['PATH']

    exe_path = prog
    if(run_from_path):
        # Run executable in the temp directory
        # Add the directory containing the executable to $PATH
        # Basically, pretend we are a shell executing the program from $PATH.
        prog_cwd = self._tmpdir
        prog_name = os.path.basename(prog)
        prog_env['PATH'] = os.pathsep.join([prog_env.get('PATH', ''), os.path.dirname(prog)])

    else:
        # Run executable in the directory where it is.
        prog_cwd = os.path.dirname(prog)
        # The executable will be called with argv[0] as relative not absolute path.
        prog_name = os.path.join(os.curdir, os.path.basename(prog))

    args = [prog_name] + args
    # Using sys.stdout/sys.stderr for subprocess fixes printing messages in
    # Windows command prompt. Py.test is then able to collect stdout/sterr
    # messages and display them if a test fails.

    process = psutil.Popen(args, executable=exe_path, stdout=sys.stdout,
                           stderr=sys.stderr, env=prog_env, cwd=prog_cwd)
    # 'psutil' allows to use timeout in waiting for a subprocess.
    # If not timeout was specified then it is 'None' - no timeout, just waiting.
    # Runtime is useful mostly for interactive tests.
    try:
        timeout = runtime if runtime else _EXE_TIMEOUT
        retcode = process.wait(timeout=timeout)
    except psutil.TimeoutExpired:
        if runtime:
            # When 'runtime' is set then expired timeout is a good sing
            # that the executable was running successfully for a specified time.
            # TODO Is there a better way return success than 'retcode = 0'?
            retcode = 0
        else:
            # Exe is still running and it is not an interactive test. Fail the test.
            retcode = 1

        # Kill the subprocess and its child processes.
        for p in list(process.children(recursive=True)) + [process]:
            with suppress(psutil.NoSuchProcess):
                p.kill()

    return retcode
