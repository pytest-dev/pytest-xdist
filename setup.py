"""
py.test 'xdist' plugin for distributed testing and loop-on-failing modes. 

See http://pytest.org/plugin/xdist.html for documentation and, after
installation of the ``pytest-xdist`` PyPI package, ``py.test -h`` 
for the new options. 
"""

from setuptools import setup
from xdist import __version__

setup(
    name="pytest-xdist",
    version=__version__,
    description='py.test xdist plugin for distributed testing and loop-on-failing modes',
    long_description=__doc__,
    license='GPLv2 or later',
    author='holger krekel and contributors',
    author_email='py-dev@codespeak.net,holger@merlinux.eu', 
    url='http://bitbucket.org/hpk42/pytest-xdist',
    platforms=['linux', 'osx', 'win32'],
    packages = ['xdist'],
    entry_points = {'pytest11': ['xdist = xdist.plugin'],},
    zip_safe=False,
    install_requires = ['execnet>=1.0.6', 'py>=1.3.1'],
    classifiers=[
    'Development Status :: 5 - Production/Stable',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: GNU General Public License (GPL)',
    'Operating System :: POSIX',
    'Operating System :: Microsoft :: Windows',
    'Operating System :: MacOS :: MacOS X',
    'Topic :: Software Development :: Testing',
    'Topic :: Software Development :: Quality Assurance',
    'Topic :: Utilities',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    ],
)
