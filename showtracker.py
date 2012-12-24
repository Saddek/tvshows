from flask import Flask, request, Response, abort, jsonify
from lxml import etree
import base64
import hashlib
import json
import redis
import requests
from functools import wraps
from StringIO import StringIO

def str2bool(v):
  return v.lower() in ("yes", "true", "t", "1")

class SeriesDatabase:
    def __init__(self, host, port, database):
        self.db = redis.StrictRedis(host=host, port=port, db=database)

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

    def addShowToUser(self, user, showId):
        if not self.db.exists('show:%s' % showId):
            req = requests.get('http://services.tvrage.com/feeds/full_show_info.php?sid=%s' % showId)

            tree = etree.fromstring(req.text.encode(req.encoding))

            self.db.hset('show:%s' % showId, 'name', tree.xpath('/Show/name')[0].text)

            pipe = self.db.pipeline()
            pipe.delete('episodes:%s' % showId)

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

                    pipe.zadd('episodes:%s' % showId, episodeId, json.dumps(episodeInfo))

            pipe.execute()

        count = self.db.sadd('user:%s:shows' % user, showId)
        if count == 1:
            self.db.hincrby('show:%s' % showId, 'refcount', 1)

    def deleteShowFromUser(self, user, showId):
        self.db.hdel('user:%s:lastseen' % user, showId)
        count = self.db.srem('user:%s:shows' % user, showId)
        if count == 1:
            refcount = self.db.hincrby('show:%s' % showId, 'refcount', -1)
            if refcount <= 0:
                self.db.delete('show:%s' % showId, 'episodes:%s' % showId)

    def getLastSeen(self, user, showId):
        return self.db.hget('user:%s:lastseen' % user, showId)

    def setLastSeen(self, user, showId, episodeId):
        if episodeId:
            lastEpisode = str(episodeId).zfill(8)

            if self.db.zcount('episodes:%s' % showId, lastEpisode, lastEpisode) != 0:
                self.db.hset('user:%s:lastseen' % user, showId, lastEpisode)
        else:
            self.db.hdel('user:%s:lastseen' % user, showId)

    def getUserShowList(self, user):
        return self.db.smembers('user:%s:shows' % user)

    def userHasShow(self, user, showId):
        return self.db.sismember('user:%s:shows' % user, showId)

    def getShowInfo(self, user, showId, withEpisodes=False, episodeLimit=None, onlyUnseen=False):
        showInfo = {'show_id': showId, 'name': self.db.hget('show:%s' % showId, 'name')}

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

        for ep in self.db.zrangebyscore('episodes:%s' % showId, begin, end, start=start, num=limit):
            episodes.append(json.loads(ep))

        return episodes

series = SeriesDatabase('192.168.1.2', 6379, 1)
app = Flask(__name__)

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not series.checkAuth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

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
    series.addShowToUser(request.authorization.username, showid)
    
    if 'last_seen' in request.form:
        lastSeen = request.form['last_seen']
        if lastSeen.lower() in ('null', 'none', '-1'):
            lastSeen = None

        series.setLastSeen(request.authorization.username, showid, lastSeen)

    return jsonify(result='Success')

@app.route('/user/shows/<showid>', methods=['DELETE'])
@requires_auth
def delete_show(showid):
    series.deleteShowFromUser(request.authorization.username, showid)

    return jsonify(result='Success')

if __name__ == "__main__":
    app.run(debug=True)
