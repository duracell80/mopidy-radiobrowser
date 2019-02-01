from __future__ import unicode_literals

import ConfigParser as configparser

import logging
import re
import time
import urlparse

from collections import OrderedDict
from contextlib import closing

import requests

try:
    import cStringIO as StringIO
except ImportError:
    import StringIO as StringIO
try:
    import xml.etree.cElementTree as elementtree
except ImportError:
    import xml.etree.ElementTree as elementtree


logger = logging.getLogger(__name__)


class PlaylistError(Exception):
    pass


class cache(object):
    # TODO: merge this to util library (copied from mopidy-spotify)

    def __init__(self, ctl=0, ttl=3600):
        logger.debug('RadioBrowser: Start radiobrowser.cache.__init__')

        self.cache = {}
        self.ctl = ctl
        self.ttl = ttl
        self._call_count = 0

    def __call__(self, func):
        logger.debug('RadioBrowser: Start radiobrowser.cache.__call__')

        def _memoized(*args):
            logger.debug('RadioBrowser: Start radiobrowser.cache.__call__._memoized')

            now = time.time()
            try:
                value, last_update = self.cache[args]
                age = now - last_update
                if (self._call_count > self.ctl or age > self.ttl):
                    self._call_count = 0
                    raise AttributeError
                if self.ctl:
                    self._call_count += 1
                return value

            except (KeyError, AttributeError):
                value = func(*args)
                if value:
                    self.cache[args] = (value, now)
                return value

            except TypeError:
                return func(*args)

        def clear():
            logger.debug('RadioBrowser: Start radiobrowser.cache.__call__.clear')

            self.cache.clear()

        _memoized.clear = clear
        return _memoized


def parse_m3u(data):
    logger.debug('RadioBrowser: Start radiobrowser.parse_m3u')

    # Copied from mopidy.audio.playlists
    # Mopidy version expects a header but it's not always present
    for line in data.readlines():
        if not line.startswith('#') and line.strip():
            yield line.strip()


def parse_pls(data):
    logger.debug('RadioBrowser: Start radiobrowser.parse_pls')

    # Copied from mopidy.audio.playlists
    try:
        cp = configparser.RawConfigParser()
        cp.readfp(data)
    except configparser.Error:
        return

    for section in cp.sections():
        if section.lower() != 'playlist':
            continue
        for i in xrange(cp.getint(section, 'numberofentries')):
            try:
                # TODO: Remove this horrible hack to avoid adverts
                if cp.has_option(section, 'length%d' % (i+1)):
                    if cp.get(section, 'length%d' % (i+1)) == '-1':
                        yield cp.get(section, 'file%d' % (i+1))
                else:
                    yield cp.get(section, 'file%d' % (i+1))
            except configparser.NoOptionError:
                return


def fix_asf_uri(uri):
    logger.debug('RadioBrowser: Start radiobrowser.fix_asf_uri')

    return re.sub(r'http://(.+\?mswmext=\.asf)', r'mms://\1', uri, flags=re.I)


def parse_old_asx(data):
    logger.debug('RadioBrowser: Start radiobrowser.parse_old_asx')

    try:
        cp = configparser.RawConfigParser()
        cp.readfp(data)
    except configparser.Error:
        return
    for section in cp.sections():
        if section.lower() != 'reference':
            continue
        for option in cp.options(section):
            if option.lower().startswith('ref'):
                uri = cp.get(section, option).lower()
                yield fix_asf_uri(uri)


def parse_new_asx(data):
    logger.debug('RadioBrowser: Start radiobrowser.parse_new_asx')

    # Copied from mopidy.audio.playlists
    try:
        for event, element in elementtree.iterparse(data):
            element.tag = element.tag.lower()  # normalize
    except elementtree.ParseError:
        return

    for ref in element.findall('entry/ref[@href]'):
        yield fix_asf_uri(ref.get('href', '').strip())

    for entry in element.findall('entry[@href]'):
        yield fix_asf_uri(entry.get('href', '').strip())


def parse_asx(data):
    logger.debug('RadioBrowser: Start radiobrowser.parse_asx')

    if 'asx' in data.getvalue()[0:50].lower():
        return parse_new_asx(data)
    else:
        return parse_old_asx(data)


# This is all broken: mopidy/mopidy#225
# from gi.repository import TotemPlParser
# def totem_plparser(uri):
#     results = []
#     def entry_parsed(parser, uri, metadata):
#         results.append(uri)

#     parser = TotemPlParser.Parser.new()
#     someid = parser.connect('entry-parsed', entry_parsed)
#     res = parser.parse(uri, False)
#     parser.disconnect(someid)
#     if res != TotemPlParser.ParserResult.SUCCESS:
#         logger.debug('Failed to parse playlist')
#     return results


