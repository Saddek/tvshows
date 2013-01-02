import os
import sys

_basedir = os.path.abspath(os.path.dirname(__file__))

activate_this = os.path.join(_basedir, 'bin/activate_this.py')
execfile(activate_this, dict(__file__=activate_this))

sys.path.append(_basedir)

import monitor
monitor.start(interval=1.0)
monitor.track(os.path.join(os.path.dirname(__file__)))

from app import app as application

application.config['DEBUG'] = True
