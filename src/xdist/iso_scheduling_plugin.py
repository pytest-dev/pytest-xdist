# This code was contributed to pytest-xdist by Akamai Technologies Inc.
# Copyright 2024 Akamai Technologies, Inc.
# Developed by Vitaly Kruglikov at Akamai Technologies, Inc.
#
#  MIT License
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in all
#  copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Pytest Fixtures for supporting users of isoscope scheduling.

NOTE: These fixtures are NOT compatible with any other xdist schedulers.

NOTE: DO NOT IMPORT this module. It needs to be loaded via pytest's
`conftest.pytest_plugins` mechanism. Pytest doc discourages importing fixtures
directly from other modules - see
https://docs.pytest.org/en/7.1.x/how-to/fixtures.html:
> "Sometimes users will import fixtures from other projects for use, however this
is not recommended: importing fixtures into a module will register them in
pytest as defined in that module".
"""
from __future__ import annotations

import contextlib
import functools
import logging
import json
import pathlib
from typing import TYPE_CHECKING

import filelock
import pytest

from xdist.iso_scheduling_utils import (
    IsoSchedulingFixture,
    DistributedSetupCoordinator,
    DistributedSetupContext,
    DistributedTeardownContext,
    CoordinationTimeoutError
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import Optional


_LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope='session')
def iso_scheduling(
    tmp_path_factory: pytest.TempPathFactory,
    testrun_uid: str,
    worker_id: str
) -> IsoSchedulingFixture:
    """A session-scoped pytest fixture for coordinating setup/teardown of test
    scope/class which is executing under isoscope scheduling.

    Based on the filelock idea described in section
    "Making session-scoped fixtures execute only once" of
    https://pytest-xdist.readthedocs.io/en/stable/how-to.html.

    NOTE: Each XDist remote worker is running its own Pytest Session, so we want
    only the worker that starts its session first to execute the setup logic and
    only the worker that finishes its session last to execute the teardown logic
    using a form of distributed coordination. This way, setup is executed exactly
    once before any worker executes any of the scope's tests, and teardown is
    executed only after the last worker finishes test execution.

    USAGE EXAMPLE:

        ```
        from __future__ import annotations
        from typing import TYPE_CHECKING
        import pytest

        if TYPE_CHECKING:
            from xdist.iso_scheduling_utils import (
                IsoSchedulingFixture,
                DistributedSetupContext,
                DistributedTeardownContext
            )

        class TestSomething:

            @classmethod
            @pytest.fixture(scope='class', autouse=True)
            def distributed_setup_and_teardown(
                    cls,
                    iso_scheduling: IsoSchedulingFixture:
                    request: pytest.FixtureRequest):

                # Distributed Setup and Teardown
                with iso_scheduling.coordinate_setup_teardown(
                        setup_request=request) as coordinator:
                    # Distributed Setup
                    coordinator.maybe_call_setup(cls.patch_system_under_test)

                    try:
                        # Yield control back to the XDist Worker to allow the
                        # test cases to run
                        yield
                    finally:
                        # Distributed Teardown
                        coordinator.maybe_call_teardown(cls.revert_system_under_test)

            @classmethod
            def patch_system_under_test(
                    cls,
                    setup_context: DistributedSetupContext) -> None:
                # Initialize the System Under Test for all the test cases in
                # this test class and store state in `setup_context.client_dir`.

            @classmethod
            def revert_system_under_test(
                    cls,
                    teardown_context: DistributedTeardownContext)
                # Fetch state from `teardown_context.client_dir` and revert
                # changes made by `patch_system_under_test()`.

            def test_case1(self)
                ...

            def test_case2(self)
                ...

            def test_case3(self)
                ...
        ```

    :param tmp_path_factory: (pytest fixture) interface for temporary
        directories and files.
    :param testrun_uid: (pytest-xdist fixture) Unique id of the current test
        run. This value is common to all XDist worker Pytest Sessions in the
        current test run.
    :param worker_id: (pytest-xdist fixture) Remote XDist worker ID which is
        executing this Pytest Session.
    :return: A callable that takes no args and returns a context manager which
        yields an instance of `DistributedSetupCoordinator` for the current
        Pytest Session.
    """
    return _IsoSchedulingFixtureImpl(tmp_path_factory=tmp_path_factory,
                                     testrun_uid=testrun_uid,
                                     worker_id=worker_id)


class _IsoSchedulingFixtureImpl(IsoSchedulingFixture):
    """Context manager yielding a new instance of the implementation of the
    `DistributedSetupCoordinator` interface.

    An instance of _IsoSchedulingFixtureImpl is returned by our pytest
    fixture `iso_scheduling`.
    """
    # pylint: disable=too-few-public-methods

    def __init__(self,
                 tmp_path_factory: pytest.TempPathFactory,
                 testrun_uid: str,
                 worker_id: str):
        """
        :param tmp_path_factory: pytest interface for temporary directories.
        :param testrun_uid: Unique id of the current test run. This value is
            common to all XDist worker Pytest Sessions in the current test run.
        :param worker_id: Remote XDist worker ID which is executing this Pytest
            Session. NOTE: Each XDist remote worker is running its own Pytest
            Session for the subset of test cases assigned to it.
        """
        self._tmp_path_factory = tmp_path_factory
        self._testrun_uid = testrun_uid
        self._worker_id = worker_id

    @contextlib.contextmanager
    def coordinate_setup_teardown(
        self,
        setup_request: pytest.FixtureRequest
    ) -> Generator[DistributedSetupCoordinator, None, None]:
        """Context manager that yields an instance of
        `DistributedSetupCoordinator` for distributed coordination of Setup
        and Teardown.

        NOTE: In python3.9 and later, a more appropriate return type would be
         `contextlib.AbstractContextManager[DistributedSetupCoordinator]`.

        :param setup_request: Value of the pytest `request` fixture obtained
            directly by the calling setup-teardown fixture.
        """
        # __enter__
        coordinator = _DistributedSetupCoordinatorImpl(
            setup_request=setup_request,
            tmp_path_factory=self._tmp_path_factory,
            testrun_uid=self._testrun_uid,
            worker_id=self._worker_id)

        # Yield control to the managed code block
        yield coordinator

        # __exit__
        # We can do some cleanup or validation here, but nothing for now


class _DistributedSetupCoordinatorImpl(DistributedSetupCoordinator):
    """Distributed scope/class setup/teardown coordination for isoscope
    scheduling.

    NOTE: do not instantiate this class directly. Use the
    `iso_scheduling` fixture instead!

    """
    _DISTRIBUTED_SETUP_ROOT_DIR_LINK_NAME = 'distributed_setup'

    def __init__(self,
                 setup_request: pytest.FixtureRequest,
                 tmp_path_factory: pytest.TempPathFactory,
                 testrun_uid: str,
                 worker_id: str):
        """
        :param setup_request: Value of the pytest `request` fixture obtained
            directly by the calling setup-teardown fixture.
        :param tmp_path_factory: Pytest interface for temporary directories and
            files.
        :param testrun_uid: Unique id of the current test run.
            This is common to all XDist worker Pytest Sessions in the
            current test run. NOTE: each XDist worker is running its own Pytest
            Session.
        :param worker_id: Remote XDist worker ID which is executing this Pytest
            Session.
        """
        self._setup_request: pytest.FixtureRequest = setup_request

        # NOTE: `tmp_path_factory.getbasetemp()` returns worker-specific temp
        # directory. `tmp_path_factory.getbasetemp().parent` is common to all
        # workers in the current PyTest test run.
        self._root_context_base_dir: pathlib.Path = (
                tmp_path_factory.getbasetemp().parent
                / self._DISTRIBUTED_SETUP_ROOT_DIR_LINK_NAME
                / testrun_uid)

        self._worker_id: str = worker_id

        self._setup_context: Optional[DistributedSetupContext] = None
        self._teardown_context: Optional[DistributedTeardownContext] = None

    def maybe_call_setup(
        self,
        setup_callback: Callable[[DistributedSetupContext], None],
        timeout: float = DistributedSetupCoordinator.DEFAULT_TIMEOUT_SEC
    ) -> None:
        """Invoke the Setup callback only if distributed setup has not been
        performed yet from any other XDist worker for your test scope.
        Process-safe.

        Call `maybe_call_setup` from the pytest setup-teardown fixture of your
        isoscope-scheduled test (typically test class) if it needs to
        initialize a resource which is common to all of its test cases which may
        be executing in different XDist worker processes (such as a subnet in
        `subnet.xml`).

        `maybe_call_setup` MUST ALWAYS be called in conjunction with
        `maybe_call_teardown`.

        :param setup_callback: Callback for performing Setup that is common to
            the pytest scope from which `maybe_call_setup` is invoked.
        :param timeout: Lock acquisition timeout in seconds

        :return: An instance of `DistributedSetupContext` which MUST be passed
            in the corresponding call to `maybe_call_teardown`.

        :raise CoordinationTimeoutError: If attempt to acquire the lock times out.
        """
        # `maybe_call_setup()` may be called only once per instance of
        # `_SetupCoordinator`
        assert self._setup_context is None, \
            f'maybe_call_setup()` already called {self._setup_context=}'

        node_path = self._setup_request.node.path

        root_context_dir: pathlib.Path = (
            self._root_context_base_dir
            / node_path.relative_to(node_path.root)
            / self._setup_request.node.name
        )

        with _DistributedSetupCoordinationImpl.acquire_distributed_setup(
                root_context_dir=root_context_dir,
                worker_id=self._worker_id,
                setup_request=self._setup_request,
                timeout=timeout) as setup_context:
            self._setup_context = setup_context
            if self._setup_context.distributed_setup_allowed:
                setup_callback(self._setup_context)

    def maybe_call_teardown(
        self,
        teardown_callback: Callable[[DistributedTeardownContext], None],
        timeout: float = DistributedSetupCoordinator.DEFAULT_TIMEOUT_SEC
    ) -> None:
        """Invoke the Teardown callback only in when called in the context of
        the final XDist Worker process to have finished the execution of the
        tests for your test scope. Process-safe.

        Call `maybe_call_teardown` from the pytest setup-teardown fixture of
        your isoscope-scheduled test (typically test class) if it needs to
        initialize a resource which is common to all of its test cases which may
        be executing in different XDist worker processes (such as a subnet in
        `subnet.xml`).

        NOTE: `maybe_call_teardown` MUST ALWAYS be called in conjunction with
        `maybe_call_setup`.

        :param teardown_callback: Callback for performing Teardown that is
            common to the pytest scope from which `maybe_call_teardown` is
            invoked.
        :param timeout: Lock acquisition timeout in seconds

        :raise CoordinationTimeoutError: If attempt to acquire the lock times out.
        """
        # Make sure `maybe_call_setup()` was already called on this instance
        # of `_SetupCoordinator`
        assert self._setup_context is not None, \
            f'maybe_call_setup() not called yet {self._setup_context=}'

        # Make sure `maybe_call_teardown()` hasn't been called on this instance
        # of `_SetupCoordinator` yet
        assert self._teardown_context is None, \
            f'maybe_call_teardown() already called {self._teardown_context=}'

        with _DistributedSetupCoordinationImpl.acquire_distributed_teardown(
                setup_context=self._setup_context,
                timeout=timeout) as teardown_context:
            self._teardown_context = teardown_context
            if self._teardown_context.distributed_teardown_allowed:
                teardown_callback(self._teardown_context)


def _map_file_lock_exception(f: Callable):
    """Decorator: map `FileLock` exceptions of interest to our own exceptions.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except filelock.Timeout as err:
            raise CoordinationTimeoutError(
                f'Another instance of this test scope/class is holding the '
                f'lock too long or timeout value is too short: {err}') \
                from err

    return wrapper


