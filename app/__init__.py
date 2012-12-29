from flask import Flask, render_template
from datetime import date
import calendar
import requests

app = Flask(__name__)
app.config.from_object('config')

def episodeNumber(episode):
	return 'S%02dE%02d' % (episode['season'], episode['episode'])

app.jinja_env.filters['episodeNumber'] = episodeNumber

# sorts episodes by date
def showSortKey(show):
	airdate = show['episodes'][0]['airdate']

	year, month, day = airdate.split('-')

	if month == '00':
		return '%s-12-31' % year

	if day == '00':
		return '%s-%s-%s' % (year, month, calendar.monthrange(int(year), int(month))[1])

	return airdate

@app.route('/')
def home():
	res = requests.get('http://seriesv2.madjawa.net/api/user/shows?episodes=true&unseen=true&limit=1', auth=('alex', '42'))

	shows = res.json()['shows']

	# we keep only shows with unseen episodes
	unseen = [show for show in shows if len(show['episodes']) > 0]

	# sorting by reverse air date
	unseen.sort(key=showSortKey, reverse=True)
	
	today = date.today().strftime('%Y-%m-%d')
	i = 0
	for show in unseen:
		if show['episodes'][0]['airdate'] < today: break
		i += 1

	return render_template('home.html', unseen=unseen[i:], upcoming=unseen[:i])
