# -*- coding: utf-8 -*-
from babel import Locale
from flask import Flask, request
from flask.ext.babel import Babel, lazy_gettext
from flask.ext.login import LoginManager, current_user

import errno
import os

from .frontend import frontend
from .api import api
from .user import User
from . import customfilters

app = Flask(__name__)

app.config['SECRET_KEY'] = os.urandom(24)

app.debug = True if os.environ.get('DEBUG') else False

app.register_blueprint(frontend)
app.register_blueprint(api, url_prefix='/api')

babel = Babel(app)

login_manager = LoginManager()

login_manager.setup_app(app)
login_manager.login_view = 'frontend.login'
login_manager.login_message = lazy_gettext(u'login.authentication_required')

customfilters.setupCustomFilters(app)


@login_manager.user_loader
def load_user(userId):
    return User(userId)


LANGUAGES = ['en', 'fr']  # TODO: fetch from translations folder


@babel.localeselector
def get_locale():
    userLanguage = current_user.config.language if current_user.is_authenticated() else None

    if userLanguage and userLanguage in LANGUAGES:
        return userLanguage
    else:
        return Locale.negotiate(request.accept_languages.values(), LANGUAGES)

# Log errors to file when not in debug mode
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
