# -*- coding: utf-8 -*-
from datetime import date
from flask import Blueprint, render_template, request, Response, jsonify, url_for, redirect, flash, abort, send_file, current_app
from flask.ext.babel import gettext, lazy_gettext, get_locale, refresh as refresh_locale
from flask.ext.login import login_user, logout_user, login_required, current_user
from flask.ext.wtf import Form, TextField, PasswordField, BooleanField, SelectField, IntegerField, validators
from StringIO import StringIO

import calendar
import Image
import ImageFile
import requests
import wtforms.ext.i18n.form

from ..database import SeriesDatabase
from ..user import User

series = SeriesDatabase()

frontend = Blueprint('frontend', __name__, template_folder='templates')


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
    shows = []
    for showId in series.getUserShowList(current_user.id):
        show = series.getShowInfo(current_user.id, showId, withEpisodes=True, onlyUnseen=True)

        if (len(show['episodes']) > 0):
            shows.append(show)

    today = date.today().strftime('%Y-%m-%d')
    for show in shows:
        show['unseenEpisodes'] = [episode for episode in show['episodes'] if airdateKey(episode['airdate']) < today and episode['airdate'] != '0000-00-00']
        show['upcomingEpisodes'] = [episode for episode in show['episodes'] if airdateKey(episode['airdate']) >= today and episode['airdate'] != '0000-00-00']

    unseen = [show for show in shows if len(show['unseenEpisodes']) > 0]
    upcoming = [show for show in shows if len(show['upcomingEpisodes']) > 0 and (len(show['unseenEpisodes']) == 0 or (show['upcomingEpisodes'][0]['season'] == show['unseenEpisodes'][0]['season'] or (show['unseenEpisodes'][0]['episode'] > 1 and show['upcomingEpisodes'][0]['season'] <= show['unseenEpisodes'][0]['season'] + 1)))]

    unseen.sort(key=unseenEpisodesKey, reverse=True)
    upcoming.sort(key=upcomingEpisodesKey)

    return unseen, upcoming


@frontend.route('/')
@login_required
def home():
    unseen, upcoming = getShowsOverview()

    return render_template('home.html', unseen=unseen, upcoming=upcoming)


@frontend.route('/shows/')
@login_required
def shows():
    shows = []
    for showId in series.getUserShowList(current_user.id):
        show = series.getShowInfo(current_user.id, showId)
        shows.append(show)

    return render_template('shows.html', shows=shows)


@frontend.route('/show/<showId>/')
@login_required
def show_details(showId):
    show = series.getShowInfo(current_user.id, showId)

    return render_template('showdetails.html', show=show)


@frontend.route('/add/<showId>')
@login_required
def show_add(showId):
    if not series.userHasShow(current_user.id, showId):
        series.addShowToUser(current_user.id, showId)

    return redirect(url_for('.shows'))


@frontend.route('/delete/<showId>')
@login_required
def show_delete(showId):
    series.deleteShowFromUser(current_user.id, showId)

    return redirect(url_for('.shows'))


class UserForm(Form, wtforms.ext.i18n.form.Form):
    username = TextField(lazy_gettext('login.placeholder.username'), [
        validators.Length(min=2, max=25),
        validators.Regexp('^\w+$', message=lazy_gettext('signup.error.alphanum'))
    ])
    password = PasswordField(lazy_gettext('login.placeholder.password'), [validators.Required()])


@frontend.route('/login', methods=['GET', 'POST'])
def login():
    class LoginForm(UserForm):
        LANGUAGES = [get_locale().language]

        remember = BooleanField(lazy_gettext('login.rememberme'))

    form = LoginForm()

    if form.validate_on_submit():
        user = User(form.username.data.lower())
        password = form.password.data
        remember = bool(form.remember.data)

        if series.checkAuth(user.id, password):
            login_user(user, remember=remember)
            return redirect(request.args.get('next') or url_for('.home'))
        else:
            flash(gettext(u'login.authentication_failed'), 'error')

    return render_template('login.html', form=form)


@frontend.route('/signup', methods=['GET', 'POST'])
def signup():
    class RegistrationForm(UserForm):
        LANGUAGES = [get_locale().language]

        password = PasswordField(lazy_gettext('login.placeholder.password'), [
            validators.Required(),
            validators.EqualTo('confirm', message=lazy_gettext('signup.error.passwordsmatch'))
        ])
        confirm = PasswordField(lazy_gettext('signup.placeholder.confirmpassword'))

    form = RegistrationForm()

    if form.validate_on_submit():
        username = form.username.data.lower()

        if not series.userExists(username):
            series.addUser(username, form.password.data)
            flash(gettext('login.successful_signup'), 'success')
            return redirect(url_for('.login'))
        else:
            flash(gettext('signup.usernametaken'), 'error')

    return render_template('signup.html', form=form)


