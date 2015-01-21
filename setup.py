#! /usr/bin/env python3
# -*- coding: utf8 -*-

from __future__ import print_function

import os
import sys
from setuptools import setup


try:
   os.chdir(os.path.dirname(sys.argv[0]))
except:
   pass

if not os.path.exists('gecco'):
    print("Preparing build",file=sys.stderr)
    if not os.path.exists('build'): os.mkdir('build')
    os.chdir('build')
    if not os.path.exists('gecco'): os.mkdir('gecco')
    os.system('cp -Rpfv ../*py ../*.yml ../modules ../example gecco/')
    os.system('find gecco/ -type l | xargs rm')
    os.system('mv -f gecco/setup.py .')
    os.system('cp -f ../README* ../INSTALL ../ChangeLog ../COPYING ../LICENSE .')

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "Gecco",
    version = "0.1",
    author = "Maarten van Gompel, Wessel Stoop",
    author_email = "proycon@anaproy.nl",
    description = ("Generic Environment for Context-Aware Correction of Orthography"),
    license = "GPL",
    keywords = "spelling corrector spell check nlp computational_linguistics rest",
    url = "http://proycon.github.com/clam",
    packages=['gecco'],
    long_description=read('README.md'),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Text Processing :: Linguistic",
        "Programming Language :: Python :: 3.2",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Operating System :: POSIX",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ],
    entry_points = {
        'console_scripts': [
            'gecco = gecco.gecco:main'
        ]
    },
    package_data = {'gecco':[] },
    install_requires=['lxml >= 2.2','pynlpl >= 0.6.18','pyyaml','python-ucto >= 0.1.1']
)
