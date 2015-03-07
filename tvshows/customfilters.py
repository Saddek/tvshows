# -*- coding: utf-8 -*-
from datetime import date
from flask.ext.babel import gettext, format_date

import ConfigParser
import os
import re
import urllib

overrides = ConfigParser.ConfigParser()
overrides.read(os.path.join(os.path.dirname(__file__), 'config', 'overrides.cfg'))


def episodeNumber(episode):
    return 'S%02dE%02d' % (episode['season'], episode['episode'])


def downloadLink(show, episode):
    # Remove content in parenthesis from the name if they are present (like the year)
    # because they are not included in release names most of the time
    # Also remove everything that is not alphanumeric or whitespace (such has apostrophes)
    strippedName = re.sub(r'\(.+?\)|([^\s\w])+', '', show['name']).strip()
    searchString = '%s %s 720p category:tv' % (strippedName, episodeNumber(episode))

    return 'https://kickass.to/usearch/%s/?field=seeders&sorder=desc' % urllib.quote(searchString)


def addic7edLink(show, episode):
    if overrides.has_option(show['show_id'], 'addic7ed_str'):
        # get the addic7ed string from the overrides file if it's defined
        strippedName = overrides.get(show['show_id'], 'addic7ed_str')
    else:
        # else, remove content in parenthesis AND keep only alphanum, spaces and colon
        strippedName = re.sub(r'[^\s\w:]', '', re.sub(r'\(.+?\)', '', show['name'])).strip().replace(' ', '_')

    return 'http://www.addic7ed.com/serie/%s/%s/%s/episode' % (urllib.quote_plus(strippedName), episode['season'], episode['episode'])


def prettyDate(dateStr, forceYear=False, addPrefix=False):
    year, month, day = [int(component) for component in dateStr.split('-')]

    if year == 0:
        return gettext('date.unknown')

    if month == 0:
        parsedDate = date(year, 1, 1)
        format = gettext('date.format.year_only')

        if addPrefix:
            format = gettext('date.in_year_%(year)s', year=format)
    elif day == 0:
        parsedDate = date(year, month, 1)
        format = gettext('date.format.year_month')

        if addPrefix:
            format = gettext('date.in_month_%(month)s', month=format)
    else:
        parsedDate = date(year, month, day)
        format = gettext('date.format.date_with_year') if forceYear or year != date.today().year else gettext('date.format.date_without_year')

        if addPrefix:
            format = gettext('date.on_day_%(day)s', day=format)

    daysDiff = (parsedDate - date.today()).days
    if daysDiff == 0:
        return gettext('date.tonight')
    elif daysDiff == -1:
        return gettext('date.yesterday_night')
    elif daysDiff == 1:
        return gettext('date.tomorrow_night')
    elif daysDiff > 0 and daysDiff < 7:
        format = gettext('date.format.next_day')
    elif daysDiff < 0 and daysDiff > -7:
        format = gettext('date.format.previous_day')

    formattedDate = format_date(parsedDate, format)

    return formattedDate


def yearRange(started, ended):
    if ended == 0:
        return started

    return '%d - %d' % (started, ended)


def localizedShowStatus(status):
    if status == 'Returning Series':
        return gettext('showdetails.status.returning')
    elif status == 'Canceled/Ended' or status == 'Ended':
        return gettext('showdetails.status.ended')
    elif status == 'New Series':
        return gettext('showdetails.status.firstseason')
    elif status == 'Final Season':
        return gettext('showdetails.status.finalseason')
    else:
        return status


def setupCustomFilters(app):
    app.jinja_env.filters['episodeNumber'] = episodeNumber
    app.jinja_env.filters['prettyDate'] = prettyDate
    app.jinja_env.filters['downloadLink'] = downloadLink
    app.jinja_env.filters['addic7edLink'] = addic7edLink
    app.jinja_env.filters['yearRange'] = yearRange
    app.jinja_env.filters['localizedShowStatus'] = localizedShowStatus