@frontend.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    class SettingsForm(Form, wtforms.ext.i18n.form.Form):
        LANGUAGES = [get_locale().language]

        language = SelectField(lazy_gettext('settings.language'), default=current_user.config.language, choices=[
            ('auto', lazy_gettext('settings.language.autodetect')),
            ('en', u'English'),
            ('fr', u'Français')
        ])
        episodesPerShow = IntegerField(lazy_gettext('settings.episodesPerShow'), default=current_user.config.episodesPerShow, validators=[
            validators.NumberRange(min=1)
        ])

    form = SettingsForm()

    if form.validate_on_submit():
        for field, value in form.data.items():
            current_user.config[field] = value

        refresh_locale()

        flash(gettext('settings.savesuccess'), 'success')

    return render_template('settings.html', form=form)


@frontend.route("/logout")
@login_required
def logout():
    logout_user()
    flash(gettext(u'login.successful_logout'), 'success')
    return redirect(url_for('.login'))


@frontend.route('/ajax/unseen/<showId>/<episodeId>')
@login_required
def ajax_home_unseen(showId, episodeId):
    series.setLastSeen(current_user.id, showId, episodeId)

    unseen, upcoming = getShowsOverview()

    show = None
    for s in unseen:
        if s['show_id'] == showId:
            show = s

    return jsonify(unseen=render_template('ajax/home_unseen.html', show=show) if show else None,
                   upcoming=render_template('ajax/home_upcoming.html', upcoming=upcoming))


@frontend.route('/ajax/more/<showId>/<int:moreMult>')
@login_required
def ajax_home_show_more(showId, moreMult):
    unseen, upcoming = getShowsOverview()

    show = None
    for s in unseen:
        if s['show_id'] == showId:
            show = s

    return jsonify(unseen=render_template('ajax/home_unseen.html', show=show, moreMult=moreMult))


@frontend.route('/ajax/showsorder', methods=['POST'])
@login_required
def ajax_set_show_order():
    ordering = {}

    for showId, order in request.form.iteritems():
        if not showId.isdigit() or not order.isdigit() or not series.userHasShow(current_user.id, showId):
            return Response(status=400)

        ordering[showId] = order

    for showId, order in ordering.iteritems():
        series.addShowToUser(current_user.id, showId, order)

    return Response(status=204)


@frontend.route('/ajax/search/<showName>')
@login_required
def ajax_search_show(showName):
    results = series.searchShow(showName)

    userShows = []
    for showId in series.getUserShowList(current_user.id):
        show = series.getShowInfo(current_user.id, showId, withEpisodes=False)
        userShows.append(show['show_id'])

    return render_template('ajax/search_results.html', results=results, userShows=userShows)


# Returns a partial view containing the posters for a show to be displayed in a popup window
@frontend.route('/ajax/posters/<showId>')
@login_required
def ajax_posters_choice(showId):
    show = series.getShowInfo(current_user.id, showId, withEpisodes=False)

    return render_template('ajax/poster_choice.html', showId=showId, posters=series.getTVDBPosters(show))


# Sets the user's custom poster. posterPath is a relative path from RheTVDB
# If no path is set, the custom poster is deleted
@frontend.route('/poster/<showId>')
@frontend.route('/poster/<showId>/<path:posterPath>')
@login_required
def set_poster(showId, posterPath=None):
    if posterPath:
        if series.setCustomPoster(current_user.id, showId, posterPath) == 200:
            flash(gettext('showdetail.posterchange.success'), 'success')
        else:
            flash(gettext('showdetail.posterchange.error'), 'error')
    else:
        if series.deleteCustomPoster(current_user.id, showId):
            flash(gettext('showdetail.posterchange.success'), 'success')
        # deleteCustomPoster returns False if there is no custom poster set, so we display nothing if it doesn't return True

    return redirect(url_for('.show_details', showId=showId))


# Downloads a poster's thumbnail from TheTVDB and passes it through to the client
# Needed because TheTVDB checks the referrer to prevent hotlinking
# We only need it to display the lightweight thumbnails, not full-res pictures
@frontend.route('/remote/thumb/<path:posterPath>')
def get_remote_thumbnail(posterPath):
    r = requests.get(SeriesDatabase.tvdbBannerCacheURLFormat % posterPath, stream=True)

    return Response(r.iter_content(chunk_size=512), mimetype=r.headers['content-type'])


@frontend.route('/thumbs/<size>/<path:posterPath>', methods=['GET'])
def get_thumbnail(size, posterPath):
    # width and height are separated by an 'x' (e.g. 187x275)
    splittedSize = size.split('x')

    if len(splittedSize) != 2 or not splittedSize[0].isdigit() or not splittedSize[1].isdigit():
        abort(400)

    width, height = [int(component) for component in splittedSize]

    img = Image.open(current_app.open_resource(posterPath))

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