class _DistributedSetupCoordinationImpl:
    """Low-level implementation of Context Managers for Coordinating
    Distributed Setup and Teardown for users of isoscope scheduling.
    """
    _ROOT_STATE_FILE_NAME = 'root_state.json'
    _ROOT_LOCK_FILE_NAME = 'lock'

    class DistributedState:
        """State of the Distributed Setup-Teardown Coordination.
        """
        def __init__(self, setup_count, teardown_count):
            self.setup_count = setup_count
            self.teardown_count = teardown_count

        def __repr__(self):
            return f'<{self.__class__.__qualname__}: ' \
                   f'setup_count={self.setup_count}; ' \
                   f'teardown_count={self.teardown_count}>'

        @classmethod
        def load_from_file_path(
            cls,
            state_file_path: pathlib.Path
        ) -> _DistributedSetupCoordinationImpl.DistributedState:
            """Load the state instance from the given file path.

            :param state_file_path:
            :return: Instance of the state constructed from the contents of the
                given file.
            """
            return cls(**json.loads(state_file_path.read_text()))

        @property
        def as_json_kwargs_dict(self) -> dict:
            """
            :return: JSON-compatible representation of the instance that is also
                suitable for constructing the instance after fetching from file.
                as in the following example:

                ```
                state_kwargs = json.load(open(state_file_path))
                DistributedState(**state_kwargs)
                ```
            """
            return {
                'setup_count': self.setup_count,
                'teardown_count': self.teardown_count
            }

        def save_to_file_path(self, state_file_path: pathlib.Path) -> None:
            """Save this state instance to the given file path.

            :param state_file_path:
            :return:
            """
            state_file_path.write_text(json.dumps(self.as_json_kwargs_dict))

    @classmethod
    @contextlib.contextmanager
    @_map_file_lock_exception
    def acquire_distributed_setup(
        cls,
        root_context_dir: pathlib.Path,
        worker_id: str,
        setup_request: pytest.FixtureRequest,
        timeout: float
    ) -> Generator[DistributedSetupContext, None, None]:
        """Low-level implementation of Context Manager for Coordinating
        Distributed Setup for isoscope scheduling.

        :param root_context_dir: Scope/class-specific root directory for
            saving this context manager's state. This directory is common to
            all xdist workers for the given test scope/class.
        :param worker_id: XDist worker ID for logging.
        :param setup_request: Value of the pytest `request` fixture obtained
            directly by the calling setup-teardown fixture.
        :param timeout: Lock acquisition timeout in seconds

        :raise CoordinationTimeoutError: If attempt to acquire the lock times out.
        """
        #
        # Before control passes to the managed code block
        #
        setup_context = DistributedSetupContext(
            setup_allowed=False,
            root_context_dir=root_context_dir,
            worker_id=worker_id,
            setup_request=setup_request)

        state_file_path = cls._get_root_state_file_path(root_context_dir)

        # Acquire resource
        with filelock.FileLock(
                str(cls._get_root_lock_file_path(root_context_dir)),
                timeout=timeout):
            if state_file_path.is_file():
                state = cls.DistributedState.load_from_file_path(
                    state_file_path)
                # We never save state with setup_count <= 0
                assert state.setup_count > 0, \
                    f'acquire_distributed_setup: non-positive setup ' \
                    f'count read from state file - {state_file_path=}; ' \
                    f'{worker_id=}; {state}'
                # No Teardowns should be executing before all Setups
                # complete
                assert state.teardown_count == 0, \
                    f'acquire_distributed_setup: non-zero teardown ' \
                    f'count read from state file - {state_file_path=}; ' \
                    f'{worker_id=}; {state}'
            else:
                # State file not created yet
                state = cls.DistributedState(setup_count=0,
                                             teardown_count=0)

            state.setup_count += 1

            setup_context.distributed_setup_allowed = state.setup_count == 1

            #
            # Yield control to the managed code block
            #
            _LOGGER.info(  # pylint: disable=logging-fstring-interpolation
                f'acquire_distributed_setup: yielding control to '
                f'managed block - {worker_id=}; {setup_context=}')
            yield setup_context

            #
            # Control returns from the managed code block, unless control
            # left managed code with an exception
            #

            # Save state to file
            state.save_to_file_path(state_file_path)

    @classmethod
    @contextlib.contextmanager
    @_map_file_lock_exception
    def acquire_distributed_teardown(
        cls,
        setup_context: DistributedSetupContext,
        timeout: float
    ) -> Generator[DistributedTeardownContext, None, None]:
        """Low-level implementation of Context Manager for Coordinating
        Distributed Teardown for the isoscope scheduling.

        :param setup_context: The instance of `DistributedSetupContext` that was
            yielded by the corresponding use of the
            `_distributed_setup_permission` context manager.
        :param timeout: Lock acquisition timeout in seconds

        :raise CoordinationTimeoutError: If attempt to acquire the lock times out.
        """
        #
        # Before control passes to the managed code block
        #
        teardown_context = DistributedTeardownContext(
            teardown_allowed=False,
            setup_context=setup_context)

        # NOTE: Friend-of-class protected member access
        root_context_dir = teardown_context._root_context_dir  # pylint: disable=protected-access

        worker_id = teardown_context.worker_id

        state_file_path = cls._get_root_state_file_path(root_context_dir)

        # Acquire resource
        with filelock.FileLock(
                str(cls._get_root_lock_file_path(root_context_dir)),
                timeout=timeout):
            if state_file_path.is_file():
                state = cls.DistributedState.load_from_file_path(
                    state_file_path)
                assert state.setup_count > 0, (
                    f'acquire_distributed_teardown: non-positive '
                    f'setup_count read from state file - {state_file_path=}; '
                    f'{worker_id=}; {state.setup_count=} <= 0; {state}')
                assert state.teardown_count < state.setup_count, (
                    f'acquire_distributed_teardown: teardown_count '
                    f'already >= setup_count read from state file - '
                    f'{state_file_path=}; {worker_id=}; '
                    f'{state.teardown_count=} >= {state.setup_count=}')
            else:
                raise RuntimeError(
                    f'acquire_distributed_teardown: state file not found: '
                    f'{state_file_path=}; {worker_id=}')

            state.teardown_count += 1

            teardown_context.distributed_teardown_allowed = (
                    state.teardown_count == state.setup_count)

            #
            # Yield control to the managed code block
            #
            _LOGGER.info(  # pylint: disable=logging-fstring-interpolation
                f'acquire_distributed_teardown: yielding control to '
                f'managed block - {worker_id=}; {teardown_context=}')
            yield teardown_context

            #
            # Control returns from the managed code block, unless control left
            # managed code with an exception
            #

            # Save state to file
            state.save_to_file_path(state_file_path)

    @classmethod
    def _get_root_state_file_path(
        cls,
        root_state_dir: pathlib.Path
    ) -> pathlib.Path:
        """Return the path of the file for storing the root state, creating all
        parent directories if they don't exist yet.

        :param root_state_dir: Directory where root state should be stored.
        :return: The file path of the root state.
        """
        root_state_dir.mkdir(parents=True, exist_ok=True)
        return root_state_dir / cls._ROOT_STATE_FILE_NAME

    @classmethod
    def _get_root_lock_file_path(
        cls,
        root_lock_dir: pathlib.Path
    ) -> pathlib.Path:
        """Return the path of the lock file, creating all parent directories if
        they don't exist yet.

        :param root_lock_dir: Directory where lock file should be stored.
        :return: The file path of the lock file.
        """
        root_lock_dir.mkdir(parents=True, exist_ok=True)
        return root_lock_dir / cls._ROOT_LOCK_FILE_NAME
