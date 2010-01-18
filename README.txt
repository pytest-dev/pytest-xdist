py.test xdist plugin: distributed testing and loop failure
===============================================================

.. _`pytest-xdist respository`: http://bitbucket.org/hpk42/pytest-xdist
.. _`pytest`: http://pytest.org

The pytest-xdist plugin extends `py.test`_ to ad-hoc distribute test 
runs to multiple CPUs or remote machines.   It requires setuptools
or distribute which help to pull in the neccessary execnet and 
pytest-core dependencies. 

Install the plugin locally with::

    python setup.py install   

or use the package in develope/in-place mode, particularly
useful with a checkout of the `pytest-xdist repository`_::

    python setup.py develop

or use one of::

    easy_install pytest-xdist 

    pip install pytest-xdist 

for downloading and installing it in one go.

holger krekel <holger at merlinux eu>
