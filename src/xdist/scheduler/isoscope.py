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

"""
Implementation of the Distributed Scope Isolation scheduler for pytest-xdist.

Properties of this scheduler:
    1. Executes one test scope/class at a time.
    2. Distributes tests of the executing scope/class to the configured XDist 
       Workers.
    3. Guarantees that the Setup of the executing scope/class completes in all
       XDist Workers BEFORE any of those Workers start processing the 
       Teardown of that test scope/class.
    4. Guarantees that the Teardown phase of the executing test scope/class
       completes in all XDist Workers before the Setup phase begins for the
       next test scope/class.

Credits:
* Implementation of `_split_scope()` and public method documentation in
  DistScopeIsoScheduling:
    - borrowed from the builtin `loadscope` scheduler
"""  # pylint: disable=too-many-lines
from __future__ import annotations

from collections import OrderedDict
import enum
from math import ceil
import random
from typing import TYPE_CHECKING

import pytest
from _pytest.runner import CollectReport
from xdist.report import report_collection_diff
from xdist.workermanage import parse_spec_config


if TYPE_CHECKING:
    from typing import Optional
    from collections.abc import Generator, Iterable, ValuesView
    import xdist.remote
    from xdist.workermanage import WorkerController


class DistScopeIsoScheduling:  # pylint: disable=too-many-instance-attributes
    """Distributed Scope Isolation Scheduling: Implement scheduling across
    remote workers, distributing and executing one scope at a time, such that
    each scope is executed in isolation from tests in other scopes.

    Ensures that all tests in a given scope complete execution before starting
    execution of the tests in the subsequent scope. This way, scoped
    setup/teardown fixtures can be orchestrated to execute global setup/teardown
    once per scope (vs. per worker) using `FileLock` or similar for
    coordination.
    """
    class _State(str, enum.Enum):
        # Waiting for scheduler to be ready to distribute the next Scope. When
        # the Workset Queue is NOT empty AND all workers which are shutting down
        # reach zero pending tests AND all other workers have no more than one
        # pending tests AND at least one worker is available for the distribution
        # of the next scope, then transition to `ACTIVATE_SCOPE`
        WAIT_READY_TO_ACTIVATE_SCOPE = 'WAIT-READY-TO-ACTIVATE-SCOPE'

        # Activate (i.e., distribute) tests from the next Scope, if any. If a
        # scope was distributed, then transition to `WAIT_READY_TO_FENCE`.
        # Workers that are available for distribution are those that already
        # contain a fence test belonging to this scope as well as empty workers
        # which are not shutting down. Workers with matching fence tests have
        # priority over empty workers (to satisfy that "at least two
        # active-Scope tests per worker" Rule)
        ACTIVATE_SCOPE = 'ACTIVATE-SCOPE'

        # Waiting for scheduler to be ready to fence the active (i.e.,
        # distributed) scope. Wait until each non-empty worker has only one
        # pending test remaining. Then, if at least one of those non-empty
        # and non-shutting-down workers contains a pending test belonging to the
        # current active Scope, transition to the `FENCE` state. If none of
        # these workers contains a pending test belonging to the current active
        # Scope, then reset current active scope and transition to
        # `WAIT-READY-TO-ACTIVATE-SCOPE` (this means that all workers containing
        # active-Scope tests crashed)
        WAIT_READY_TO_FENCE = 'WAIT-READY-TO-FENCE'

        # Fence the workers containing the final active-Scope tests in
        # order to allow those final pending tests to complete execution. Fence
        # tests are dequeued from subsequent scopes, making sure that those
        # scopes will be able to satisfy the "at least two active-Scope tests
        # per worker" Rule when they are activated. When subsequent scopes run
        # out of tests for fencing, then send "shutdown" to the balance of those
        # workers instead of a fence test. Finally, transition to
        # `WAIT_READY_TO_ACTIVATE_SCOPE`.
        FENCE = 'FENCE'

    def __init__(self, config: pytest.Config,
                 log: xdist.remote.Producer):
        self._config = config
        self._log: xdist.remote.Producer = log.distscopeisosched

        # Current scheduling state
        self._state: DistScopeIsoScheduling._State = \
            self._State.WAIT_READY_TO_ACTIVATE_SCOPE

        # Scope ID of tests that are currently executing; `None` prior to the
        # initial distribution
        self._active_scope_id: Optional[str] = None

        # The initial expected number of remote workers taking part.
        # The actual number of workers will vary during the scheduler's
        # lifetime as nodes are added by the DSession as they are brought up and
        # removed either because of a dead node or normal shutdown.  This number
        # is primarily used to know when the initial collection is completed.
        self._expected_num_workers = len(parse_spec_config(config))

        # The final list of test IDs collected by all nodes once
        # it's validated to be identical between all the nodes. The validation
        # is performed once the number of registered node collections reaches
        # `_expected_num_workers`. It is initialized to None and then updated
        # after validation succeeds.
        self._official_test_collection: Optional[tuple[str]] = None
        # Remote worker node having `_official_test_collection` as its test
        # collection (for reporting failed collection validations)
        self._official_test_collection_node: Optional[WorkerController] = None

        # Ordered collection of Scope Worksets. Each Scope Workset is an ordered
        # collection of tests belonging to the given scope. Initially empty,
        # it will be populated once we establish the final test collection
        # (see `_official_test_collection`).
        self._workset_queue = _WorksetQueue()

        # Workers available for test distribution (aka, active workers). It's
        # the mapping of `WorkerController` nodes to the corresponding
        # `_WorkerProxy` instances. Initially empty, it will be populated by
        # our `add_node_collection` implementation as it's called by xdist's
        # `DSession` and the corresponding test collection passes validation.
        self._worker_by_node: \
            OrderedDict[WorkerController, _WorkerProxy] = OrderedDict()

        # Workers pending validation of their Test collections that have not
        # been admitted to `_worker_by_node` yet.
        #
        # A worker is added to `_pending_worker_by_node` with its collection
        # value initialized to `None` when xdist Controller invokes
        # `add_node()`.
        #
        # The worker's test collection value is updated when
        # `add_node_collection` receives the corresponding test collection.
        #
        # A worker is moved from `_pending_worker_by_node` to `_worker_by_node`
        # when its collection is validated.
        #
        # A worker is removed from `_pending_worker_by_node` when the xdist
        # controller invokes `remove_node()` with the corresponding node.
        self._pending_worker_by_node: \
            OrderedDict[WorkerController, _WorkerProxy] = OrderedDict()

    @property
    def nodes(self) -> list[WorkerController]:
        """A new list of all active `WorkerController` nodes.

        Called by xdist `DSession`.
        """
        return (list(self._worker_by_node.keys())
                + list(self._pending_worker_by_node.keys()))

    @property
    def collection_is_completed(self) -> bool:
        """Indication whether initial test collection is completed.

        Indicates that all initial participating remote workers have finished
        test collection.

        Called by xdist `DSession`:
            - when it gets notified that a remote worker completed collection as
              a prelude to calling our `schedule()` method.
        """
        return self._official_test_collection is not None

    @property
    def tests_finished(self) -> bool:
        """True if all tests have completed execution.

        Called by xdist `DSession`:
            - periodically as a prelude to triggering shutdown
        """
        if not self.collection_is_completed:
            return False

        if self.has_pending:
            return False

        return True

    @property
    def has_pending(self) -> bool:
        """True if there are pending test items.

        This indicates that collection has finished and nodes are still
        processing test items, so this can be thought of as
        "the scheduler is active".

        Called by xdist `DSession`.
        """
        if not self._workset_queue.empty:
            return True

        for worker in self._workers:
            if not worker.empty:
                return True

        return False

    def add_node(self, node: WorkerController):
        """Add a new node to the scheduler's pending worker collection.

        The node will be activated and assigned tests to be executed only after
        its test collection is received by `add_node_collection()` and
        validated.

        Called by the ``DSession.worker_workerready`` hook
            - when it successfully bootstraps a new remote worker.
        """
        self._log(f'Registering remote worker node {node}')

        assert node not in self._pending_worker_by_node, \
            f'{node=} already in pending workers'

        self._pending_worker_by_node[node] = _WorkerProxy(node)

    def remove_node(self, node: WorkerController) -> Optional[str]:
        """Remove a Remote Worker node from the scheduler.

        This should be called either when the node crashed or at node shutdown
        time.

        NOTE: If the worker still has pending tests assigned to it, this
        method will return those pending tests back to the Workset Queue for
        later execution.

        IMPORTANT: If the remote worker experienced an ungraceful shutdown, it
        may create an imbalance between the execution of the setup and teardown
        fixture(s). THIS MAY LEAVE THE SYSTEM UNDER TEST IN AN UNEXPECTED STATE,
        COMPROMISING EXECUTION OF ALL SUBSEQUENT TESTS IN CURRENT AND FUTURE
        SESSIONS.

        Called by the hooks:

            - ``DSession.worker_workerfinished``.
            - ``DSession.worker_errordown``.

        :return: the test ID being executed while the node crashed or None if
            the node has no more pending items.

        :raise KeyError: if the Remote Worker node has not been registered with
            the scheduler. (NOTE: xdist's `DSession` expects this behavior)
        """
        self._log(f'Removing remote worker node {node}')

        if node in self._pending_worker_by_node:
            # Worker was not admitted to active workers yet, remove it from the
            # pending worker collection.
            self._pending_worker_by_node.pop(node)
            assert node not in self._worker_by_node, \
                f'{node=} in both pending and active workers'
            return None

        # Worker was admitted to active workers already

        worker = self._worker_by_node.pop(node)

        if worker.empty:
            return None

        # The remote worker node crashed; identify the test that crashed
        #
        # IMPORTANT: The remote worker might have experienced an ungraceful
        # shutdown, possibly creating an imbalance between the execution of
        # the setup and teardown fixture(s). THIS MAY LEAVE THE
        # SYSTEM UNDER TEST IN AN UNEXPECTED STATE, COMPROMISING EXECUTION OF
        # ALL SUBSEQUENT TESTS IN CURRENT AND FUTURE SESSIONS.

        first_pending_test = worker.head_pending_test
        crashed_test_id = first_pending_test.test_id

        self._log(f'Remote Worker {repr(worker)} shut down ungracefully. It '
                  f'may have crashed while executing the pending test '
                  f'{first_pending_test}. '
                  f'NOTE: The ungraceful shutdown may create an imbalance '
                  f'between the execution of the setup and teardown '
                  f'fixture(s). THIS MAY LEAVE THE SYSTEM UNDER TEST IN AN '
                  f'UNEXPECTED STATE, COMPROMISING EXECUTION OF ALL SUBSEQUENT '
                  f'TESTS IN CURRENT AND FUTURE SESSIONS.')

        # Return the pending tests back to the workset queue
        for test in worker.release_pending_tests():
            self._workset_queue.add_test(test)

        return crashed_test_id

    def add_node_collection(self, node: WorkerController,
                            collection: list[str]):
        """Register the collected test items from a Remote Worker node.

        If the official test collection has been established already, validate
        the given worker's test collection against the official node; if valid,
        then activate the worker, making it available for scheduling.

        If the official test collection has not been established yet, and we
        now have at least the expected number of pending workers with a test
        collection, and all these test collections are identical, then:
            1. Record the reference node and collection for subsequent
               validations of future worker collections
            2. Activate all these workers, making them available for scheduling.
            2. Organize tests into a queue of worksets grouped by test scope ID

        Called by the hook:

        - ``DSession.worker_collectionfinish``.
        """
        self._log(f'Adding collection for node {node}: {len(collection)=}')

        # Check that add_node() was called on the node before
        assert node in self._pending_worker_by_node, \
            f'Received test collection for {node=} which is not in pending ' \
            f'workers'

        worker = self._pending_worker_by_node[node]

        collection = worker.collection = tuple(collection)

        if self.collection_is_completed:
            # A new node has been added after final collection establishment,
            # perhaps an original one died.

            # Check that the new collection matches the official collection
            if self._do_two_nodes_have_same_collection(
                    reference_node=self._official_test_collection_node,
                    reference_collection=self._official_test_collection,
                    node=node,
                    collection=collection):
                # The worker's collection is valid, so activate the new worker
                self._pending_worker_by_node.pop(node)
                self._worker_by_node[node] = worker

            return

        #
        # The final collection has not been established yet
        #

        # Check if we now have enough collections to establish a final one

        # Get all pending workers with registered test collection
        w: _WorkerProxy
        workers_with_collection = [
            w for w in self._pending_worker_by_node.values()
            if w.collection is not None]

        if len(workers_with_collection) < self._expected_num_workers:
            # Not enough test collections registered yet
            return

        # Check that all nodes collected the same tests
        same_collection = True
        reference_worker = workers_with_collection[0]
        for pending_worker in workers_with_collection[1:]:
            if not self._do_two_nodes_have_same_collection(
                    reference_node=reference_worker.node,
                    reference_collection=reference_worker.collection,
                    node=pending_worker.node,
                    collection=pending_worker.collection):
                same_collection = False

        if not same_collection:
            self._log(
                '**Different tests collected, aborting worker activation**')
            return

        # Collections are identical!

        # Record the reference node and collection for subsequent validations of
        # future worker collections
        self._official_test_collection_node = reference_worker.node
        self._official_test_collection = reference_worker.collection

        # Activate these workers
        for worker in workers_with_collection:
            # Activate the worker
            self._pending_worker_by_node.pop(worker.node)
            self._worker_by_node[worker.node] = worker

        # Shuffle the tests to break any inherent ordering relationships for
        # distribution across workers (e.g., a sub-sequence of tests that are
        # particularly slow)
        all_tests = [
            _TestProxy(test_id=test_id, test_index=test_index)
            for test_index, test_id
            in enumerate(self._official_test_collection)]
        shuffled_test_collection = random.sample(all_tests, k=len(all_tests))

        # Organize tests into a queue of worksets grouped by test scope ID
        for test in shuffled_test_collection:
            self._workset_queue.add_test(test)

    def mark_test_complete(self, node: WorkerController, item_index: int,
                           duration):
        """Mark test item as completed by node and remove from pending tests
        in the worker and reschedule.

        Called by the hook:

        - ``DSession.worker_runtest_protocol_complete``.
        """
        # Suppress "unused parameter" warning
        assert duration is duration  # pylint: disable=comparison-with-itself

        worker = self._worker_by_node[node]

        if self._log.enabled:
            self._log(f'Marking test complete: '
                      f'test_id={self._official_test_collection[item_index]}; '
                      f'{item_index=}; {worker}')

        worker.handle_test_completion(test_index=item_index)

        self._reschedule_workers()

    def mark_test_pending(self, item):
        """Not supported"""
        raise NotImplementedError()

    def schedule(self):
        """Initiate distribution of the test collection.

        Initiate scheduling of the items across the nodes.  If this gets called
        again later it behaves the same as calling ``._reschedule()`` on all
        nodes so that newly added nodes will start to be used.

        If ``.collection_is_completed`` is True, this is called by the hook:

        - ``DSession.worker_collectionfinish``.
        """
        assert self.collection_is_completed, \
            'schedule() called before test collection completed'

        # Test collection has been completed, so reschedule if needed
        self._reschedule_workers()

    @staticmethod
    def split_scope(test_id: str) -> str:
        """Determine the scope (grouping) of a test ID (aka, "nodeid").

        There are usually 3 cases for a nodeid::

            example/loadsuite/test/test_beta.py::test_beta0
            example/loadsuite/test/test_delta.py::Delta1::test_delta0
            example/loadsuite/epsilon/__init__.py::epsilon.epsilon

        #. Function in a test module.
        #. Method of a class in a test module.
        #. Doctest in a function in a package.

        This function will group tests with the scope determined by splitting
        the first ``::`` from the right. That is, classes will be grouped in a
        single work unit, and functions from a test module will be grouped by
        their module. In the above example, scopes will be::

            example/loadsuite/test/test_beta.py
            example/loadsuite/test/test_delta.py::Delta1
            example/loadsuite/epsilon/__init__.py
        """
        return test_id.rsplit('::', 1)[0]

    @property
    def _workers(self) -> Iterable[_WorkerProxy]:
        """An iterable of all active worker proxies in this scheduler,
        including those that have initiated, but not yet completed shutdown.
        """
        return self._worker_by_node.values()

    def _reschedule_workers(self):
        """Distribute work to workers if needed at this time.
        """
        assert self._state is not None

        traversed_states = []
        previous_state = None
        while self._state != previous_state:
            # NOTE: This loop will terminate because completion of tests and
            # worker availability are reported outside the scope of this
            # function, and our state transitions are limited by those factors
            assert len(traversed_states) <= len(self._State), \
                f'Too many traversed states - {len(traversed_states)}: ' \
                f'{traversed_states}'
            traversed_states.append(self._state)

            previous_state = self._state

            if self._state is self._State.WAIT_READY_TO_ACTIVATE_SCOPE:
                self._handle_state_wait_ready_to_activate_scope()
            elif self._state is self._State.ACTIVATE_SCOPE:
                self._handle_state_activate_scope()
            elif self._state is self._State.WAIT_READY_TO_FENCE:
                self._handle_state_wait_ready_to_fence()
            elif self._state is self._State.FENCE:
                self._handle_state_fence()
            else:
                raise RuntimeError(f'Unhandled state: {self._state}')

    def _handle_state_wait_ready_to_activate_scope(self):
        """Handle the `WAIT_READY_TO_ACTIVATE_SCOPE` state.

        Waiting for scheduler to be ready to distribute the next Scope. When
        the Workset Queue is NOT empty AND all workers which are shutting down
        reach zero pending tests AND all other workers have no more than one
        pending tests AND at least one worker is available for the distribution
        of the next scope, then transition to `ACTIVATE_SCOPE`
        """
        assert self._state is self._State.WAIT_READY_TO_ACTIVATE_SCOPE, \
            f'{self._state=} != {self._State.WAIT_READY_TO_ACTIVATE_SCOPE}'

        if self._workset_queue.empty:
            # No more scopes are available
            return

        # First check if all workers satisfy the pending test thresholds
        for worker in self._workers:
            if worker.num_pending_tests > 1:
                # A worker has too many pending tests
                return
            if worker.shutting_down and worker.num_pending_tests != 0:
                # A worker is shutting down, but is not empty yet
                return

        # Check whether at least one worker is available for the next Scope.
        #
        # In the event none are available, we'll have to wait for crashed
        # worker(s) to be restarted.
        #
        # NOTE: xdist will either replace crashed workers or terminate the
        # session.

        next_scope_id = self._workset_queue.head_workset.scope_id
        if not self._get_workers_available_for_distribution(
                scope_id=next_scope_id):
            # No workers are available for distribution of the next scope.
            # It appears that some workers have crashed. xdist will either
            # replace crashed workers or terminate the session.
            if self._log.enabled:
                self._log(f'No workers are available for {next_scope_id=}, '
                          f'they likely crashed; staying in {self._state=}')
            return

        # Conditions are satisfied for transition to next state
        previous_state = self._state
        self._state = self._State.ACTIVATE_SCOPE
        self._log(f'Transitioned from {str(previous_state)} to '
                  f'{str(self._state)}')

    def _handle_state_activate_scope(self):
        """Handle the `ACTIVATE_SCOPE` state.

        Activate (i.e., distribute) tests from the next Scope, if any. If we
        distributed a scope, then transition to `WAIT_READY_TO_FENCE`.
        Workers that are available for distribution are those that already
        contain fence tests belonging to this scope as well as empty workers
        which are not shutting down. Workers with matching fence tests have
        priority over empty workers (to satisfy the "at least two
        active-Scope tests per worker" Rule)
        """
        assert self._state is self._State.ACTIVATE_SCOPE, \
            f'{self._state=} != {self._State.ACTIVATE_SCOPE}'

        # The previous state is responsible for ensuring that the workset queue
        # is not empty
        assert not self._workset_queue.empty, f'Empty {self._workset_queue}'

        workset = self._workset_queue.dequeue_workset()

        # Get workers that are available for distribution: those that already
        # contain a fence test belonging to this scope as well as empty workers
        # which are not shutting down
        available_workers = self._get_workers_available_for_distribution(
            scope_id=workset.scope_id)

        # The previous state is responsible for ensuring that workers are
        # available for this Scope
        assert available_workers, \
            f'No workers available for {workset.scope_id=} in {self._state=}'

        # Distribute the workset to the available workers
        self._distribute_workset(workset=workset, workers=available_workers)

        # Update Active Scope ID
        self._active_scope_id = workset.scope_id

        # Conditions are satisfied for transition to next state
        previous_state = self._state
        self._state = self._State.WAIT_READY_TO_FENCE
        self._log(f'Transitioned from {str(previous_state)} to '
                  f'{str(self._state)}. '
                  f'Activated scope={self._active_scope_id}')

    def _handle_state_wait_ready_to_fence(self):
        """Handle the `WAIT_READY_TO_FENCE` state.

        Waiting for scheduler to be ready to fence the active (i.e.,
        distributed) scope. Wait until each non-empty worker has only one
        pending test remaining. Then, if at least one of those non-empty
        and non-shutting-down workers contains a pending test belonging to the
        current active Scope, transition to the `FENCE` state. If none of
        these workers contains a pending test belonging to the current active
        Scope, then reset current active scope and transition to
        `WAIT-READY-TO-ACTIVATE-SCOPE` (this means that all workers containing
        active-Scope tests crashed)
        """
        assert self._state is self._State.WAIT_READY_TO_FENCE, \
            f'{self._state=} != {self._State.WAIT_READY_TO_FENCE}'

        assert self._active_scope_id is not None, \
            f'{self._active_scope_id=} is None'

        for worker in self._workers:
            if worker.num_pending_tests > 1:
                # A worker has too many pending tests
                return

        workers_to_fence = self._get_workers_ready_for_fencing(
            scope_id=self._active_scope_id)

        # Conditions are satisfied for transition to next state
        previous_state = self._state

        if workers_to_fence:
            # There are pending active-Scope tests that need to be fenced
            self._state = self._State.FENCE
        else:
            # No active-Scope tests pending, so nothing to fence. Their
            # worker(s) must have crashed?
            self._state = self._State.WAIT_READY_TO_ACTIVATE_SCOPE
            self._log(f'Nothing to fence! No active-scope tests pending - '
                      f'workers crashed? {self._active_scope_id=}')

        self._log(f'Transitioned from {str(previous_state)} to '
                  f'{str(self._state)}')

    def _handle_state_fence(self):
        """Handle the `FENCE` state.

        Fence the workers containing the final active-Scope tests in
        order to allow those final pending tests to complete execution. Fence
        tests are dequeued from subsequent scopes, making sure that those
        scopes will be able to satisfy the "at least two active-Scope tests
        per worker" Rule when they are activated. When subsequent scopes run
        out of tests for fencing, then send "shutdown" to the balance of those
        workers instead of a fence test. Finally, transition to
        `WAIT_READY_TO_ACTIVATE_SCOPE`.
        """
        assert self._state is self._State.FENCE, \
            f'{self._state=} is not {self._State.FENCE}'

        workers_to_fence = self._get_workers_ready_for_fencing(
            scope_id=self._active_scope_id)

        # The prior state should have ensured that there is at least one worker
        # that needs to be fenced
        assert workers_to_fence, \
            f'No workers ready to fence {self._active_scope_id=} ' \
            f'in {self._state=}; ' \
            f'active workers: {[w.verbose_repr() for w in self._workers]}'

        # We will take Fence tests from subsequent worksets.
        # NOTE: A given workset may be used to fence multiple preceding active
        # Scopes
        fence_item_generator = self._generate_fence_items(
            source_worksets=self._workset_queue.worksets)

        # Start fencing
        for worker in workers_to_fence:
            fence_item = next(fence_item_generator)
            if fence_item is not None:
                worker.run_some_tests([fence_item])
                self._log(f'Fenced {worker} with {fence_item}. '
                          f'Active scope={self._active_scope_id}')
            else:
                # No more fence items, so send the "shutdown" message to
                # the worker to force it to execute its final pending test and
                # shut down. We won't need this worker any more - the remaining
                # fence items are already occupying the necessary number of
                # workers
                worker.shutdown()

        # Transition to next state
        previous_state = self._state
        self._state = self._State.WAIT_READY_TO_ACTIVATE_SCOPE
        self._log(f'Transitioned from {str(previous_state)} to '
                  f'{str(self._state)}')

    def _distribute_workset(self, workset: _ScopeWorkset,
                            workers: list[_WorkerProxy]):
        """Distribute the tests in the given workset to the given workers.

        Adhere to the "at least two active-Scope tests per worker" Rule.

        Note that each of the non-empty workers, if any, contains exactly one
        Fence test that belongs to the scope of the given workset.

        :param workset: The workset to distribute. NOTE that some of its tests
            may have already been dequeued and applied as fences for a prior
            scope.
        :param workers: Workers to receive the distribution of tests from the
            given workset. NOTE that some of the workers may be non-empty, in
            which case they contain exactly one Fence test that belongs to the
            scope of the given workset.
        """
        # Workers with matching fence tests have priority over empty workers (to
        # satisfy the "at least two active-Scope tests per worker" Rule)
        #
        # Sort workers such that non-empty ones (those containing Fence items)
        # are at the beginning to make sure each receive at least one additional
        # test item from the workset
        workers = list(sorted(workers, key=lambda w: w.empty))

        num_workers_with_fences = sum(1 for w in workers if not w.empty)

        # Remaining tests in the workset plus the number borrowed as fences
        # must add up to the original total tests in the workset
        assert (workset.num_tests + num_workers_with_fences
                == workset.high_water), \
            f'{workset}.num_tests + {num_workers_with_fences=} ' \
            f'!= {workset.high_water=}; {workers=}'

        # Determine the number of workers we will use for this distribution
        num_workers_to_use = min(
            self._get_max_workers_for_num_tests(workset.high_water),
            len(workers))

        # At minimum, all workers fenced from the given Scope Workset must be
        # included in the distribution
        assert num_workers_to_use >= num_workers_with_fences, \
            f'{num_workers_to_use=} < {num_workers_with_fences=} ' \
            f'for {workset} and available {len(workers)=}'
        # We should only be called when there is work to be done
        assert num_workers_to_use > 0, f'{num_workers_to_use=} <= 0'
        # Our workset's footprint should not exceed available workers
        assert num_workers_to_use <= len(workers), \
            f'{num_workers_to_use=} > {len(workers)=} for {workset}'

        # Distribute the tests to the selected workers
        self._log(f'Distributing {workset} to {num_workers_to_use=}: '
                  f'{workers[:num_workers_to_use]}')

        num_tests_remaining = workset.high_water
        for (worker, num_available_workers) in zip(
                workers,
                range(num_workers_to_use, 0, -1)):
            worker: _WorkerProxy
            num_available_workers: int

            # Workers ready for distribution must have no more than one pending
            # test
            assert worker.num_pending_tests <= 1, \
                f'{worker.verbose_repr()} num_pending_tests > 1'

            if not worker.empty:
                # The single pending test in the worker must be a Fence test
                # borrowed from the given workset
                assert worker.head_pending_test.scope_id == workset.scope_id, \
                    f'Scope IDs of {worker.verbose_repr()} and {workset} differ'

            # Determine the target number of tests for this worker (including
            # a matching Fence test, if any)
            target_num_tests = ceil(num_tests_remaining / num_available_workers)
            num_tests_remaining -= target_num_tests

            # Number of tests we'll be dequeuing from the workset and adding to
            # the worker
            num_tests_to_add = target_num_tests - worker.num_pending_tests

            # Send tests to the worker
            if num_tests_to_add:
                tests_to_add = workset.dequeue_tests(num_tests=num_tests_to_add)
                worker.run_some_tests(tests_to_add)
                self._log(f'Distributed {len(tests_to_add)} tests to {worker} '
                          f'from {workset}')
            else:
                # NOTE: A Workset with a high watermark of just one item becomes
                # empty if a Fence item was withdrawn from it
                assert workset.high_water == 1, \
                    f'Attempted to distribute 0 tests to {worker} ' \
                    f'from {workset}'
                self._log(f'No more tests to distribute from {workset} '
                          f'to {worker}')

        # Workset should be empty now
        assert workset.empty, \
            f'{workset} is not empty after distribution to {num_workers_to_use} ' \
            f'workers: {workers[:num_workers_to_use]}.'

    @classmethod
    def _generate_fence_items(cls, source_worksets: Iterable[_ScopeWorkset]
                              ) -> Generator[Optional[_TestProxy], None, None]:
        """Generator that withdraws (i.e., dequeues) Fence test items from the
        given ordered Scope Worksets and yields them until it runs out of the
        fence items per limits described below, and will thereafter yield
        `None`.

        Details:
        Withdraws (i.e., dequeues) Fence test items - one test per yield - from
        the given ordered Scope Worksets and yields these
        test items, while making sure not to exceed each Workset's withdrawal
        limit to be in compliance with the "at least two active-Scope tests per
        worker" Rule when these Worksets are activated.

        The withdrawals are made from the first Workset until it reaches its
        Fence limit, then the next Workset, and so on.

        If all Fence items available in the given Source Worksets become
        exhausted, the generator yields `None` indefinitely.

        NOTE: The Worksets may have been used to fence multiple preceding active
        Scopes, so they may not have their full capacity of Fence items.

        NOTE: ASSUME that all previously withdrawn items were used for Fencing.

        NOTE: Worksets with high watermark of just one item become empty when
        a Fence item is withdrawn.

        NOTE: Worksets with original capacity of more than one Test item will
        not be completely emptied out by Fencing in order to adhere with the
        "at least two active-Scope tests per worker" Rule when these Worksets
        are eventually activated.

        :param source_worksets: A (possibly-empty) ordered Iterable of Scope
            Worksets from which to withdraw Fence test items.

        :return: this generator.
        """
        for workset in source_worksets:
            # Determine the maximum number of items we can withdraw from this
            # Workset for Fencing.
            #
            # ASSUME that all previously withdrawn items were used for Fencing
            num_fence_items = cls._get_fence_capacity_of_workset(workset)
            for _ in range(num_fence_items):
                yield workset.dequeue_tests(num_tests=1)[0]

        # The given Worksets ran out of Fence items, so yield `None` from now on
        while True:
            yield None

    @classmethod
    def _get_fence_capacity_of_workset(cls, workset: _ScopeWorkset) -> int:
        """Determine the maximum number of items we can withdraw from this
        Workset for Fencing.

        NOTE: The Worksets may have been used to fence multiple preceding active
        Scopes, so they may not have their full capacity of Fence items.

        NOTE: ASSUME that all previously withdrawn items were used for Fencing.

        NOTE: Worksets with high watermark of just one item become empty when
        a Fence item is withdrawn.

        :param workset: The given Scope Workset
        :return:
        """
        num_fence_items = (
            cls._get_max_workers_for_num_tests(num_tests=workset.high_water)
            - (workset.high_water - workset.num_tests)
        )

        assert num_fence_items >= 0, f'Number of fences below zero ' \
                                     f'({num_fence_items}) in {workset}'

        return num_fence_items

    @staticmethod
    def _get_max_workers_for_num_tests(num_tests: int) -> int:
        """Determine the maximum number of workers to which the given number of
        tests can be distributed, adhering to the "at least two active-Scope
        tests per worker" Rule.

        f(0) = 0
        f(1) = 1
        f(2) = 1
        f(3) = 1
        f(4) = 2
        f(5) = 2
        f(6) = 3
        f(7) = 3
        f(8) = 4

        :param num_tests: Number of tests.
        :return: The maximum number of workers to which the given number of
            tests can be distributed, adhering to the "at least two active-Scope
            tests per worker" Rule.
        """
        if num_tests == 1:
            return 1

        return num_tests // 2

    def _get_workers_available_for_distribution(
            self, scope_id: str) -> list[_WorkerProxy]:
        """Return workers available for distribution of the given Scope.

        Available workers are non-shutting-down workers that either
            * contain a single pending test which is a fence
              test belonging to the given scope
            * or are empty workers (no pending tests)

        ASSUMPTION: the caller is responsible for making sure that no worker
        contains more than one pending test before calling this method.

        :param scope_id: The scope ID of the test Scope being distributed.

        :return: A (possibly empty) list of workers available for distribution.
        """
        return [
            worker for worker in self._workers
            if (not worker.shutting_down
                and (worker.empty
                     or worker.tail_pending_test.scope_id == scope_id))
        ]

    def _get_workers_ready_for_fencing(self, scope_id: str
                                       ) -> list[_WorkerProxy]:
        """Return workers that are ready to be Fenced for the given test Scope.

        A worker that needs to be Fenced satisfies all the following conditions:
            * is not shutting down
            * contains exactly one pending test
            * this test belongs to the given Scope.

        :param scope_id: Scope ID of the test Scope that needs to be Fenced

        :return: A (possibly empty) list of workers to Fence.
        """
        return [
            worker for worker in self._workers
            if (not worker.shutting_down
                and worker.num_pending_tests == 1
                and worker.head_pending_test.scope_id == scope_id)
        ]

    def _do_two_nodes_have_same_collection(
            self,
            reference_node: WorkerController,
            reference_collection: tuple[str],
            node: WorkerController,
            collection: tuple[str]) -> bool:
        """
        If collections differ, this method returns False while logging
        the collection differences and posting collection errors to
        pytest_collectreport hook.

        :param reference_node: Node of test collection believed to be correct.
        :param reference_collection: Test collection believed to be correct.
        :param node: Node of the other collection.
        :param collection: The other collection to be compared with
            `reference_collection`
        :return: True if both nodes have collected the same test items. False
            otherwise.
        """
        msg = report_collection_diff(
            reference_collection, collection, reference_node.gateway.id,
            node.gateway.id)
        if not msg:
            return True

        self._log(msg)

        if self._config is not None:
            # NOTE: Not sure why/when `_config` would be `None`. Copied check
            # from the `loadscope` scheduler.

            report = CollectReport(node.gateway.id, 'failed', longrepr=msg,
                                   result=[])
            self._config.hook.pytest_collectreport(report=report)

        return False


