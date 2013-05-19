# -*- coding: utf-8 -*-
import os
import sys

_basedir = os.path.abspath(os.path.dirname(__file__))

activate_this = os.path.join(_basedir, 'bin/activate_this.py')
execfile(activate_this, dict(__file__=activate_this))

sys.path.append(_basedir)

from tvshows import app as application
