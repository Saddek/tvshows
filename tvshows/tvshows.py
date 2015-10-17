# -*- coding: utf-8 -*-
from babel import Locale
from datetime import timedelta
from flask import Flask, request, session
from flask.ext.babel import Babel, lazy_gettext
from flask.ext.login import LoginManager, current_user

import errno
import logstash
import os

from .frontend import frontend
from .api import api
from .user import User
from .database import SeriesDatabase
from . import customfilters

class LoggingFlask(Flask):
    def log_exception(self, exc_info):
        """Logs an exception.  This is called by :meth:`handle_exception`
        if debugging is disabled and right before the handler is called.
        The default implementation logs the exception as error on the
        :attr:`logger`.
        .. versionadded:: 0.8
        """
        self.logger.error('Exception on %s [%s]' % (
            request.path,
            request.method
        ), exc_info=exc_info, extra={
            'method': request.method,
            'path': request.path,
            'ip': request.remote_addr,
            'agent_platform': request.user_agent.platform,
            'agent_browser': request.user_agent.browser,
            'agent_browser_version': request.user_agent.version,
            'agent': request.user_agent.string,
            'user': current_user.id if not current_user.is_anonymous() else '<anonymous>'
        })

app = LoggingFlask(__name__)

app.config['SECRET_KEY'] = SeriesDatabase().getAppSecretKey()

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
    session.permanent = True
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

    app.logger.setLevel(logging.INFO)

    file_handler = TimedRotatingFileHandler(os.path.join(logsDir, 'error.log'), when='midnight', backupCount=5)
    file_handler.setLevel(logging.WARNING)

    logstash_handler = logstash.TCPLogstashHandler('localhost', 5229, message_type=None, version=1) # no message type, let the logstash server decide

    app.logger.addHandler(file_handler)
    app.logger.addHandler(logstash_handler)
