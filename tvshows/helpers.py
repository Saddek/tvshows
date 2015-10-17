# -*- coding: utf-8 -*-
import time

from flask import current_app, request
from flask.ext.login import current_user
from functools import wraps

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


def logged_request(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        current_app.logger.info('%s request on %s' % (request.method, request.path), extra={
            'method': request.method,
            'path': request.path,
            'ip': request.remote_addr,
            'agent_platform': request.user_agent.platform,
            'agent_browser': request.user_agent.browser,
            'agent_browser_version': request.user_agent.version,
            'agent': request.user_agent.string,
            'user': current_user.id if not current_user.is_anonymous() else '<anonymous>'
        })

        return func(*args, **kwargs)
    return decorated_view
