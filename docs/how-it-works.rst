How it works?
=============

``xdist`` works by spawning one or more **workers**, which are
controlled by the **controller**. Each **worker** is responsible for
performing a full test collection and afterwards running tests as
dictated by the **controller**.

The execution flow is:

1. **controller** spawns one or more **workers** at the beginning of the
   test session. The communication between **controller** and **worker**
   nodes makes use of `execnet <https://codespeak.net/execnet/>`__ and
   its
   `gateways <https://codespeak.net/execnet/basics.html#gateways-bootstrapping-python-interpreters>`__.
   The actual interpreters executing the code for the **workers** might
   be remote or local.

2. Each **worker** itself is a mini pytest runner. **workers** at this
   point perform a full test collection, sending back the collected
   test-ids back to the **controller** which does not perform any
   collection itself.

3. The **controller** receives the result of the collection from all
   nodes. At this point the **controller** performs some sanity check to
   ensure that all **workers** collected the same tests (including
   order), bailing out otherwise. If all is well, it converts the list
   of test-ids into a list of simple indexes, where each index
   corresponds to the position of that test in the original collection
   list. This works because all nodes have the same collection list, and
   saves bandwidth because the **controller** can now tell one of the
   workers to just *execute test index 3* instead of passing the full
   test id.

4. If **dist-mode** is **each**: the **controller** just sends the full
   list of test indexes to each node at this moment.

5. If **dist-mode** is **load**: the **controller** takes around 25% of
   the tests and sends them one by one to each **worker** in a round
   robin fashion. The rest of the tests will be distributed later as
   **workers** finish tests (see below).

6. Note that ``pytest_xdist_make_scheduler`` hook can be used to
   implement custom tests distribution logic.

7. **workers** re-implement ``pytest_runtestloop``: pytest’s default
   implementation basically loops over all collected items in the
   ``session`` object and executes the ``pytest_runtest_protocol`` for
   each test item, but in xdist **workers** sit idly waiting for
   **controller** to send tests for execution. As tests are received by
   **workers**, ``pytest_runtest_protocol`` is executed for each test.
   Here it worth noting an implementation detail: **workers** always
   must keep at least one test item on their queue due to how the
   ``pytest_runtest_protocol(item, nextitem)`` hook is defined: in order
   to pass the ``nextitem`` to the hook, the worker must wait for more
   instructions from controller before executing that remaining test. If
   it receives more tests, then it can safely call
   ``pytest_runtest_protocol`` because it knows what the ``nextitem``
   parameter will be. If it receives a “shutdown” signal, then it can
   execute the hook passing ``nextitem`` as ``None``.

8. As tests are started and completed at the **workers**, the results
   are sent back to the **controller**, which then just forwards the
   results to the appropriate pytest hooks: ``pytest_runtest_logstart``
   and ``pytest_runtest_logreport``. This way other plugins (for example
   ``junitxml``) can work normally. The **controller** (when in
   dist-mode **load**) decides to send more tests to a node when a test
   completes, using some heuristics such as test durations and how many
   tests each **worker** still has to run.

9. When the **controller** has no more pending tests it will send a
   “shutdown” signal to all **workers**, which will then run their
   remaining tests to completion and shut down. At this point the
   **controller** will sit waiting for **workers** to shut down, still
   processing events such as ``pytest_runtest_logreport``.

FAQ
---

**Question**: Why does each worker do its own collection, as opposed to having the
controller collect once and distribute from that collection to the
workers?

If collection was performed by controller then it would have to
serialize collected items to send them through the wire, as workers live
in another process. The problem is that test items are not easily
(impossible?) to serialize, as they contain references to the test
functions, fixture managers, config objects, etc. Even if one manages to
serialize it, it seems it would be very hard to get it right and easy to
break by any small change in pytest.
