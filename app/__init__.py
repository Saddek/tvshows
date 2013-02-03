# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, Response, jsonify, url_for, redirect, session, flash, abort, send_file
from flask.ext.login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask.ext.babel import Babel, gettext, lazy_gettext, format_date
from datetime import date
from PIL import Image, ImageFile
from StringIO import StringIO
import calendar
import ConfigParser
import errno
import os
import re
import requests
import urllib


class User(UserMixin):
    def __init__(self, userId):
        super(User, self).__init__()
        self.id = userId

app = Flask(__name__)
login_manager = LoginManager()

app.config['SECRET_KEY'] = os.urandom(24)

# TODO: check that all needed config variables are set
app.config.from_pyfile('config.cfg')

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

overrides = ConfigParser.ConfigParser()
overrides.read(os.path.join(os.path.dirname(__file__), 'overrides.cfg'))

babel = Babel(app)

apiURL = app.config['SERIES_API_URL']

login_manager.setup_app(app)
login_manager.login_view = 'login'
login_manager.login_message = lazy_gettext(u'login.authentication_required')


def credentials():
    return (current_user.id, current_user.password)


@login_manager.user_loader
def load_user(userId):
    user = User(userId)
    user.password = session['password'] if 'password' in session else None
    return user


@babel.localeselector
def get_locale():
    return request.accept_languages.best_match(['fr', 'en'])


def episodeNumber(episode):
    return 'S%02dE%02d' % (episode['season'], episode['episode'])


def pirateBayLink(show, episode):
    # Remove content in parenthesis from the name if they are present (like the year)
    # because they are not included in release names most of the time
    # Also remove everything that is not alphanumeric or whitespace (such has apostrophes)
    strippedName = re.sub(r'\(.+?\)|([^\s\w])+', '', show['name']).strip()
    searchString = '%s %s' % (strippedName, episodeNumber(episode))

    return 'http://thepiratebay.se/search/%s/0/99/208' % urllib.quote_plus(searchString)


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


# sorts episodes by date
def unseenEpisodesKey(show):
    return airdateKey(show['unseenEpisodes'][0]['airdate'])


def upcomingEpisodesKey(show):
    return airdateKey(show['upcomingEpisodes'][0]['airdate'])


def airdateKey(airdate):
    year, month, day = [int(component) for component in airdate.split('-')]

    if month == 0:
        return '%04d-12-31' % year

    if day == 0:
        return '%04d-%02d-%02d' % (year, month, calendar.monthrange(year, month)[1])

    return airdate


def getShowsOverview():
    res = requests.get('%s/user/shows?episodes=true&unseen=true' % apiURL, auth=credentials(), verify=False)

    shows = [show for show in res.json()['shows'] if len(show['episodes']) > 0]

    today = date.today().strftime('%Y-%m-%d')
    for show in shows:
        show['unseenEpisodes'] = [episode for episode in show['episodes'] if airdateKey(episode['airdate']) < today and episode['airdate'] != '0000-00-00']
        show['upcomingEpisodes'] = [episode for episode in show['episodes'] if airdateKey(episode['airdate']) >= today and episode['airdate'] != '0000-00-00']

    unseen = [show for show in shows if len(show['unseenEpisodes']) > 0]
    upcoming = [show for show in shows if len(show['upcomingEpisodes']) > 0 and (len(show['unseenEpisodes']) == 0 or (show['upcomingEpisodes'][0]['season'] == show['unseenEpisodes'][0]['season'] or (show['unseenEpisodes'][0]['episode'] > 1 and show['upcomingEpisodes'][0]['season'] <= show['unseenEpisodes'][0]['season'] + 1)))]

    unseen.sort(key=unseenEpisodesKey, reverse=True)
    upcoming.sort(key=upcomingEpisodesKey)

    return unseen, upcoming


@app.route('/')
@login_required
def home():
    unseen, upcoming = getShowsOverview()

    return render_template('home.html', unseen=unseen, upcoming=upcoming)


@app.route('/shows/')
@login_required
def shows():
    res = requests.get('%s/user/shows' % apiURL, auth=credentials(), verify=False)

    shows = res.json()['shows']

    return render_template('shows.html', shows=shows)


