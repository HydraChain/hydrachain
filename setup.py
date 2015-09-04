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


with open('README.rst') as readme_file:
    readme = readme_file.read()


history = ''


install_requires = set(x.strip() for x in open('requirements.txt'))
install_requires_replacements = {
    'https://github.com/ethereum/pyethapp/tarball/develop': 'pyethapp',
}

install_requires = [install_requires_replacements.get(r, r) for r in install_requires]

test_requirements = ['ethereum-serpent>=1.8.1']

version = '0.0.1'  # preserve format, this is read from __init__.py

setup(
    name='hydrachain',
    version=version,
    description="",
    long_description=readme + '\n\n' + history,
    author="HeikoHeiko",
    author_email='heiko@brainbot.com',
    url='https://github.com/HydraChain/hydrachain',
    packages=[
        'hydrachain',
        'hydrachain.consensus'
    ],
    #    package_dir={'hydrachain': 'hydrachain'},
    include_package_data=True,
    license="BSD",
    zip_safe=False,
    keywords='hydrachain',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
    ],
    cmdclass={'test': PyTest},
    install_requires=install_requires,
    tests_require=test_requirements,
    entry_points='''
    [console_scripts]
    hydrachain=hydrachain.app:app
    '''
)
