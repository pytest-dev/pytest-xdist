from setuptools import setup, find_packages

install_requires = [
    "execnet>=1.1",
    "psutil>=3.0.0",
    "pytest>=4.4.0",
    "pytest-forked",
    "six",
]


with open("README.rst") as f:
    long_description = f.read()

setup(
    name="pytest-xdist",
    use_scm_version={"write_to": "src/xdist/_version.py"},
    description="pytest xdist plugin for distributed testing"
    " and loop-on-failing modes",
    long_description=long_description,
    license="MIT",
    author="holger krekel and contributors",
    author_email="pytest-dev@python.org,holger@merlinux.eu",
    url="https://github.com/pytest-dev/pytest-xdist",
    platforms=["linux", "osx", "win32"],
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    extras_require={"testing": ["filelock"]},
    entry_points={
        "pytest11": ["xdist = xdist.plugin", "xdist.looponfail = xdist.looponfail"]
    },
    zip_safe=False,
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    install_requires=install_requires,
    setup_requires=["setuptools_scm"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Framework :: Pytest",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS :: MacOS X",
        "Topic :: Software Development :: Testing",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Utilities",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
)
