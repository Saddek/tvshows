from flask import Flask, request, Response, abort, jsonify
from lxml import etree
import base64
import hashlib
import json
import redis
import requests
from functools import wraps
from StringIO import StringIO

# TODO: user -> users in redis ?
#       lastepisode -> lastseen

db = redis.StrictRedis(host='192.168.1.2', port=6379, db=1)
app = Flask(__name__)

def check_auth(username, password):
    return db.hget('user:%s' % username, 'password') == hashlib.sha256(password).hexdigest()

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
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def getShowInfo(showId):
    return {'showid': showId, 'name': db.hget('show:%s' % showId, 'name')}

def getEpisodes(showId, begin='-inf', end='+inf', limit=None):
    episodes = []

    for ep in db.zrangebyscore('episodes:%s' % showId, begin, end, start=(None if limit == None else 0), num=limit):
        episodes.append(json.loads(ep))

    return episodes

@app.route('/search/<showName>', methods=['GET'])
def search_show(showName):
    req = requests.get('http://services.tvrage.com/feeds/search.php?show=%s' % showName)

    results = {}

    tree = etree.fromstring(req.text.encode(req.encoding))
    for e in tree.xpath('/Results/show'):
        showId = e.xpath('showid')[0].text
        results[showId] = {'name': e.xpath('name')[0].text}
    
    return jsonify(results)

@app.route('/shows', methods=['GET'])
@requires_auth
def get_user_shows():
    shows = []

    for showId in db.smembers('user:%s:shows' % request.authorization.username):
        shows.append(getShowInfo(showId))

    return jsonify(shows=shows)

@app.route('/shows/<showId>', methods=['GET'])
@requires_auth
def get_show(showId):
    if not db.sismember('user:%s:shows' % request.authorization.username, showId):
        abort(404)

    showInfo = getShowInfo(showId)

    showInfo['episodes'] = getEpisodes(showId)
    showInfo['lastepisode'] = db.hget('user:%s:lastepisodes' % request.authorization.username, showId) or -1

    return jsonify(showInfo)

@app.route('/shows/<showId>', methods=['PUT'])
@requires_auth
def add_show(showId):
    if not db.exists('show:%s' % showId):
        req = requests.get('http://services.tvrage.com/feeds/full_show_info.php?sid=%s' % showId)

        tree = etree.fromstring(req.text.encode(req.encoding))

        db.hset('show:%s' % showId, 'name', tree.xpath('/Show/name')[0].text)

        pipe = db.pipeline()
        pipe.delete('episodes:%s' % showId)

        for season in tree.xpath('/Show/Episodelist/Season'):
            seasonNum = int(season.get('no'))

            for episode in season.xpath('episode'):
                episodeNum = int(episode.xpath('seasonnum')[0].text)
                episodeId = '%04d%04d' % (seasonNum, episodeNum)

                episodeInfo = {
                    'episodeid': episodeId,
                    'title': episode.xpath('title')[0].text,
                    'season': seasonNum,
                    'episode': episodeNum,
                    'airdate': episode.xpath('airdate')[0].text
                }

                pipe.zadd('episodes:%s' % showId, episodeId, json.dumps(episodeInfo))

        pipe.execute()

    db.sadd('user:%s:shows' % request.authorization.username, showId)
    
    if 'lastEpisode' in request.form:
        lastEpisode = str(request.form['lastEpisode']).zfill(8)

        if db.zcount('episodes:%s' % showId, lastEpisode, lastEpisode) != 0:
            db.hset('user:%s:lastepisodes' % request.authorization.username, showId, lastEpisode)

    return jsonify(result='Success')

@app.route('/shows/<showId>', methods=['DELETE'])
@requires_auth
def delete_show(showId):
    # TODO: delete if last show

    db.srem('user:%s:shows' % request.authorization.username, showId)

    return jsonify(result='Success')

def getUnseenEpisodes(user, showid, limit=None):
    lastEpisode = db.hget('user:%s:lastepisodes' % user, showid) or '-inf'

    return getEpisodes(showid, '(' + lastEpisode, '+inf', limit)

@app.route('/unseen/<showid>', methods=['GET'])
@requires_auth
def get_unseen(showid):
    limit = request.args.get('limit')

    return jsonify(showid=showid, unseen=getUnseenEpisodes(request.authorization.username, showid, limit))

@app.route('/unseen', methods=['GET'])
@requires_auth
def get_all_unseen():
    limit = request.args.get('limit')
    
    unseen = []

    for showid in db.smembers('user:%s:shows' % request.authorization.username):
        unseen.append({'showid': showid, 'unseen': getUnseenEpisodes(request.authorization.username, showid, limit)})

    return jsonify(unseen=unseen)

#########

if __name__ == "__main__":
    app.run(debug=True)
