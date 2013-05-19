from flask.ext.login import UserMixin


class User(UserMixin):
    def __init__(self, userId):
        super(User, self).__init__()
        self.id = userId
