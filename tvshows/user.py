# -*- coding: utf-8 -*-
from flask.ext.login import UserMixin
from .database import SeriesDatabase

series = SeriesDatabase()


class UserDefaults(object):
    language = 'auto'
    episodesPerShow = 4


class UserConfig(object):
    def __init__(self, user):
        object.__setattr__(self, 'user', user)

    def __getattr__(self, name):
        value = series.getUserConfigValue(self.user.id, name)

        if not value:
            value = getattr(UserDefaults, name)

        return value

    def __setattr__(self, name, value):
        if value != getattr(UserDefaults, name):
            series.setUserConfigValue(self.user.id, name, value)
        else:
            series.setUserConfigValue(self.user.id, name, None)

    def __delattr__(self, name):
        series.setUserConfigValue(self.user.id, name, None)

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __setitem__(self, name, value):
        self.__setattr__(name, value)

    def __delitem__(self, name):
        self.__delattr__(name)


class User(UserMixin):
    defaults = UserDefaults

    def __init__(self, userId):
        super(User, self).__init__()
        self.id = userId
        self.config = UserConfig(self)