@app.route('/show/<showId>/')
@login_required
def show_details(showId):
    res = requests.get('%s/user/shows/%s' % (apiURL, showId), auth=credentials(), verify=False)

    show = res.json()

    if 'poster' in show:
        show['poster_path'] = '%s/%s' % (apiURL, show['poster'])

    return render_template('showdetails.html', show=show)


@app.route('/add/<showId>')
@login_required
def show_add(showId):
    r = requests.put('%s/user/shows/%s' % (apiURL, showId), auth=credentials(), verify=False)

    if r.status_code != 200 and r.status_code != 201:
        return Response(status=500)

    return redirect(url_for('shows'))


@app.route('/delete/<showId>')
@login_required
def show_delete(showId):
    r = requests.delete('%s/user/shows/%s' % (apiURL, showId), auth=credentials(), verify=False)

    if r.status_code == 404:
        return Response(status=404)

    if r.status_code != 204:
        return Response(status=500)

    return redirect(url_for('shows'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User(request.form['username'])
        password = request.form['password']
        remember = bool(request.form.get('remember', False))

        r = requests.get('%s/user/shows' % apiURL, auth=(user.id, password), verify=False)

        if r.status_code == 200:
            login_user(user, remember=remember)
            session['password'] = password
            return redirect(request.args.get('next') or url_for('home'))
        else:
            flash(gettext(u'login.authentication_failed'), 'error')

    return render_template('login.html')


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash(gettext(u'login.successful_logout'), 'success')
    return redirect(url_for('login'))


@app.route('/ajax/unseen/<showId>/<episodeId>')
@login_required
def ajax_home_unseen(showId, episodeId):
    r = requests.put('%s/user/shows/%s/last_seen' % (apiURL, showId), data=episodeId, auth=credentials(), verify=False)

    if (r.status_code != 204):
        return Response(status=500)

    unseen, upcoming = getShowsOverview()

    show = None
    for s in unseen:
        if s['show_id'] == showId:
            show = s

    return jsonify(unseen=render_template('ajax/home_unseen.html', show=show) if show else None,
                   upcoming=render_template('ajax/home_upcoming.html', upcoming=upcoming))


@app.route('/ajax/showsorder', methods=['POST'])
@login_required
def ajax_set_show_order():
    ordering = {}

    for showId, order in request.form.iteritems():
        if not showId.isdigit() or not order.isdigit():
            return Response(status=400)

        ordering[showId] = order

    res = requests.post('%s/user/shows_order' % apiURL, data=ordering, auth=credentials(), verify=False)

    if res.status_code != 204:
        return Response(status=500)

    return Response(status=204)


@app.route('/ajax/search/<showName>')
@login_required
def ajax_search_show(showName):
    r = requests.get('%s/search/%s' % (apiURL, urllib.quote_plus(showName)), verify=False)

    if r.status_code != 200:
        abort(500)

    results = r.json()['results']

    r = requests.get('%s/user/shows' % apiURL, auth=credentials(), verify=False)

    userShows = [show['show_id'] for show in r.json()['shows']]

    return render_template('ajax/search_results.html', results=results, userShows=userShows)


@app.route('/thumbs/<size>/<path:posterPath>', methods=['GET'])
def get_thumbnail(size, posterPath):
    # width and height are separated by an 'x' (e.g. 187x275)
    splittedSize = size.split('x')

    if len(splittedSize) != 2 or not splittedSize[0].isdigit() or not splittedSize[1].isdigit():
        abort(400)

    width, height = [int(component) for component in splittedSize]

    r = requests.get('%s/%s' % (apiURL, posterPath), stream=True, verify=False)

    img = Image.open(StringIO(r.content))

    img.thumbnail((width, height), Image.ANTIALIAS)

    thumbnail = StringIO()

    try:
        img.save(thumbnail, 'JPEG', quality=95, optimize=True, progressive=True)
    except IOError:
        # http://stackoverflow.com/questions/6788398/how-to-save-progressive-jpeg-using-python-pil-1-1-7
        ImageFile.MAXBLOCK = img.size[0] * img.size[1]
        img.save(thumbnail, 'JPEG', quality=95, optimize=True, progressive=True)

    thumbnail.seek(0)

    return send_file(thumbnail, mimetype='image/jpeg')
