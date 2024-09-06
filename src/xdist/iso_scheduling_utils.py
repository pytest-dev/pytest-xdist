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

"""Utilities for supporting isoscope scheduling.

NOTE: These utilities are NOT compatible with any other xdist schedulers.

See also `iso_scheduling_plugin.py` for fixtures specific to isoscope scheduling.
"""

from __future__ import annotations

import abc
import pathlib
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator

    import pytest


class CoordinationTimeoutError(Exception):
    """When attempt to acquire the distributed lock times out."""


class IsoSchedulingFixture(abc.ABC):
    """Interface of the context manager which is returned by our pytest fixture
    `iso_scheduling`.

    An instance of the implementation of this interface is a context manager
    which yields an instance of  the implementation of the
    `DistributedSetupCoordinator` interface.
    """

    # pylint: disable=too-few-public-methods

    @abc.abstractmethod
    def coordinate_setup_teardown(
        self, setup_request: pytest.FixtureRequest
    ) -> Generator[DistributedSetupCoordinator, None, None]:
        """Context manager that yields an instance of
        `DistributedSetupCoordinator` for distributed coordination of Setup
        and Teardown.

        NOTE: In python3.9 and later, a more appropriate return type would be
         `contextlib.AbstractContextManager[DistributedSetupCoordinator]`.

        :param setup_request: Value of the pytest `request` fixture obtained
            directly by the calling setup-teardown fixture.
        """


class DistributedSetupCoordinator(abc.ABC):
    """Interface for use with the `iso_scheduling` fixture for
    distributed coordination of Setup and Teardown workflows. For example,
    inserting a subnet into `subnet.xml` and reverting it upon Teardown.

    The `iso_scheduling` fixture returns an implementation of this
    interface. See the `iso_scheduling` fixture in
    `iso_scheduling_plugin.py` for additional information.

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
    """

    # Default lock acquisition timeout in seconds
    DEFAULT_TIMEOUT_SEC = 90

    @abc.abstractmethod
    def maybe_call_setup(
        self,
        setup_callback: Callable[[DistributedSetupContext], None],
        timeout: float = DEFAULT_TIMEOUT_SEC,
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

        :raise CoordinationTimeoutError: If attempt to acquire the lock times
            out.
        """

    @abc.abstractmethod
    def maybe_call_teardown(
        self,
        teardown_callback: Callable[[DistributedTeardownContext], None],
        timeout: float = DEFAULT_TIMEOUT_SEC,
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

        :raise CoordinationTimeoutError: If attempt to acquire the lock times
            out.
        """


class _DistributedSetupTeardownContextMixin:  # pylint: disable=too-few-public-methods
    """Mixin for `DistributedSetupContext` and DistributedTeardownContext`."""

    # Expected instance members in derived class
    _root_context_dir: pathlib.Path
    _setup_node_name: str

    _CLIENT_SUBDIRECTORY_LINK = "client-workspace"

    @property
    def client_dir(self) -> pathlib.Path:
        """
        :return: The directory where client should save/retrieve
            client-specific state, creating the directory if not already
            created.
        """
        client_dir_path = self._root_context_dir / self._CLIENT_SUBDIRECTORY_LINK
        client_dir_path.mkdir(parents=True, exist_ok=True)

        return client_dir_path


class DistributedSetupContext(_DistributedSetupTeardownContextMixin):
    """Setup context provided by the `acquire_distributed_setup` context
    manager.
    """

    def __init__(
        self,
        setup_allowed: bool,
        root_context_dir: pathlib.Path,
        worker_id: str,
        setup_request: pytest.FixtureRequest,
    ):
        """
        :param setup_allowed: Whether distributed setup may be performed by the
            current process.
        :param root_context_dir: Scope/class-specific root directory for
            saving this context manager's state. This directory is common to
            all xdist workers for the given test scope/class.
        :param worker_id: XDist worker ID which is executing tests in the
            current process.
        :param setup_request: Value of the pytest `request` fixture obtained
            directly by the calling setup-teardown fixture.
        """
        self._root_context_dir = root_context_dir

        # XDist worker ID which is executing tests in the current process
        self.worker_id = worker_id

        # Pytest setup node name (e.g., name of test class being setup)
        self._setup_node_name = setup_request.node.name

        # Managed code MUST obey the value of `distributed_setup_allowed`!
        #
        # If True, the client is designated for performing the distributed Setup
        # actions.
        # If False, the client MUST NOT perform the distributed Setup actions,
        # in which case someone else has already performed them
        self.distributed_setup_allowed = setup_allowed

    def __repr__(self) -> str:
        return (
            f"< {self.__class__.__name__}: "
            f"node_name={self._setup_node_name}; "
            f"setup_allowed={self.distributed_setup_allowed}; "
            f"worker_id={self.worker_id}; "
            f"client_dir={self.client_dir} >"
        )


class DistributedTeardownContext(_DistributedSetupTeardownContextMixin):
    """Teardown context provided by the `acquire_distributed_teardown` context
    manager.
    """

    def __init__(self, teardown_allowed: bool, setup_context: DistributedSetupContext):
        """
        :param teardown_allowed: Whether Distributed Teardown may be performed
            by the current process.
        :param setup_context: Setup Context from the Setup phase.
        """
        # Managed code MUST obey the value of `distributed_teardown_allowed`!
        #
        # If True, the client is designated for performing the distributed
        # Teardown actions.
        # If False, the client MUST NOT perform the distributed Teardown
        # actions, in which case someone else will perform them.
        self.distributed_teardown_allowed = teardown_allowed

        # NOTE: Friend-of-class protected member access
        self._root_context_dir = setup_context._root_context_dir  # pylint: disable=protected-access

        # XDist worker ID which is executing tests in the current process
        self.worker_id = setup_context.worker_id

        # NOTE: Friend-of-class protected member access
        self._setup_node_name = setup_context._setup_node_name  # pylint: disable=protected-access

    def __repr__(self) -> str:
        return (
            f"< {self.__class__.__name__}: "
            f"node_name={self._setup_node_name}; "
            f"teardown_allowed={self.distributed_teardown_allowed}; "
            f"worker_id={self.worker_id}; "
            f"client_dir={self.client_dir} >"
        )
