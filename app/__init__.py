# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, Response, jsonify, url_for, redirect, session, flash, abort, send_file
from flask.ext.login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask.ext.babel import Babel, gettext, ngettext, lazy_gettext, format_date
from datetime import date, datetime
from StringIO import StringIO
import calendar
import Image
import locale
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
	# remove content in parenthesis from the name if they are present (like the year)
	# because they are not included in release names most of the time
	strippedName = re.sub(r'\(.+?\)', '', show['name']).strip()
	searchString = '%s %s' % (strippedName, episodeNumber(episode))

	return 'http://thepiratebay.se/search/%s/0/99/208' % urllib.quote_plus(searchString)

def addic7edLink(show, episode):
	# remove content in parenthesis AND keep only alphanum, spaces and colon for Addic7ed
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

	daysDiff = (date.today() - parsedDate).days
	if daysDiff == 0:
		return gettext('date.tonight')
	elif daysDiff == 1:
		return gettext('date.yesterday_night')
	elif daysDiff == -1:
		return gettext('date.tomorrow_night')
	elif abs(daysDiff) < 7:
		format = gettext('date.format.next_day')

	formattedDate = format_date(parsedDate, format)

	return formattedDate

app.jinja_env.filters['episodeNumber'] = episodeNumber
app.jinja_env.filters['prettyDate'] = prettyDate
app.jinja_env.filters['pirateBayLink'] = pirateBayLink
app.jinja_env.filters['addic7edLink'] = addic7edLink
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
	res = requests.get('%s/user/shows?episodes=true&unseen=true' % apiURL, auth=credentials())

	shows = [show for show in res.json()['shows'] if len(show['episodes']) > 0]

	today = date.today().strftime('%Y-%m-%d')
	for show in shows:
		show['unseenEpisodes']   = [episode for episode in show['episodes'] if airdateKey(episode['airdate']) < today and episode['airdate'] != '0000-00-00']
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
	res = requests.get('%s/user/shows' % apiURL, auth=credentials())

	shows = res.json()['shows']
	
	for show in shows:
		if 'poster' in show:
			show['poster_path'] = '%s/%s' % (apiURL, show['poster'])

	return render_template('shows.html', shows=shows)

@app.route('/show/<showId>/')
@login_required
def show_details(showId):
	res = requests.get('%s/user/shows/%s' % (apiURL, showId), auth=credentials())

	show = res.json()
	
	if 'poster' in show:
		show['poster_path'] = '%s/%s' % (apiURL, show['poster'])

	return render_template('showdetails.html', show=show)

@app.route('/login', methods=['GET', 'POST'])
def login():
	if request.method == 'POST':
		user = User(request.form['username'])
		password = request.form['password']
		remember = bool(request.form.get('remember', False))

		r = requests.get('%s/user/shows' % apiURL, auth=(user.id, password))

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
	r = requests.put('%s/user/shows/%s/last_seen' % (apiURL, showId), data=episodeId, auth=credentials())

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

	res = requests.post('%s/user/shows_order' % apiURL, data=ordering, auth=credentials())

	if res.status_code != 204:
		return Response(status=500)

	return Response(status=204)

@app.route('/thumbs/', methods=['GET'])
#@login_required
def get_thumbnail():
	url = request.args.get('url')

	if not url: abort(400)

	r = requests.get(url, stream=True)

	img = Image.open(StringIO(r.content))

	#img = img.rotate(45)
	img.thumbnail((187, 275), Image.ANTIALIAS)

	thumbnail = StringIO()
	print img.format
	img.save(thumbnail, 'JPEG', quality=95, optimize=True, progressive=True)
	thumbnail.seek(0)

	return send_file(thumbnail, mimetype='image/jpeg')
