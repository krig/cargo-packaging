#!/usr/bin/env python
from distutils.core import setup

setup(name='cargoapi',
      version='0.0.1',
      description='Tools for interacting with the cargo package manager',
      author='Kristoffer Gronlund',
      author_email='kgronlund@suse.com',
      url='https://github.com/krig/cargo-packaging',
      packages=['cargoapi'],
      scripts=['cargo2rpm'],
      install_requires=['dulwich', 'requests'])
