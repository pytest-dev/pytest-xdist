# Overview #

`xdist` works by spawning one or more **workers**, which are controlled
by the **master**. Each **worker** is responsible for performing 
a full test collection and afterwards running tests as dictated by the **master**.

The execution flow is:

1. **master** spawns one or more **workers** at the beginning of
   the test session. The communication between **master** and **worker** nodes makes use of 
   [execnet](http://codespeak.net/execnet/) and its [gateways](http://codespeak.net/execnet/basics.html#gateways-bootstrapping-python-interpreters).
   The actual interpreters executing the code for the **workers** might
   be remote or local. 
  
1. Each **worker** itself is a mini pytest runner. **workers** at this
   point perform a full test collection, sending back the collected 
   test-ids back to the **master** which does not
   perform any collection itself.
     
1. The **master** receives the result of the collection from all nodes.
   At this point the **master** performs some sanity check to ensure that
   all **workers** collected the same tests (including order), bailing out otherwise.
   If all is well, it converts the list of test-ids into a list of simple
   indexes, where each index corresponds to the position of that test in the
   original collection list. This works because all nodes have the same 
   collection list, and saves bandwidth because the **master** can now tell
   one of the workers to just *execute test index 3* index of passing the
   full test id.
   
1. If **dist-mode** is **each**: the **master** just sends the full list
   of test indexes to each node at this moment.
   
1. If **dist-mode** is **load**: the **master** takes around 25% of the
   tests and sends them one by one to each **worker** in a round robin
   fashion. The rest of the tests will be distributed later as **workers**
   finish tests (see below).
   
1. **workers** re-implement `pytest_runtestloop`: pytest's default implementation
   basically loops over all collected items in the `session` object and executes
   the `pytest_runtest_protocol` for each test item, but in xdist **workers** sit idly 
   waiting for **master** to send tests for execution. As tests are
   received by **workers**, `pytest_runtest_protocol` is executed for each test. 
   Here it worth noting an implementation detail: **workers** always must keep at 
   least one test item on their queue due to how the `pytest_runtest_protocol(item, nextitem)` 
   hook is defined: in order to pass the `nextitem` to the hook, the worker must wait for more 
   instructions from master before executing that remaining test. If it receives more tests, 
   then it can safely call `pytest_runtest_protocol` because it knows what the `nextitem` parameter will be. 
   If it receives a "shutdown" signal, then it can execute the hook passing `nextitem` as `None`. 
   
1. As tests are started and completed at the **workers**, the results are sent
   back to the **master**, which then just forwards the results to 
   the appropriate pytest hooks: `pytest_runtest_logstart` and 
   `pytest_runtest_logreport`. This way other plugins (for example `junitxml`)
   can work normally. The **master** (when in dist-mode **load**) 
   decides to send more tests to a node when a test completes, using
   some heuristics such as test durations and how many tests each **worker**
   still has to run.
   
1. When the **master** has no more pending tests it will
   send a "shutdown" signal to all **workers**, which will then run their 
   remaining tests to completion and shut down. At this point the 
   **master** will sit waiting for **workers** to shut down, still
   processing events such as `pytest_runtest_logreport`.
 
## FAQ ##

> Why does each worker do its own collection, as opposed to having 
the master collect once and distribute from that collection to the workers?

If collection was performed by master then it would have to 
serialize collected items to send them through the wire, as workers live in another process. 
The problem is that test items are not easily (impossible?) to serialize, as they contain references to 
the test functions, fixture managers, config objects, etc. Even if one manages to serialize it, 
it seems it would be very hard to get it right and easy to break by any small change in pytest. 
  

