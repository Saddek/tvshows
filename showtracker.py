from bottle import route, request, response, abort, get, post, put, delete, run
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
loggedUser = None

def requires_auth(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        if request.headers.get('Authorization'):
            authHeader = request.headers.get('Authorization').split(' ')
            scheme = authHeader[0]

            if scheme == 'Basic':
                decoded = base64.b64decode(authHeader[1])
                user, password = decoded.split(':')
                
                if db.hget('user:%s' % user, 'password') == hashlib.sha256(password).hexdigest():
                    loggedUser = user
                    return f(*args, **kwds)

        response.set_header('WWW-Authenticate', 'Basic realm="Authentication required"')
        response.status = 401

    return wrapper

def getShowInfo(showId):
    return {'showid': showId, 'name': db.hget('show:%s' % showId, 'name')}

def getEpisodes(showId, begin='-inf', end='+inf', limit=None):
    episodes = []

    for ep in db.zrangebyscore('episodes:%s' % showId, begin, end, start=(None if limit == None else 0), num=limit):
        episodes.append(json.loads(ep))

    return episodes

@get('/search/<showName>')
def search_show(showName):
    req = requests.get('http://services.tvrage.com/feeds/search.php?show=%s' % showName)

    results = {}

    tree = etree.fromstring(req.text.encode(req.encoding))
    for e in tree.xpath('/Results/show'):
        showId = e.xpath('showid')[0].text
        results[showId] = {'name': e.xpath('name')[0].text}
    
    return results

@get('/shows')
@requires_auth
def get_user_shows():
    shows = []

    for showId in db.smembers('user:%s:shows' % loggedUser):
        shows.append(getShowInfo(showId))

    return {'shows': shows}

@get('/shows/<showId>')
@requires_auth
def get_show(showId):
    if not db.sismember('user:%s:shows' % loggedUser, showId):
        abort(404)

    showInfo = getShowInfo(showId)

    showInfo['episodes'] = getEpisodes(showId)
    showInfo['lastepisode'] = db.hget('user:%s:lastepisodes' % loggedUser, showId) or -1

    return showInfo

@put('/shows/<showId>')
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

    db.sadd('user:%s:shows' % loggedUser, showId)

    if request.body.len > 0:
        body = json.load(request.body)

        if body['lastEpisode']:
            lastEpisode = str(body['lastEpisode']).zfill(8)

            if db.zcount('episodes:%s' % showId, lastEpisode, lastEpisode) != 0:
                db.hset('user:%s:lastepisodes' % loggedUser, showId, lastEpisode)

@delete('/shows/<showId>')
@requires_auth
def delete_show(showId):
    # TODO: delete if last show

    db.srem('user:%s:shows' % loggedUser, showId)

def getUnseenEpisodes(user, showid, limit=None):
    lastEpisode = db.hget('user:%s:lastepisodes' % user, showid) or '-inf'

    return getEpisodes(showid, '(' + lastEpisode, '+inf', limit)

@get('/unseen/<showid>')
@requires_auth
def get_unseen(showid):
    limit = int(request.query.limit) if request.query.limit else None

    return {'showid': showid, 'unseen': getUnseenEpisodes(loggedUser, showid, limit)}

@get('/unseen')
@requires_auth
def get_all_unseen():
    limit = int(request.query.limit) if request.query.limit else None
    
    unseen = []

    for showid in db.smembers('user:%s:shows' % loggedUser):
        unseen.append({'showid': showid, 'unseen': getUnseenEpisodes(loggedUser, showid, limit)})

    return {'unseen': unseen}

#########

run(host='localhost', port=8080)