class _WorkerProxy:
    """Our proxy of a xdist Remote Worker.

    NOTE: tests are added to the pending queue and sent to the remote worker.
    NOTE: a test is removed from the pending queue when pytest-xdist controller
        reports that the test has completed
    """

    def __init__(self, node: WorkerController):
        """
        :param node: The corresponding xdist worker node.
        """
        # node: node instance for communication with remote worker,
        #       provided by pytest-xdist controller
        self._node: WorkerController = node

        # An ordered collection of test IDs collected by the remote worker.
        # Initially None, until assigned by the Scheduler
        self._collection: Optional[tuple[str]] = None

        self._pending_test_by_index: \
            OrderedDict[int, _TestProxy] = OrderedDict()

    def __repr__(self):
        return self.verbose_repr(verbose=False)

    @property
    def node(self) -> WorkerController:
        """
        :return: The corresponding xdist worker node.
        """
        return self._node

    @property
    def collection(self) -> Optional[tuple[str]]:
        """
        :return: An ordered collection of test IDs collected by the remote
            worker; `None` if the collection is not available yet.
        """
        return self._collection

    @collection.setter
    def collection(self, collection: tuple[str]):
        """
        :param collection: An ordered collection of test IDs collected by the
            remote worker. Must not be `None`. Also, MUST NOT be set already.
        """
        assert collection is not None, f'None test collection passed to {self}'

        assert self._collection is None, \
            f'Test collection passed when one already exists to {self}'

        self._collection = collection

    @property
    def pending_tests(self) -> ValuesView[_TestProxy]:
        """Pending tests"""
        return self._pending_test_by_index.values()

    @property
    def head_pending_test(self) -> _TestProxy:
        """
        :return: The head pending test

        :raise StopIteration: If there are no pending tests
        """
        return next(iter(self.pending_tests))

    @property
    def tail_pending_test(self) -> _TestProxy:
        """
        :return: The tail pending test

        :raise StopIteration: If there are no pending tests
        """
        return next(reversed(self.pending_tests))

    @property
    def empty(self) -> bool:
        """
        `True` if no tests have been enqueued for this worker
        `False` is at least one Test remains on the pending queue
        """
        return not self._pending_test_by_index

    @property
    def num_pending_tests(self) -> int:
        """Count of tests in the pending queue
        """
        return len(self._pending_test_by_index)

    @property
    def shutting_down(self) -> bool:
        """
        :return: `True` if the worker is already down or shutdown was sent to
            the remote worker; `False` otherwise.
        """
        return self._node.shutting_down

    def verbose_repr(self, verbose: bool = True) -> str:
        """Return a possibly verbose `repr` of the instance.

        :param verbose: `True` to return verbose `repr`; `False` for terse
            `repr` content. Defaults to `True`.

        :return: `repr` of the instance.
        """
        items = [
            '<',
            f'{self.__class__.__name__}:',
            f'{self._node}',
            f'shutting_down={self.shutting_down}',
            f'num_pending={self.num_pending_tests}'
        ]

        if verbose:
            if self.num_pending_tests == 1:
                items.append(
                    f'head_scope_id={self.head_pending_test.scope_id}')
            if self.num_pending_tests > 1:
                items.append(
                    f'tail_scope_id={self.tail_pending_test.scope_id}')

        items.append('>')

        return ' '.join(items)

    def run_some_tests(self, tests: Iterable[_TestProxy]):
        """
        Add given tests to the pending queue and
        send their indexes to the remote worker
        """
        self._node.send_runtest_some([test.test_index for test in tests])
        self._pending_test_by_index.update((t.test_index, t) for t in tests)

    def handle_test_completion(self, test_index: int):
        """Remove completed test from the worker's pending tests.

        :param test_index: The stable index of the corresponding test.
        """
        # Test assumption: tests should be completed in the order they are sent
        # to the remote worker
        head_pending_test_index = next(iter(self._pending_test_by_index.keys()))

        # Completion should be reported in same order the tests were sent to
        # the remote worker
        assert head_pending_test_index == test_index, \
            f'{head_pending_test_index=} != {test_index}'

        # Remove the test from the worker's pending queue
        self._pending_test_by_index.pop(test_index)

    def release_pending_tests(self) -> list[_TestProxy]:
        """Reset the worker's pending tests, returning those pending tests.

        :return: A (possibly empty) list of pending tests.
        """
        pending_tests = list(self.pending_tests)
        self._pending_test_by_index.clear()
        return pending_tests

    def shutdown(self):
        """
        Send the "shutdown" message to the remote worker. This
        will cause the remote worker to shut down after executing
        any remaining pending tests assigned to it.
        """
        self._node.shutdown()


