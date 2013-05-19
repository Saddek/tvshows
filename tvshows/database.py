# -*- coding: utf-8 -*-
from lxml import etree

import ConfigParser
import errno
import hashlib
import json
import os
import re
import redis
import requests

from .helpers import retry


class SeriesDatabase:
    tvdbBannerURLFormat = 'http://thetvdb.com/banners/%s'
    postersDir = os.path.join(os.path.dirname(__file__), 'static', 'posters')

    def __init__(self):
        config = ConfigParser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), 'config', 'config.cfg'))

        self.db = redis.StrictRedis(host=config.get('redis', 'host'), port=config.getint('redis', 'port'), db=config.getint('redis', 'db'))
        self.tvdbAPIKey = config.get('thetvdb', 'api_key')

        if not os.path.exists(SeriesDatabase.postersDir):
            os.makedirs(SeriesDatabase.postersDir)

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

        return results

    def checkAuth(self, user, password):
        return self.db.hget('user:%s' % user, 'password') == hashlib.sha256(password).hexdigest()

    def addUser(self, user, password):
        self.db.hset('user:%s' % user, 'password', hashlib.sha256(password).hexdigest())

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

        req = requests.get('http://www.thetvdb.com/api/%s/series/%s/banners.xml' % (self.tvdbAPIKey, tvdbId))
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

        req = requests.get(SeriesDatabase.tvdbBannerURLFormat % posters[0])
        if req.status_code == 200:
            with open(self.posterFilename(showInfo['show_id']), 'wb') as f:
                f.write(req.content)

    def setCustomPoster(self, user, showId, posterURL):
        req = requests.get(SeriesDatabase.tvdbBannerURLFormat % posterURL)

        posterFile = self.posterFilename(showId, user=user)
        posterDir = os.path.dirname(posterFile)

        if not os.path.exists(posterDir):
            os.makedirs(os.path.dirname(posterFile))

        if req.status_code == 200:
            with open(posterFile, 'wb') as f:
                f.write(req.content)

        return req.status_code

    def deleteCustomPoster(self, user, showId):
        posterFile = self.posterFilename(showId, user=user)
        posterDir = os.path.dirname(posterFile)

        if not os.path.exists(posterFile):
            return False

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
            return os.path.join(SeriesDatabase.postersDir, user, filename)

        return os.path.join(SeriesDatabase.postersDir, filename)

    @retry(requests.ConnectionError, tries=4, delay=1)
    def downloadShow(self, showId):
        req = requests.get('http://services.tvrage.com/feeds/full_show_info.php?sid=%s' % showId)

        tree = etree.fromstring(req.text.encode(req.encoding))

        showName = tree.xpath('/Show/name')[0].text

        pipe = self.db.pipeline()

        pipe.delete('show:%s' % showId)

        pipe.hset('show:%s' % showId, 'name', showName)
        pipe.hset('show:%s' % showId, 'seasons', int(tree.xpath('count(/Show/Episodelist/Season)')))
        pipe.hset('show:%s' % showId, 'status', tree.xpath('/Show/status')[0].text)

        country = tree.xpath('/Show/origin_country')[0].text
        pipe.hset('show:%s' % showId, 'country', country)

        network = tree.xpath('/Show/network[@country="%s"]' % country)
        if network:
            pipe.hset('show:%s' % showId, 'network', network[0].text)

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

        # the date format in "started" and "ended" tags of the feed are not in a standard date format
        # so we retrieve the first episode of the list to get the show's first airing date
        episodes = self.__getEpisodes(showId)
        if len(episodes) > 0:
            self.db.hset('show:%s' % showId, 'firstaired', episodes[0]['airdate'])

            if tree.xpath('/Show/ended[node()]'):
                self.db.hset('show:%s' % showId, 'lastaired', episodes[-1]['airdate'])

        if not os.path.exists(self.posterFilename(showId)):
            self.downloadPoster({'show_id': showId, 'name': showName, 'first_aired': episodes[0]['airdate'] if len(episodes) > 0 else None})

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

    def userExists(self, user):
        return self.db.exists('user:%s' % user)

    def getUserShowList(self, user):
        return self.db.zrangebyscore('user:%s:shows' % user, '-inf', '+inf')

    def userHasShow(self, user, showId):
        return self.db.zscore('user:%s:shows' % user, showId) is not None

    def userHasShows(self, user, showIds):
        pipe = self.db.pipeline()
        for showId in showIds:
            pipe.zscore('user:%s:shows' % user, showId)

        return not None in pipe.execute()

    def getShowInfo(self, user, showId, withEpisodes=True, episodeLimit=None, onlyUnseen=False):
        showInfo = {
            'show_id': showId,
            'name': self.db.hget('show:%s' % showId, 'name'),
            'status': self.db.hget('show:%s' % showId, 'status'),
            'country': self.db.hget('show:%s' % showId, 'country'),
            'network': self.db.hget('show:%s' % showId, 'network'),
            'seasons': self.db.hget('show:%s' % showId, 'seasons'),
            'last_seen': self.getLastSeen(user, showId),
            'first_aired': self.db.hget('show:%s' % showId, 'firstaired')
        }

        lastAired = self.db.hget('show:%s' % showId, 'lastaired')
        if lastAired:
            showInfo['last_aired'] = lastAired

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
