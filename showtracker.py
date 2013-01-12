from flask import Flask, request, Response, abort, jsonify
from lxml import etree
import base64
import errno
import hashlib
import json
import os
import re
import redis
import requests
import time
from functools import wraps
from StringIO import StringIO

app = Flask(__name__)

# TODO: check that all needed config variables are set
app.config.from_pyfile('config.cfg')

tvdbAPIKey = app.config['TVDB_API_KEY']
tvdbBannerURLFormat = 'http://thetvdb.com/banners/%s'

postersDir = os.path.join(os.path.dirname(__file__), 'static', 'posters')
if not os.path.exists(postersDir): os.makedirs(postersDir)

def str2bool(v):
  return v.lower() in ("yes", "true", "t", "1")

def retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    :param ExceptionToCheck: the exception to check. may be a tuple of
        excpetions to check
    :type ExceptionToCheck: Exception or tuple
    :param tries: number of times to try (not retry) before giving up
    :type tries: int
    :param delay: initial delay between retries in seconds
    :type delay: int
    :param backoff: backoff multiplier e.g. value of 2 will double the delay
        each retry
    :type backoff: int
    :param logger: logger to use. If None, print
    :type logger: logging.Logger instance
    """
    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            try_one_last_time = True
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                    try_one_last_time = False
                    break
                except ExceptionToCheck, e:
                    msg = "%s, Retrying in %d seconds..." % (str(e), mdelay)
                    if logger:
                        logger.warning(msg)
                    else:
                        print msg
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            if try_one_last_time:
                return f(*args, **kwargs)
            return
        return f_retry  # true decorator
    return deco_retry

class SeriesDatabase:
    def __init__(self):
        self.db = redis.StrictRedis(host=app.config['REDIS_HOST'], port=app.config['REDIS_PORT'], db=app.config['REDIS_DB'])

    @retry(requests.ConnectionError, tries=4, delay=1)
    def searchShow(self, showName):
        req = requests.get('http://services.tvrage.com/feeds/search.php?show=%s' % showName)
        tree = etree.fromstring(req.text.encode(req.encoding))

        results = []
        for e in tree.xpath('/Results/show'):
            showId = e.xpath('showid')[0].text
            results.append({
                'id': showId,
                'name': e.xpath('name')[0].text,
                'seasons': int(e.xpath('seasons')[0].text),
                'started': int(e.xpath('started')[0].text),
                'ended': int(e.xpath('ended')[0].text),
                'genres': [genre.text for genre in e.xpath('genres/genre')]
            })
        
        return results;

    def checkAuth(self, user, password):
        return self.db.hget('user:%s' % user, 'password') == hashlib.sha256(password).hexdigest()

    @retry(requests.ConnectionError, tries=4, delay=1)
    def getTVDBID(self, showInfo):
        print 'Searching TVDB for "%s"...' % showInfo['name']
        req = requests.get('http://www.thetvdb.com/api/GetSeries.php?seriesname=%s' % showInfo['name'])
        tree = etree.fromstring(req.text.encode(req.encoding))

        if len(tree) == 0:
            # remove parenthesis (TVRage sometimes include the country or year in the show name and not TVDB)
            strippedName = re.compile('\(.+?\)').sub('', showInfo['name']).strip()

            print ' No results, trying "%s"...' % strippedName
            req = requests.get('http://www.thetvdb.com/api/GetSeries.php?seriesname=%s' % strippedName)
            tree = etree.fromstring(req.text.encode(req.encoding))

            if len(tree) == 0:
                print ' Still nothing, giving up.'
                return None

        print 'We got results! Getting the results with the same air date'
        matches = tree.xpath('/Data/Series[FirstAired="%s"]/seriesid' % showInfo['first_aired'])

        if len(matches) == 0:
            print 'Nothing. Getting first result instead'
            matches = tree.xpath('/Data/Series/seriesid')
        
            if len(matches) == 0:
                print 'What the fuck?'
                return None

        print 'TVDB ID for %s: %s' % (showInfo['name'], matches[0].text)
        return matches[0].text

    @retry(requests.ConnectionError, tries=4, delay=1)
    def getTVDBPosters(self, showInfo):
        tvdbId = self.getTVDBID(showInfo)

        req = requests.get('http://www.thetvdb.com/api/%s/series/%s/banners.xml' % (tvdbAPIKey, tvdbId))
        tree = etree.fromstring(req.text.encode(req.encoding))

        posters = []
        for poster in tree.xpath('/Banners/Banner[BannerType="poster"]'):
            rating = poster.xpath('Rating')[0].text or 0
            voters = poster.xpath('RatingCount')[0].text or 0

            posters.append({
                'path': poster.xpath('BannerPath')[0].text,
                'rating': float(rating),
                'voters': int(voters)
            })

        maxVoters = 0
        for poster in posters:
            if poster['voters'] > maxVoters:
                maxVoters = poster['voters']

        for poster in posters:
            if poster['voters'] == 0:
                poster['weightedRating'] = 0
            else:
                poster['weightedRating'] = poster['rating'] * (poster['voters'] / float(maxVoters))

        posters.sort(key=lambda e: e['weightedRating'], reverse=True)
        
        return [poster['path'] for poster in posters]

    @retry(requests.ConnectionError, tries=4, delay=1)
    def downloadPoster(self, showInfo):
        posters = self.getTVDBPosters(showInfo)

        if len(posters) == 0:
            return

        req = requests.get(tvdbBannerURLFormat % posters[0])
        if req.status_code == 200:
            with open(self.posterFilename(showInfo['show_id']), 'wb') as code:
                code.write(req.content)


    def deleteCustomPoster(self, user, showId):
        posterFile = series.posterFilename(showId, user=user);
        posterDir = os.path.dirname(posterFile)

        if not os.path.exists(posterFile): return False

        os.remove(posterFile)

        try:
            os.rmdir(posterDir)
        except OSError as e:
            if e.errno == errno.ENOTEMPTY:
                pass
            else:
                raise

        return True

    def posterFilename(self, showId, user=None):
        filename = '%s.jpg' % showId
        
        if user:
            return os.path.join(postersDir, user, filename)
        
        return os.path.join(postersDir, filename)

    @retry(requests.ConnectionError, tries=4, delay=1)
    def downloadShow(self, showId):
        req = requests.get('http://services.tvrage.com/feeds/full_show_info.php?sid=%s' % showId)

        tree = etree.fromstring(req.text.encode(req.encoding))

        showName = tree.xpath('/Show/name')[0].text

        pipe = self.db.pipeline()

        pipe.hset('show:%s' % showId, 'name', showName)
        pipe.hset('show:%s' % showId, 'seasons', int(tree.xpath('count(/Show/Episodelist/Season)')))

        pipe.delete('show:%s:episodes' % showId)
        for season in tree.xpath('/Show/Episodelist/Season'):
            seasonNum = int(season.get('no'))

            for episode in season.xpath('episode'):
                episodeNum = int(episode.xpath('seasonnum')[0].text)
                episodeId = '%04d%04d' % (seasonNum, episodeNum)

                episodeInfo = {
                    'episode_id': episodeId,
                    'title': episode.xpath('title')[0].text,
                    'season': seasonNum,
                    'episode': episodeNum,
                    'airdate': episode.xpath('airdate')[0].text
                }

                pipe.zadd('show:%s:episodes' % showId, episodeId, json.dumps(episodeInfo))

        pipe.execute()

        episodes = self.__getEpisodes(showId, limit=1)
        firstAired = episodes[0]['airdate'] if len(episodes) > 0 else None

        self.db.hset('show:%s' % showId, 'firstaired', firstAired)

        if not os.path.exists(self.posterFilename(showId)):
            self.downloadPoster({'show_id': showId, 'name': showName, 'first_aired': firstAired})

    @retry(requests.ConnectionError, tries=4, delay=1)
    def update(self):
        print "Starting daily update..."
        allShows = set(self.db.hkeys('shows'))

        req = requests.get('http://services.tvrage.com/feeds/last_updates.php?hours=36')
        tree = etree.fromstring(req.text.encode(req.encoding))

        updatedShows = tree.xpath('/updates/show/id/text()')

        for show in allShows.intersection(updatedShows):
            self.downloadShow(show)
            print " - Updated", show

        print "Update done."

    def addShowToUser(self, user, showId, order=0):
        if not self.db.exists('show:%s' % showId):
            self.downloadShow(showId)

        count = self.db.zadd('user:%s:shows' % user, order, showId)
        if count == 1:
            self.db.hincrby('shows', showId, 1)

    def deleteShowFromUser(self, user, showId):
        self.db.hdel('user:%s:lastseen' % user, showId)
        self.deleteCustomPoster(user, showId)
        count = self.db.zrem('user:%s:shows' % user, showId)
        if count == 1:
            refcount = self.db.hincrby('shows', showId, -1)
            if refcount <= 0:
                self.db.delete('show:%s' % showId, 'show:%s:episodes' % showId)
                self.db.hdel('shows', showId)

                posterFile = self.posterFilename(showId)
                if os.path.exists(posterFile):
                    os.remove(posterFile)

    def getLastSeen(self, user, showId):
        return self.db.hget('user:%s:lastseen' % user, showId)

    def setLastSeen(self, user, showId, episodeId):
        if episodeId:
            lastEpisode = str(episodeId).zfill(8)

            if self.db.zcount('show:%s:episodes' % showId, lastEpisode, lastEpisode) != 0:
                self.db.hset('user:%s:lastseen' % user, showId, lastEpisode)
            else:
                return False
        else:
            self.db.hdel('user:%s:lastseen' % user, showId)

        return True

    def getUserShowList(self, user):
        return self.db.zrangebyscore('user:%s:shows' % user, '-inf', '+inf')

    def userHasShow(self, user, showId):
        return self.db.zscore('user:%s:shows' % user, showId) != None

    def userHasShows(self, user, showIds):
        pipe = self.db.pipeline()
        for showId in showIds:
            pipe.zscore('user:%s:shows' % user, showId)

        return not None in pipe.execute()

    def getShowInfo(self, user, showId, withEpisodes=False, episodeLimit=None, onlyUnseen=False):
        showInfo = {
            'show_id': showId,
            'name': self.db.hget('show:%s' % showId, 'name'),
            'seasons': self.db.hget('show:%s' % showId, 'seasons'),
            'first_aired': self.db.hget('show:%s' % showId, 'firstaired')
        }

        showInfo['last_seen'] = self.getLastSeen(user, showId)

        if os.path.exists(self.posterFilename(showId, user=user)):
            showInfo['poster'] = 'static/posters/%s/%s.jpg' % (user, showId)
        elif os.path.exists(self.posterFilename(showId)):
            showInfo['poster'] = 'static/posters/%s.jpg' % showId

        if withEpisodes:
            if onlyUnseen:
                lastEpisode = self.db.hget('user:%s:lastseen' % user, showId) or '-inf'
                showInfo['episodes'] = self.__getEpisodes(showId, begin='(' + lastEpisode, limit=episodeLimit)
            else:
                showInfo['episodes'] = self.__getEpisodes(showId, limit=episodeLimit)

        return showInfo

    def __getEpisodes(self, showId, begin='-inf', end='+inf', limit=None):
        limit = limit or None
        start = 0 if limit else None

        episodes = []

        for ep in self.db.zrangebyscore('show:%s:episodes' % showId, begin, end, start=start, num=limit):
            episodes.append(json.loads(ep))

        return episodes

series = SeriesDatabase()

def authenticate():
    response = jsonify(message='You have to login with proper credentials')
    response.status_code = 401
    response.headers.add('WWW-Authenticate', 'Basic realm="Login required"')

    return response

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not series.checkAuth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/posters/<showid>', methods=['GET'])
@requires_auth
def get_poster(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    showInfo = series.getShowInfo(request.authorization.username, showid)

    posters = series.getTVDBPosters(showInfo)

    return jsonify(posters=posters)

@app.route('/posters/<showid>', methods=['POST'])
@requires_auth
def set_custom_poster(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    req = requests.get(tvdbBannerURLFormat % request.form['posterURL'])

    posterFile = series.posterFilename(showid, user=request.authorization.username);
    posterDir = os.path.dirname(posterFile)

    if not os.path.exists(posterDir):
        os.makedirs(os.path.dirname(posterFile))

    if req.status_code == 200:
        with open(posterFile, 'wb') as code:
            code.write(req.content)

        return Response(status=204)
    elif req.status_code == 404:
        response = jsonify(message='Invalid posterURL')
        response.status_code = 400
        return response
    else:
        abort(500)

@app.route('/posters/<showid>', methods=['DELETE'])
@requires_auth
def delete_custom_poster(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    if not series.deleteCustomPoster(request.authorization.username, showid):
        response = jsonify(message='There is no custom poster for showID %s' % showid)
        response.status_code = 400
        return response

    return Response(status=204)

@app.route('/update', methods=['POST'])
def update_shows():
    if not request.authorization or request.authorization.username != 'alex':
        return Response(status=401)

    series.update()

    return Response(status=204)

@app.route('/search/<show_name>', methods=['GET'])
def search_show(show_name):
    return jsonify(results=series.searchShow(show_name))

@app.route('/user/shows', methods=['GET'])
@requires_auth
def get_user_shows():
    withEpisodes = str2bool(request.args.get('episodes', 'false'))
    episodeLimit = int(request.args.get('limit', '0'))
    onlyUnseen = str2bool(request.args.get('unseen', 'false'))

    shows = []
    for showid in series.getUserShowList(request.authorization.username):
        shows.append(series.getShowInfo(request.authorization.username, showid, withEpisodes=withEpisodes, episodeLimit=episodeLimit, onlyUnseen=onlyUnseen))

    return jsonify(shows=shows)

@app.route('/user/shows/<showid>', methods=['GET'])
@requires_auth
def get_show(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    withEpisodes = str2bool(request.args.get('episodes', 'true'))
    episodeLimit = int(request.args.get('limit', '0'))
    onlyUnseen = str2bool(request.args.get('unseen', 'false'))

    showInfo = series.getShowInfo(request.authorization.username, showid, withEpisodes=withEpisodes, episodeLimit=episodeLimit, onlyUnseen=onlyUnseen)

    return jsonify(showInfo)

@app.route('/user/shows/<showid>', methods=['PUT'])
@requires_auth
def add_show(showid):
    shouldAdd = not series.userHasShow(request.authorization.username, showid)

    if shouldAdd:
        series.addShowToUser(request.authorization.username, showid)

    response = jsonify(series.getShowInfo(request.authorization.username, showid))

    response.status_code = 201 if shouldAdd else 200

    return response

@app.route('/user/shows/<showid>/last_seen', methods=['PUT'])
@requires_auth
def change_show(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    lastSeen = request.data
    if lastSeen.lower() in ('null', 'none', '-1'):
        lastSeen = None
    elif not lastSeen.isdigit():
        abort(400)

    if not series.setLastSeen(request.authorization.username, showid, lastSeen):
        response = jsonify(message='Invalid episode_id %s' % lastSeen)
        response.status_code = 400
        return response

    return Response(status=204)

@app.route('/user/shows/<showid>', methods=['DELETE'])
@requires_auth
def delete_show(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)
    
    series.deleteShowFromUser(request.authorization.username, showid)

    return Response(status=204)

@app.route('/user/shows_order', methods=['POST'])
@requires_auth
def reorder_shows():
    if not series.userHasShows(request.authorization.username, request.form.keys()):
        response = jsonify(message='One or more show_id is invalid')
        response.status_code = 400
        return response

    for showId, order in request.form.iteritems():
        if not order.isdigit():
            response = jsonify(message='Invalid order value %s' % order)
            response.status_code = 400
            return response

        series.addShowToUser(request.authorization.username, showId, order)

    return Response(status=204)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001)
