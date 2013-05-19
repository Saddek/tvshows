from flask import Flask, session
from flask.ext.login import LoginManager
from flask.ext.babel import Babel, lazy_gettext
from .user import User
from . import customfilters
import os
import errno

from frontend import frontend
from rest import rest

app = Flask(__name__)

app.config['SECRET_KEY'] = os.urandom(24)

app.debug = True if os.environ.get('DEBUG') else False

app.register_blueprint(frontend)
app.register_blueprint(rest, url_prefix='/rest')

babel = Babel(app)

login_manager = LoginManager()

login_manager.setup_app(app)
login_manager.login_view = 'frontend.login'
login_manager.login_message = lazy_gettext(u'login.authentication_required')

customfilters.setupCustomFilters(app)


@login_manager.user_loader
def load_user(userId):
    if not 'password' in session:
        return None

    user = User(userId)
    user.password = session['password']
    return user


@babel.localeselector
def get_locale():
    # TODO: make sure it returns a locale also supported by WTForms to prevent errors
    return 'fr'  # request.accept_languages.best_match(['fr', 'en'])

if not app.debug:
    import logging
    from logging.handlers import TimedRotatingFileHandler

    logsDir = os.path.join(os.path.dirname(__file__), 'logs')
    try:
        os.makedirs(logsDir)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

    file_handler = TimedRotatingFileHandler(os.path.join(logsDir, 'error.log'), when='midnight', backupCount=5)
    file_handler.setLevel(logging.WARNING)
    app.logger.addHandler(file_handler)
