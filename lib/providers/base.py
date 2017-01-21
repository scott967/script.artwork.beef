import StorageServer
import sys
import xbmc
from abc import ABCMeta, abstractmethod
from requests import codes
from requests.exceptions import HTTPError, Timeout

from devhelper import pykodi, quickjson
from devhelper.pykodi import log

from lib.libs.utils import SortedDisplay

from requests.packages import urllib3
urllib3.disable_warnings()

useragent = 'ArtworkBeef Kodi'

def update_useragent():
    global useragent
    beefversion = pykodi.get_main_addon().version
    props = quickjson.get_application_properties(['name', 'version'])
    appversion = '{0}.{1}'.format(props['version']['major'], props['version']['minor'])
    useragent = 'ArtworkBeef/{0} {1}/{2}'.format(beefversion, props['name'], appversion)

update_useragent()

cache = StorageServer.StorageServer('script.artwork.beef', 72)
monitor = xbmc.Monitor()

# Result dict of lists, keyed on art type
# {'url': URL, 'language': ISO alpha-2 code, 'rating': SortedDisplay, 'size': SortedDisplay, 'provider': self.name, 'preview': preview URL}
# 'title': optional image title
# 'subtype': optional image subtype, like disc dvd/bluray/3d, SortedDisplay
# language should be None if there is no title on the image

class AbstractProvider(object):
    __metaclass__ = ABCMeta

    name = SortedDisplay(0, '')
    mediatype = None

    def __init__(self, session):
        self.session = session
        self.getter = Getter(session, self.login)

    def set_accepted_contenttype(self, contenttype):
        self.getter.set_accepted_contenttype(contenttype)

    def doget(self, url, params=None, headers=None):
        return self.getter.get(url, params, headers)

    def log(self, message, level=xbmc.LOGDEBUG):
        log(message, level, tag='%s.%s' % (self.name.sort, self.mediatype))

    def login(self):
        return False

    @abstractmethod
    def get_images(self, mediaid, types=None):
        pass

class Getter(object):
    retryable_errors = (codes['bad_gateway'], codes['internal_server_error'], 520)
    def __init__(self, session, login=lambda: False):
        self.session = session
        self.login = login
        self.contenttype = None
        self.retryon_servererror = False

    def set_accepted_contenttype(self, contenttype):
        self.session.headers['Accept'] = contenttype
        self.contenttype = contenttype

    def get(self, url, params=None, headers=None):
        result = self._inget(url, params, headers)
        if result is None:
            return
        errcount = 0
        while self.retryon_servererror and result.status_code in self.retryable_errors:
            message = sys.exc_info()[1].message if sys.exc_info()[1] else 'HTTP 520' if \
                result.status_code == 520 else ''
            if errcount > 2:
                raise ProviderError, (message, sys.exc_info()[1]), sys.exc_info()[2]
            log('HTTP 5xx error, retrying in 2s: ' + message + '\n' + url)
            errcount += 1
            if monitor.waitForAbort(2):
                return
            result = self._inget(url, params, headers)
        if result.status_code == codes['unauthorized']:
            if self.login():
                result = self._inget(url, params, headers)
                if result is None:
                    return
        errcount = 0
        while result.status_code == codes['too_many_requests']:
            if errcount > 2:
                raise ProviderError, "Too many requests", sys.exc_info()[2]
            errcount += 1
            try:
                wait = int(result.headers.get('Retry-After')) + 1
            except ValueError:
                wait = 10
            if monitor.waitForAbort(wait):
                return
            result = self._inget(url, params, headers)
            if result is None:
                return

        if result.status_code == codes['not_found']:
            return
        try:
            result.raise_for_status()
        except HTTPError:
            raise ProviderError, (sys.exc_info()[1].message, sys.exc_info()[1]), sys.exc_info()[2]
        if self.contenttype and not result.headers['Content-Type'].startswith(self.contenttype):
            raise ProviderError, "Provider returned unexected content", sys.exc_info()[2]
        return result

    def _inget(self, url, params=None, headers=None, timeout=15):
        finalheaders = {'User-Agent': useragent}
        if headers:
            finalheaders.update(headers)
        try:
            return self.session.get(url, params=params, headers=finalheaders, timeout=timeout)
        except Timeout:
            try:
                return self.session.get(url, params=params, headers=finalheaders, timeout=timeout)
            except Timeout as ex:
                raise ProviderError, ("Provider is not responding", ex), sys.exc_info()[2]

class ProviderError(Exception):
    def __init__(self, message, cause=None):
        super(ProviderError, self).__init__(message)
        self.cause = cause