class _TestProxy:
    """
      Represents a single test from the overall test
      collection to be executed
    """

    # There can be a large number of tests, so economize memory by declaring
    # `__slots__` (see https://wiki.python.org/moin/UsingSlots)
    __slots__ = ('test_id', 'test_index',)

    def __init__(self, test_id: str, test_index: int):
        """
        :param test_id: Test ID of this test;
        :param test_index: The stable index of the corresponding test
            for assigning to remote worker.

        """
        self.test_id: str = test_id
        self.test_index: int = test_index

    def __repr__(self):
        return f'<{self.__class__.__name__}: test_index={self.test_index} ' \
               f'scope_id={self.scope_id} test_id={self.test_id}>'

    @property
    def scope_id(self) -> str:
        """Scope ID to which this test belongs.
        """
        return DistScopeIsoScheduling.split_scope(self.test_id)


class _ScopeWorkset:
    """
    Ordered collection of Tests for the given scope
    """

    __slots__ = ('scope_id', '_high_water', '_test_by_index',)

    def __init__(self, scope_id: str):
        """
        :param scope_id: Test Scope to which the tests in this workset belong;
        """
        self.scope_id = scope_id

        # High watermark for number of tests in the workset
        self._high_water: int = 0

        self._test_by_index: OrderedDict[int, _TestProxy] = OrderedDict()

    def __repr__(self):
        return f'<{self.__class__.__name__}: scope_id={self.scope_id} ' \
               f'num_tests={self.num_tests} high_water={self.high_water}>'

    @property
    def empty(self) -> bool:
        """`True` if workset is empty; `False` otherwise."""
        return not self._test_by_index

    @property
    def high_water(self) -> int:
        """
        :return: High Watermark of the number of tests in the workset.
        """
        return self._high_water

    @property
    def num_tests(self) -> int:
        """Number of tests in this workset"""
        return len(self._test_by_index)

    def enqueue_test(self, test: _TestProxy):
        """Append given test to ordered test collection"""
        assert test.scope_id == self.scope_id, \
            f'Wrong {test.scope_id=} for {self}'

        assert test.test_index not in self._test_by_index, \
            f'{test.test_index=} was already assigned to {self}'

        self._test_by_index[test.test_index] = test

        # Update high watermark
        new_num_tests = len(self._test_by_index)
        if new_num_tests > self._high_water:
            self._high_water = new_num_tests

    def dequeue_tests(self, num_tests: int) -> list[_TestProxy]:
        """
        Remove and return the given number of tests from the head of the
        collection.

        :param num_tests: a positive number of tests to dequeue; must not exceed
            available tests.
        @raise IndexError: If `num_tests` exceeds available tests.
        """
        assert num_tests > 0, f'Non-positive {num_tests=} requested.'

        if num_tests > len(self._test_by_index):
            raise IndexError(
                f'{num_tests=} exceeds {len(self._test_by_index)=}')

        key_iter = iter(self._test_by_index.keys())
        test_indexes_to_dequeue = [next(key_iter) for _ in range(num_tests)]

        return [self._test_by_index.pop(test_index)
                for test_index in test_indexes_to_dequeue]


