from flask import Flask, request, Response, abort, jsonify
import errno
import os
import re
from seriesdatabase import SeriesDatabase
from functools import wraps

app = Flask(__name__)

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


def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")


series = SeriesDatabase(app.config['REDIS_HOST'], app.config['REDIS_PORT'], app.config['REDIS_DB'], app.config['TVDB_API_KEY'])


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

    statusCode = series.setCustomPoster(request.authorization.username, showid, request.form['posterURL'])

    if statusCode == 200:
        return Response(status=204)
    elif statusCode == 404:
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


@app.route('/signup', methods=['POST'])
def signup():
    username = request.form['username'].lower()
    if re.match('^[\w-]+$', username) is None:
        response = jsonify(message='Invalid username')
        response.status_code = 400
        return response

    if series.userExists(username):
        return Response(status=409)

    password = request.form['password']

    if len(password) == 0:
        return Response(status=400)

    series.addUser(username, password)

    return Response(status=204)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001)
