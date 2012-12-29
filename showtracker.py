from flask import Flask, request, Response, abort, jsonify
from lxml import etree
import base64
import hashlib
import json
import redis
import requests
import time
from functools import wraps
from StringIO import StringIO

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
    def __init__(self, host, port, database):
        self.db = redis.StrictRedis(host=host, port=port, db=database)

    @retry(requests.ConnectionError, tries=4, delay=1)
    def searchShow(self, showName):
        req = requests.get('http://services.tvrage.com/feeds/search.php?show=%s' % showName)
        tree = etree.fromstring(req.text.encode(req.encoding))

        results = {}
        for e in tree.xpath('/Results/show'):
            showId = e.xpath('showid')[0].text
            results[showId] = {'name': e.xpath('name')[0].text}

        return results;

    def checkAuth(self, user, password):
        return self.db.hget('user:%s' % user, 'password') == hashlib.sha256(password).hexdigest()

    @retry(requests.ConnectionError, tries=4, delay=1)
    def downloadShow(self, showId):
        req = requests.get('http://services.tvrage.com/feeds/full_show_info.php?sid=%s' % showId)

        tree = etree.fromstring(req.text.encode(req.encoding))

        pipe = self.db.pipeline()

        pipe.hset('show:%s' % showId, 'name', tree.xpath('/Show/name')[0].text)
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
        count = self.db.zrem('user:%s:shows' % user, showId)
        if count == 1:
            refcount = self.db.hincrby('shows', showId, -1)
            if refcount <= 0:
                self.db.delete('show:%s' % showId, 'show:%s:episodes' % showId)
                self.db.hdel('shows', showId)

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
        showInfo = {'show_id': showId, 'name': self.db.hget('show:%s' % showId, 'name'), 'seasons': self.db.hget('show:%s' % showId, 'seasons')}

        showInfo['last_seen'] = self.getLastSeen(user, showId)

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

series = SeriesDatabase('192.168.1.2', 6379, 1)
app = Flask(__name__)

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

@app.route('/update', methods=['POST'])
def update_shows():
    if not request.authorization or request.authorization.username != 'alex':
        return Response(status=401)

    series.update()

    return Response(status=204)

@app.route('/search/<show_name>', methods=['GET'])
def search_show(show_name):
    return jsonify(series.searchShow(show_name))

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
    app.run(host='0.0.0.0', debug=True)
