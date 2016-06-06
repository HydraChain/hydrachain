#!/usr/bin/env python
# -*- coding: utf-8 -*-

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
from setuptools.command.test import test as TestCommand


class PyTest(TestCommand):

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        # import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.test_args)
        raise SystemExit(errno)


with open('README.md') as readme_file:
    readme = readme_file.read()


history = ''


install_requires = set(x.strip() for x in open('requirements.txt'))
install_requires_replacements = {}

install_requires = [install_requires_replacements.get(r, r) for r in install_requires]

test_requirements = [
    'docker-compose==1.7.0',
    'bumpversion==0.5.3',
    'pytest==2.9.1'
]


# *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
# see: https://github.com/ethereum/pyethapp/wiki/Development:-Versions-and-Releases
version = '0.3.2'


setup(
    name='hydrachain',
    version=version,
    description="Permissioned Distributed Ledger based on Ethereum",
    long_description=readme + '\n\n' + history,
    author="HeikoHeiko",
    author_email='heiko@brainbot.com',
    url='https://github.com/HydraChain/hydrachain',
    packages=[
        'hydrachain',
        'hydrachain.consensus',
        'hydrachain.examples',
        'hydrachain.examples.native',
        'hydrachain.examples.native.fungible',
    ],
    include_package_data=True,
    license="MIT",
    zip_safe=False,
    keywords='hydrachain',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
    ],
    cmdclass={'test': PyTest},
    install_requires=install_requires,
    tests_require=test_requirements,
    entry_points={
        'console_scripts': [
            "hydrachain = hydrachain.app:app"
        ]
    }
)