def find_playlist_parser(extension, content_type):
    logger.debug('RadioBrowser: Start radiobrowser.find_playlist_parser')

    extension_map = {'.asx': parse_asx,
                     '.wax': parse_asx,
                     '.m3u': parse_m3u,
                     '.pls': parse_pls}
    content_type_map = {'video/x-ms-asf': parse_asx,
                        'application/x-mpegurl': parse_m3u,
                        'audio/x-scpls': parse_pls}

    parser = extension_map.get(extension, None)
    if not parser and content_type:
        # Annoying case where the url gave us no hints so try and work it out
        # from the header's content-type instead.
        # This might turn out to be server-specific...
        parser = content_type_map.get(content_type.lower(), None)
    return parser


class RadioBrowser(object):
    # Wrapper for the RadioBrowser API.

    def __init__(self, timeout, session=None):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.__init__')

        self._base_uri = 'http://opml.radiotime.com/%s'
        self._session = session or requests.Session()
        self._timeout = timeout / 1000.0
        self._stations = {}

    def reload(self):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.reload')

        self._stations.clear()
        self._radiobrowser.clear()
        self._get_playlist.clear()

    def _flatten(self, data):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._flatten')

        results = []
        for item in data:
            if 'children' in item:
                results.extend(item['children'])
            else:
                results.append(item)
        return results

    def _filter_results(self, data, section_name=None, map_func=None):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._filter_results')

        results = []

        def grab_item(item):
            if 'guide_id' not in item:
                return
            if map_func:
                station = map_func(item)
            elif item.get('type', 'link') == 'link':
                results.append(item)
                return
            else:
                station = item
            self._stations[station['guide_id']] = station
            results.append(station)

        for item in data:
            if section_name is not None:
                section_key = item.get('key', '').lower()
                if section_key.startswith(section_name.lower()):
                    for child in item['children']:
                        grab_item(child)
            else:
                grab_item(item)
        return results

    def categories(self, category=''):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.categories')

        # No possibility to get it from the API ...
        '''
        results = [];  # <type 'list'>
        category = {   # <type 'dict'>
            'URL': self._base_uri % 'countries', # http://www.radio-browser.info/webservice/json/countries
            'element': 'outline',
            'key: 'countries',
            'text': 'Countries',
            'type': 'link'
        };
        results.append(category);

        category = {
            'URL': self._base_uri % 'languages', # http://www.radio-browser.info/webservice/json/languages
            'element': 'outline',
            'text': 'Languages',
            'key': 'languages',
            'type': 'link'
        };
        results.append(category);

        category = {
            'URL': self._base_uri % 'tags', # http://www.radio-browser.info/webservice/json/tags
            'element': 'outline',
            'text': 'Tags',
            'key': 'tags',
            'type': 'link'
        };
        results.append(category);

        category = {
            'URL': self._base_uri % 'stations/topclick', # http://www.radio-browser.info/webservice/json/stations/topclick
            'element': 'outline',
            'text': 'Top 50 clicked',
            'key': 'clicks',
            'type': 'link'
        };
        results.append(category);

        category = {
            'URL': self._base_uri % 'stations/topvote', # http://www.radio-browser.info/webservice/json/stations/topvote
            'element': 'outline',
            'text': 'Top 50 voted',
            'key': 'votes',
            'type': 'link'
        };
        results.append(category);
        '''
        if category == 'location':
            args = '&id=r0'  # Annoying special case
        elif category == 'language':
            args = '&c=lang'
            return []  # TuneIn's API is a mess here, cba
        else:
            args = '&c=' + category

        # Take a copy so we don't modify the cached data
        results = list(self._radiobrowser('Browse.ashx', args))
        if category in ('podcast', 'local'):
            # Flatten the results!
            results = self._filter_results(self._flatten(results))
        elif category == '':
            trending = {'text': 'Trending',
                        'key': 'trending',
                        'type': 'link',
                        'URL': self._base_uri % 'Browse.ashx?c=trending'}
            # Filter out the language root category for now
            results = [x for x in results if x['key'] != 'language']
            results.append(trending)
        else:
            results = self._filter_results(results)
        return results

    def locations(self, location):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.locations')

        args = '&id=' + location
        results = self._radiobrowser('Browse.ashx', args)
        # TODO: Support filters here
        return [x for x in results if x.get('type', '') == 'link']

    def _browse(self, section_name, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._browse')

        args = '&id=' + guide_id
        results = self._radiobrowser('Browse.ashx', args)
        return self._filter_results(results, section_name)

    def featured(self, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.featured')

        return self._browse('Featured', guide_id)

    def local(self, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.local')

        return self._browse('Local', guide_id)

    def stations(self, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.stations')

        return self._browse('Station', guide_id)

    def related(self, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.related')

        return self._browse('Related', guide_id)

    def shows(self, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.shows')

        return self._browse('Show', guide_id)

    def episodes(self, guide_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.episodes')

        args = '&c=pbrowse&id=' + guide_id
        results = self._radiobrowser('Tune.ashx', args)
        return self._filter_results(results, 'Topic')

    def _map_listing(self, listing):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._map_listing')

        # We've already checked 'guide_id' exists
        url_args = 'Tune.ashx?id=%s' % listing['guide_id']
        return {'text': listing.get('name', '???'),
                'guide_id': listing['guide_id'],
                'type': 'audio',
                'image': listing.get('logo', ''),
                'subtext': listing.get('slogan', ''),
                'URL': self._base_uri % url_args}

    def _station_info(self, station_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._station_info')

        logger.debug('RadioBrowser: Fetching info for station %s' % station_id)
        args = '&c=composite&detail=listing&id=' + station_id
        results = self._radiobrowser('Describe.ashx', args)
        listings = self._filter_results(results, 'Listing', self._map_listing)
        if listings:
            return listings[0]

    def parse_stream_url(self, url):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.parse_stream_url')

        logger.debug('RadioBrowser: Extracting URIs from %s', url)
        extension = urlparse.urlparse(url).path[-4:]
        if extension in ['.mp3', '.wma']:
            return [url]  # Catch these easy ones
        results = []
        playlist, content_type = self._get_playlist(url)
        if playlist:
            parser = find_playlist_parser(extension, content_type)
            if parser:
                playlist_data = StringIO.StringIO(playlist)
                try:
                    results = [u for u in parser(playlist_data)
                               if u and u != url]
                except Exception as e:
                    logger.error('RadioBrowser playlist parsing failed %s' % e)
                if not results:
                    logger.debug('RadioBrowser: Parsing failure, '
                                 'malformed playlist: %s' % playlist)
        elif content_type:
            results = [url]
        logger.debug('RadioBrowser: Got %s', results)
        return list(OrderedDict.fromkeys(results))

    def tune(self, station):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.tune')

        logger.debug('RadioBrowser: Tuning station id %s' % station['guide_id'])
        args = '&id=' + station['guide_id']
        stream_uris = []
        for stream in self._radiobrowser('Tune.ashx', args):
            if 'url' in stream:
                stream_uris.append(stream['url'])
        if not stream_uris:
            logger.error('Failed to tune station id %s' % station['guide_id'])
        return list(OrderedDict.fromkeys(stream_uris))

    def station(self, station_id):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.station')

        if station_id in self._stations:
            station = self._stations[station_id]
        else:
            station = self._station_info(station_id)
            self._stations['station_id'] = station
        return station

    def search(self, query):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser.search')

        # "Search.ashx?query=" + query + filterVal
        if not query:
            logger.debug('RadioBrowser: Empty search query')
            return []
        logger.debug('RadioBrowser: Searching RadioBrowser for "%s"' % query)
        args = '&query=' + query
        search_results = self._radiobrowser('Search.ashx', args)
        results = []
        for item in self._flatten(search_results):
            if item.get('type', '') == 'audio':
                # Only return stations
                self._stations[item['guide_id']] = item
                results.append(item)

        return results

    # @cache()   # Can't be debugged
    def _radiobrowser(self, variant, args):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._radiobrowser')

        uri = (self._base_uri % variant) + '?render=json' + args
        logger.debug('RadioBrowser: RadioBrowser request: %s', uri)
        try:
            with closing(self._session.get(uri, timeout=self._timeout)) as r:
                r.raise_for_status()
                return r.json()['body']
        except Exception as e:
            logger.info('RadioBrowser API request for %s failed: %s' % (variant, e))
        return {}

    # @cache()   # Can't be debugged
    def _get_playlist(self, uri):
        logger.debug('RadioBrowser: Start radiobrowser.RadioBrowser._get_playlist')

        data, content_type = None, None
        try:
            # Defer downloading the body until know it's not a stream
            with closing(self._session.get(uri,
                                           timeout=self._timeout,
                                           stream=True)) as r:
                r.raise_for_status()
                content_type = r.headers.get('content-type', 'audio/mpeg')
                logger.debug('RadioBrowser: %s has content-type: %s' % (uri, content_type))
                if content_type != 'audio/mpeg':
                    data = r.content.decode('utf-8', errors='ignore')
        except Exception as e:
            logger.info('RadioBrowser playlist request for %s failed: %s' % (uri, e))
        return (data, content_type)