class _WorksetQueue:
    """Ordered collection of Scope Worksets grouped by scope id."""

    def __init__(self):
        self._workset_by_scope: OrderedDict[str, _ScopeWorkset] = OrderedDict()

    def __repr__(self):
        return f'<{self.__class__.__name__}: ' \
               f'num_worksets={len(self._workset_by_scope)}>'

    @property
    def empty(self) -> bool:
        """`True` if work queue is empty; `False` otherwise."""
        return not self._workset_by_scope

    @property
    def head_workset(self) -> _ScopeWorkset:
        """
        :return: The head workset

        :raise StopIteration: If the Workset Queue is empty
        """
        return next(iter(self.worksets))

    @property
    def worksets(self) -> ValuesView[_ScopeWorkset]:
        """
        :return: An iterable of this queue's ordered collection of
            `_ScopeWorkset` instances.
        """
        return self._workset_by_scope.values()

    def add_test(self, test: _TestProxy):
        """Adds given test to its Scope Workset, creating the corresponding
        workset as needed. Newly-created Worksets are always added at
        the end of the Workset Queue(appended).
        """
        scope_id = test.scope_id

        if (workset := self._workset_by_scope.get(scope_id)) is not None:
            # Add to an existing Scope Workset
            workset.enqueue_test(test)
        else:
            # Create a new Scope Workset
            new_workset = _ScopeWorkset(scope_id=scope_id)
            new_workset.enqueue_test(test)
            self._workset_by_scope[scope_id] = new_workset

    def dequeue_workset(self) -> _ScopeWorkset:
        """Dequeue and return the scope workset at the head of the queue.

        @raise IndexError: If queue is empty.
        """
        if self.empty:
            raise IndexError('Attempted dequeue from empty Workset Queue.')

        return self._workset_by_scope.pop(
            next(iter(self._workset_by_scope.keys())))
