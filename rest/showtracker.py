from flask import Blueprint, request, Response, abort, jsonify
from seriesdatabase import SeriesDatabase
from functools import wraps

rest = Blueprint('rest', __name__)

series = SeriesDatabase()


def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")


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


@rest.route('/posters/<showid>', methods=['GET'])
@requires_auth
def get_poster(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    showInfo = series.getShowInfo(request.authorization.username, showid)

    posters = series.getTVDBPosters(showInfo)

    return jsonify(posters=posters)


@rest.route('/posters/<showid>', methods=['POST'])
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


@rest.route('/posters/<showid>', methods=['DELETE'])
@requires_auth
def delete_custom_poster(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    if not series.deleteCustomPoster(request.authorization.username, showid):
        response = jsonify(message='There is no custom poster for showID %s' % showid)
        response.status_code = 400
        return response

    return Response(status=204)


@rest.route('/update', methods=['POST'])
def update_shows():
    if not request.authorization or request.authorization.username != 'alex':
        return Response(status=401)

    series.update()

    return Response(status=204)


@rest.route('/search/<show_name>', methods=['GET'])
def search_show(show_name):
    return jsonify(results=series.searchShow(show_name))


@rest.route('/user/shows', methods=['GET'])
@requires_auth
def get_user_shows():
    withEpisodes = str2bool(request.args.get('episodes', 'false'))
    episodeLimit = int(request.args.get('limit', '0'))
    onlyUnseen = str2bool(request.args.get('unseen', 'false'))

    shows = []
    for showid in series.getUserShowList(request.authorization.username):
        shows.append(series.getShowInfo(request.authorization.username, showid, withEpisodes=withEpisodes, episodeLimit=episodeLimit, onlyUnseen=onlyUnseen))

    return jsonify(shows=shows)


@rest.route('/user/shows/<showid>', methods=['GET'])
@requires_auth
def get_show(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    withEpisodes = str2bool(request.args.get('episodes', 'true'))
    episodeLimit = int(request.args.get('limit', '0'))
    onlyUnseen = str2bool(request.args.get('unseen', 'false'))

    showInfo = series.getShowInfo(request.authorization.username, showid, withEpisodes=withEpisodes, episodeLimit=episodeLimit, onlyUnseen=onlyUnseen)

    return jsonify(showInfo)


@rest.route('/user/shows/<showid>', methods=['PUT'])
@requires_auth
def add_show(showid):
    shouldAdd = not series.userHasShow(request.authorization.username, showid)

    if shouldAdd:
        series.addShowToUser(request.authorization.username, showid)

    response = jsonify(series.getShowInfo(request.authorization.username, showid))

    response.status_code = 201 if shouldAdd else 200

    return response


@rest.route('/user/shows/<showid>/last_seen', methods=['PUT'])
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


@rest.route('/user/shows/<showid>', methods=['DELETE'])
@requires_auth
def delete_show(showid):
    if not series.userHasShow(request.authorization.username, showid):
        abort(404)

    series.deleteShowFromUser(request.authorization.username, showid)

    return Response(status=204)


@rest.route('/user/shows_order', methods=['POST'])
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
