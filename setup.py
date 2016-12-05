from setuptools import setup

setup(
    name="pytest-xdist",
    use_scm_version={'write_to': 'xdist/_version.py'},
    description='py.test xdist plugin for distributed testing'
                ' and loop-on-failing modes',
    long_description=open('README.rst').read(),
    license='MIT',
    author='holger krekel and contributors',
    author_email='pytest-dev@python.org,holger@merlinux.eu',
    url='https://github.com/pytest-dev/pytest-xdist',
    platforms=['linux', 'osx', 'win32'],
    packages=['xdist'],
    entry_points={
        'pytest11': [
            'xdist = xdist.plugin',
            'xdist.looponfail = xdist.looponfail',
            'xdist.boxed = xdist.boxed',
        ],
    },
    zip_safe=False,
    install_requires=['execnet>=1.1', 'pytest>=2.7.0', 'py>=1.4.22'],
    setup_requires=['setuptools_scm'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Framework :: Pytest',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
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
