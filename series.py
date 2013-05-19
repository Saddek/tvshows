from flask import Flask, session
from flask.ext.login import LoginManager, UserMixin
from flask.ext.babel import Babel, gettext, lazy_gettext, format_date
from datetime import date
import ConfigParser
import os
import re
import urllib
import errno

from frontend import frontend
from rest import rest

app = Flask(__name__)

app.register_blueprint(frontend)
app.register_blueprint(rest, url_prefix='/rest')

app.config['SECRET_KEY'] = os.urandom(24)
app.debug = True


class User(UserMixin):
    def __init__(self, userId):
        super(User, self).__init__()
        self.id = userId

login_manager = LoginManager()

overrides = ConfigParser.ConfigParser()
overrides.read(os.path.join(os.path.dirname(__file__), 'config', 'overrides.cfg'))

babel = Babel(app)

login_manager.setup_app(app)
login_manager.login_view = 'frontend.login'
login_manager.login_message = lazy_gettext(u'login.authentication_required')


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


def episodeNumber(episode):
    return 'S%02dE%02d' % (episode['season'], episode['episode'])


def pirateBayLink(show, episode):
    # Remove content in parenthesis from the name if they are present (like the year)
    # because they are not included in release names most of the time
    # Also remove everything that is not alphanumeric or whitespace (such has apostrophes)
    strippedName = re.sub(r'\(.+?\)|([^\s\w])+', '', show['name']).strip()
    searchString = '%s %s' % (strippedName, episodeNumber(episode))

    return 'http://thepiratebay.se/search/%s/0/7/208' % urllib.quote_plus(searchString)


def addic7edLink(show, episode):
    if overrides.has_option(show['show_id'], 'addic7ed_str'):
        # get the addic7ed string from the overrides file if it's defined
        strippedName = overrides.get(show['show_id'], 'addic7ed_str')
    else:
        # else, remove content in parenthesis AND keep only alphanum, spaces and colon
        strippedName = re.sub(r'[^\s\w:]', '', re.sub(r'\(.+?\)', '', show['name'])).strip().replace(' ', '_')

    return 'http://www.addic7ed.com/serie/%s/%s/%s/episode' % (urllib.quote_plus(strippedName), episode['season'], episode['episode'])


def prettyDate(dateStr, forceYear=False, addPrefix=False):
    year, month, day = [int(component) for component in dateStr.split('-')]

    if year == 0:
        return gettext('date.unknown')

    if month == 0:
        parsedDate = date(year, 1, 1)
        format = gettext('date.format.year_only')

        if addPrefix:
            format = gettext('date.in_year_%(year)s', year=format)
    elif day == 0:
        parsedDate = date(year, month, 1)
        format = gettext('date.format.year_month')

        if addPrefix:
            format = gettext('date.in_month_%(month)s', month=format)
    else:
        parsedDate = date(year, month, day)
        format = gettext('date.format.date_with_year') if forceYear or year != date.today().year else gettext('date.format.date_without_year')

        if addPrefix:
            format = gettext('date.on_day_%(day)s', day=format)

    daysDiff = (parsedDate - date.today()).days
    if daysDiff == 0:
        return gettext('date.tonight')
    elif daysDiff == -1:
        return gettext('date.yesterday_night')
    elif daysDiff == 1:
        return gettext('date.tomorrow_night')
    elif daysDiff > 0 and daysDiff < 7:
        format = gettext('date.format.next_day')
    elif daysDiff < 0 and daysDiff > -7:
        format = gettext('date.format.previous_day')

    formattedDate = format_date(parsedDate, format)

    return formattedDate


def yearRange(started, ended):
    if ended == 0:
        return started

    return '%d - %d' % (started, ended)


def localizedShowStatus(status):
    if status == 'Returning Series':
        return gettext('showdetails.status.returning')
    elif status == 'Canceled/Ended' or status == 'Ended':
        return gettext('showdetails.status.ended')
    elif status == 'New Series':
        return gettext('showdetails.status.firstseason')
    elif status == 'Final Season':
        return gettext('showdetails.status.finalseason')
    else:
        return status

app.jinja_env.filters['episodeNumber'] = episodeNumber
app.jinja_env.filters['prettyDate'] = prettyDate
app.jinja_env.filters['pirateBayLink'] = pirateBayLink
app.jinja_env.filters['addic7edLink'] = addic7edLink
app.jinja_env.filters['yearRange'] = yearRange
app.jinja_env.filters['localizedShowStatus'] = localizedShowStatus
app.jinja_env.add_extension('jinja2.ext.do')


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
