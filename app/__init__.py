# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, Response, jsonify, url_for, redirect, session, flash
from flask.ext.login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from datetime import date, datetime
import calendar
import locale
import os
import requests

class User(UserMixin):
	def __init__(self, userId):
		super(User, self).__init__()
		self.id = userId

app = Flask(__name__)
login_manager = LoginManager()

app.config.from_object('config')
app.config['SECRET_KEY'] = os.urandom(24)

login_manager.setup_app(app)
login_manager.login_view = 'login'
login_manager.login_message = u'Merci de vous identifier pour accéder à cette page'

SERIES_API_URL = 'http://seriesv2.madjawa.net/api'

def credentials():
	return (current_user.id, current_user.password)

@login_manager.user_loader
def load_user(userId):
	user = User(userId)
	user.password = session['password'] if 'password' in session else None
	return user

locale.setlocale(locale.LC_ALL, 'fr_FR')

def episodeNumber(episode):
	return 'S%02dE%02d' % (episode['season'], episode['episode'])

def prettyDate(dateStr, forceYear=False, addPrefix=False):
	year, month, day = [int(component) for component in dateStr.split('-')]

	if year == 0:
		return 'Inconnu'

	if month == 0:
		parsedDate = date(year, 1, 1)
		prefix = 'en ' if addPrefix else None
		format = '%Y'
	elif day == 0:
		parsedDate = date(year, month, 1)
		prefix = 'en ' if addPrefix else None
		format = '%B %Y'
	else:
		parsedDate = date(year, month, day)
		prefix = 'le ' if addPrefix else None
		format = '%d %B %Y' if forceYear or year != date.today().year else '%d %B'

	if abs((date.today() - parsedDate).days) <= 7:
		prefix = ''
		format = '%A'

	formattedDate = parsedDate.strftime(format).lstrip('0').lower()

	if prefix:
		formattedDate = prefix + formattedDate

	return formattedDate.decode('utf-8')

app.jinja_env.filters['episodeNumber'] = episodeNumber
app.jinja_env.filters['prettyDate'] = prettyDate
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
	res = requests.get('%s/user/shows?episodes=true&unseen=true' % SERIES_API_URL, auth=credentials())

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
	res = requests.get('%s/user/shows' % SERIES_API_URL, auth=credentials())

	shows = res.json()['shows']
	
	for show in shows:
		if 'poster' in show:
			show['poster_path'] = '%s/%s' % (SERIES_API_URL, show['poster'])

	return render_template('shows.html', shows=shows)

@app.route('/show/<showId>/')
@login_required
def show_details(showId):
	res = requests.get('%s/user/shows/%s' % (SERIES_API_URL, showId), auth=credentials())

	show = res.json()
	
	if 'poster' in show:
		show['poster_path'] = '%s/%s' % (SERIES_API_URL, show['poster'])

	return render_template('showdetails.html', show=show)

@app.route('/login', methods=['GET', 'POST'])
def login():
	if request.method == 'POST':
		user = User(request.form['username'])
		password = request.form['password']
		remember = bool(request.form.get('remember', False))

		r = requests.get('%s/user/shows' % SERIES_API_URL, auth=(user.id, password))

		if r.status_code == 200:
			login_user(user, remember=remember)
			session['password'] = password
			return redirect(request.args.get('next') or url_for('home'))
		else:
			flash(u'Identifiants invalides', 'error')

	return render_template('login.html')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash(u'Déconnecté avec succès', 'success')
    return redirect(url_for('login'))

@app.route('/ajax/unseen/<showId>/<episodeId>')
@login_required
def ajax_home_unseen(showId, episodeId):
	r = requests.put('%s/user/shows/%s/last_seen' % (SERIES_API_URL, showId), data=episodeId, auth=credentials())

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

	res = requests.post('%s/user/shows_order' % SERIES_API_URL, data=ordering, auth=credentials())

	if res.status_code != 204:
		return Response(status=500)

	return Response(status=204)
