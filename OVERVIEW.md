# Overview #

Here it is described a brief overview of xdist's internal architecture.


`xdist` works by spawning one or more **worker nodes**, which are controlled
by the **master node**. Each **worker node** is responsible for performing 
a full test collection and afterwards running tests as dictated by the **master node**.

The execution flow is:

1. **master node** spawns one or more **worker nodes** at the begginning of
   the test session. The communication between **master** and **worker** nodes makes use of 
   [execnet](http://codespeak.net/execnet/) and its [gateways](http://codespeak.net/execnet/basics.html#gateways-bootstrapping-python-interpreters).
   The actual interpreters executing the code for the **worker nodes** might
   be remote or local. 
  
1. Each **worker node** itself is a mini pytest runner. **workers** at this
   point perform a full test collection, sending back the collected 
   test-ids back to the **master node** which does not
   perform any collection itself.
     
1. The **master node** receives the result of the collection from all nodes.
   At this point the **master node** performs some sanity check to ensure that
   all **worker nodes** collected the same tests (including order), bailing out otherwise.
   If all is well, it converts the list of test-ids into a list of simple
   indexes, where each index corresponds to the position of that test in the
   original collection list. This works because all nodes have the same 
   collection list, and saves bandwidth because the **master** can now tell
   one of the workers to just *execute test index 3* index of passing the
   full test id.
   
1. If **dist-mode** is **each**: the **master node** just sends the full list
   of test indexes to each node at this moment.
   
1. If **dist-mode** is **load**: the **master node** takes around 25% of the
   tests and sends them one by one to each **worker node** in a round robin
   fashion. The rest of the tests will be distributed later as **worker nodes**
   finish tests (see below).
   
1. **worker nodes** re-implement `pytest_runtestloop`: pytest's default implementation
   basically loops over all collected items in the `session` object and executes
   the `pytest_runtest_protocol` for each test item, but in xdist **workers** sit idly 
   waiting for **master node** to send tests for execution. As tests are
   received by **workers**, `pytest_runtest_protocol` is executed for each test. 
   Here it worth noting an implementation detail: at least one
   test is kept always in **worker nodes** must they comply with 
   `pytest_runtest_protocol` in that it needs to know which will be the 
   `nextitem` in the hook call: either a new test in case the **master node** sends
   a new test, or `None` if the **worker** receives a "shutdown" request.
   
1. As tests are started and completed at the **workers**, the results are sent
   back to the **master node**, which then just forwards the results to 
   the appropriate pytest hooks: `pytest_runtest_logstart` and 
   `pytest_runtest_logreport`. This way other plugins (for example `junitxml`)
   can work normally. The **master node** (when in dist-mode **load**) 
   decides to send more tests to a node when a test completes, using
   some heuristics such as test durations and how many tests each **worker node**
   still has to run.
   
1. When the **master node** has no more pending tests it will
   send a "shutdown" signal to all **workers**, which will then run their 
   remaining tests to completion and shut down. At this point the 
   **master node** will sit waiting for **workers** to shut down, still
   processing events such as `pytest_runtest_logreport`.
 
