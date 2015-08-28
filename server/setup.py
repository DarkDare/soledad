# -*- coding: utf-8 -*-
# setup.py
# Copyright (C) 2013 LEAP
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
"""
setup file for leap.soledad.server
"""
import os
import re
from setuptools import setup
from setuptools import find_packages
from setuptools import Command

from pkg import utils

import versioneer
versioneer.versionfile_source = 'src/leap/soledad/server/_version.py'
versioneer.versionfile_build = 'leap/soledad/server/_version.py'
versioneer.tag_prefix = ''  # tags are like 1.2.0
versioneer.parentdir_prefix = 'leap.soledad.server-'

isset = lambda var: os.environ.get(var, None)
if isset('VIRTUAL_ENV') or isset('LEAP_SKIP_INIT'):
    data_files = None
else:
    # XXX this should go only for linux/mac
    data_files = [("/etc/init.d/", ["pkg/soledad-server"])]


trove_classifiers = (
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: "
    "GNU General Public License v3 or later (GPLv3+)",
    "Environment :: Console",
    "Operating System :: OS Independent",
    "Operating System :: POSIX",
    "Programming Language :: Python :: 2.6",
    "Programming Language :: Python :: 2.7",
    "Topic :: Database :: Front-Ends",
    "Topic :: Software Development :: Libraries :: Python Modules"
)

DOWNLOAD_BASE = ('https://github.com/leapcode/soledad/'
                 'archive/%s.tar.gz')
_versions = versioneer.get_versions()
VERSION = _versions['version']
VERSION_FULL = _versions['full']
DOWNLOAD_URL = ""

# get the short version for the download url
_version_short = re.findall('\d+\.\d+\.\d+', VERSION)
if len(_version_short) > 0:
    VERSION_SHORT = _version_short[0]
    DOWNLOAD_URL = DOWNLOAD_BASE % VERSION_SHORT

cmdclass = versioneer.get_cmdclass()


class freeze_debianver(Command):
    """
    Freezes the version in a debian branch.
    To be used after merging the development branch onto the debian one.
    """
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        proceed = str(raw_input(
            "This will overwrite the file _version.py. Continue? [y/N] "))
        if proceed != "y":
            print("He. You scared. Aborting.")
            return
        template = r"""
# This file was generated by the `freeze_debianver` command in setup.py
# Using 'versioneer.py' (0.7+) from
# revision-control system data, or from the parent directory name of an
# unpacked source archive. Distribution tarballs contain a pre-generated copy
# of this file.

version_version = '{version}'
version_full = '{version_full}'
"""
        templatefun = r"""

def get_versions(default={}, verbose=False):
        return {'version': version_version, 'full': version_full}
"""
        subst_template = template.format(
            version=VERSION_SHORT,
            version_full=VERSION_FULL) + templatefun
        with open(versioneer.versionfile_source, 'w') as f:
            f.write(subst_template)


cmdclass["freeze_debianver"] = freeze_debianver

# XXX add ref to docs

requirements = utils.parse_requirements()

if utils.is_develop_mode():
    print
    print ("[WARNING] Skipping leap-specific dependencies "
           "because development mode is detected.")
    print ("[WARNING] You can install "
           "the latest published versions with "
           "'pip install -r pkg/requirements-leap.pip'")
    print ("[WARNING] Or you can instead do 'python setup.py develop' "
           "from the parent folder of each one of them.")
    print
else:
    requirements += utils.parse_requirements(
        reqfiles=["pkg/requirements-leap.pip"])

setup(
    name='leap.soledad.server',
    version=VERSION,
    cmdclass=cmdclass,
    url='https://leap.se/',
    download_url=DOWNLOAD_URL,
    license='GPLv3+',
    description='Synchronization of locally encrypted data among devices '
                '(server components)',
    author='The LEAP Encryption Access Project',
    author_email='info@leap.se',
    maintainer='Kali Kaneko',
    maintainer_email='kali@leap.se',
    long_description=(
        "Soledad is the part of LEAP that allows application data to be "
        "securely shared among devices. It provides, to other parts of the "
        "LEAP project, an API for data storage and sync."
    ),
    classifiers=trove_classifiers,
    namespace_packages=["leap", "leap.soledad"],
    packages=find_packages('src'),
    package_dir={'': 'src'},
    install_requires=requirements,
    data_files=data_files
)
