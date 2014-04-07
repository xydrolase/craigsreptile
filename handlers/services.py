#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from craigslist import List, Post, ListSubscriber, AlertFilter

from geo import geotypes, geomath
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import util
from google.appengine.api import users
from google.appengine.api import urlfetch
from django.utils import simplejson as json

import re
import pickle
from datetime import datetime, timedelta

class JSONHandler(webapp.RequestHandler):
    def _error(self, message, code=400):
        self.error(code)
        self.response.out.write(json.dumps({
            'status': 'ERROR',
            'message': message,
            'results': {}
            }))

        return None

    def apply_filters(self, query):
        try:
            freshness = int(self.request.get('freshness', 48))
        except ValueError:
            return query

        if freshness > 0:
            query_date = datetime.utcnow() + timedelta(hours=-freshness)
            query = query.filter('created >', query_date)

        return query

class PackHandler(JSONHandler):
    def post(self):
        try:
            kind = self.request.get('kind')
            id = int(self.request.get('id'))
        except ValueError:
            return self._error('BAD REQUEST', 400)

        if not kind or not id:
            return self._error('BAD REQUEST', 400)

        self.response.headers['Content-Type'] = 'application/json'

        key = db.Key.from_path(kind, id)
        entity = db.get(key)
        if not key or not entity:
            return self._error('ENTRY NOT EXISTS', 400)

        return self.response.out.write(json.dumps({
            'status': 'OK',
            kind: entity.pack()
        }))

class SubscribeHandler(JSONHandler):
    def is_valid_rss(self, rss_url):
        result = urlfetch.fetch(rss_url)
        return result.status_code == 200

    def post(self):
        # For cities like Ann Arbor, San Diego etc.
        city = re.sub('\s', '',
                      self.request.get('city').strip().lower())
        state = self.request.get('state').strip().upper()
        category = self.request.get('category').strip()
        user = users.get_current_user()
        
        if not city or not category or not user:
            return self._error('BAD REQUEST', 400)

        match_lists = List.all().filter('city =', city).filter(
            'state =', state).filter('category =', category).fetch(1)

        self.response.headers['Content-Type'] = 'application/json'

        if match_lists:
            craigslist = match_lists[0]
            subscriber = ListSubscriber.all().filter(
                'subscriber =', user).filter('sublist =', craigslist).fetch(1)
            if subscriber:
                return self.response.out.write(json.dumps({
                    'status': 'DUPLICATE_SUBSCRIPTION',
                    'list': None
                }))
            else:
                subscriber = ListSubscriber(sublist=craigslist,
                                            subscriber=user)
                sub_key = subscriber.put()
        else:
            craigslist = List(city=city,
                              state=state,
                              category=category,
                              last_updated=datetime.utcfromtimestamp(0),
                             )
            if self.is_valid_rss(craigslist.rss_url):
                list_key = craigslist.put()
                subscriber = ListSubscriber(sublist=list_key,
                                            subscriber=user)
                sub_key = subscriber.put()
            else:
                return self._error('INVALID CITY', 400)

        return self.response.out.write(json.dumps({
            'status': 'OK',
            'list': {'id': sub_key.id(),
                     'city': city,
                     'state': state,
                     'category': category
                    }
        }))

class PostRetrieveHandler(JSONHandler):
    re_image = re.compile(
        r'<img src="(.+)" alt=".+">')

    def retrieve_images(self, link):
        result = urlfetch.fetch(link)
        if result.status_code == 200:
            sub_content = result.content[
                result.content.find(
                    '<table summary="craigslist hosted images">'):
                result.content.rfind("</table>")]

            return self.re_image.findall(sub_content)
        else:
            return []
    def get(self):
        try:
            post_id = int(self.request.get('id'))
        except ValueError:
            return self._error("INVALID_IDENTIFIER", 400)

        self.response.headers['Content-Type'] = 'application/json'

        post = Post.get_by_id(post_id)
        if post:
            post_hosted_images = self.retrieve_images(post.link)
            return self.response.out.write(json.dumps(
                {'status': 'OK',
                 'post': {
                     'title': post.title,
                     'description': post.description,
                     'link': post.link,
                     'created': post.created.ctime(),
                     'images': post_hosted_images
                     }
                }))
        else:
            return self.response.out.write(json.dumps(
                {'status': 'ZERO_RESULT',
                 'post': {}
                }))

class FilterHandler(JSONHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
            return self._error("UNAUTHORIZED_REQUEST", 400)

        try:
            list_id = int(self.request.get('list'))
        except ValueError:
            return self._error("INVALID_PARAMETERS", 400)


        user_filters = AlertFilter.all().filter('owner =', user).filter(
            'sublist =', db.Key.from_path('List', list_id))

        self.response.headers['Content-Type'] = 'application/json'

        return self.response.out.write(json.dumps(
            {'status': 'OK',
             'filters': [
                 {
                 'id': uf.key().id(),
                 'street': uf.street_name,
                 'center': pickle.loads(uf.geo_region)['center'],
                 'radius': pickle.loads(uf.geo_region)['radius'],
                 'maxPrice': uf.max_price
                 } for uf in user_filters]
            }))

    def post(self):
        try:
            filter_id = int(self.request.get('id', 0))
            latitude = float(self.request.get('lat'))
            longitude = float(self.request.get('lng'))
            list_watched = int(self.request.get('list'))
            max_price = int(self.request.get('maxprice', 0))
            street_name = self.request.get('street')
            radius = int(self.request.get('radius', 2500))
        except ValueError:
            return self._error('INVALID_PARAMETERS', 400)

        user = users.get_current_user()

        if filter_id:
            user_filter = AlertFilter.get_by_id(filter_id)
            if user_filter.owner != user:
                return self._error("UNAUTHORIZED_REQUEST", 400)

            user_filter.geo_region = pickle.dumps({
                'center': [latitude, longitude],
                'radius': radius
            })
            user_filter.max_price = max_price
            user_filter.street_name = street_name
        elif user and list_watched:
            user_filter = AlertFilter(
                sublist=db.Key.from_path('List', list_watched),
                max_price=max_price,
                street_name=street_name,
                owner=user,
                geo_region=pickle.dumps({
                    'center': [latitude, longitude],
                    'radius': radius
                })
            )

        if user_filter:
            filter_key = user_filter.put()

            self.response.headers['Content-Type'] = 'application/json'
            return self.response.out.write(json.dumps({
                'status': 'OK',
                'id': filter_key.id()
            }))

class ProximitySearchHandler(JSONHandler):
    def get(self):
        try:
            latitude = float(self.request.get('lat'))
            longitude = float(self.request.get('lng'))
            list_search_against = int(self.request.get('list'))
            radius = int(self.request.get('radius', 2500)) # 2.5 km by default
            max_results = int(self.request.get('max_results', 100))
            max_price = int(self.request.get('max_price', 0))
        except ValueError:
            return self._error('INVALID_PARAMETERS', 400) # Bad request

        approx_results = self.request.get('approx', False)

        if not latitude or not longitude or not list_search_against:
            return self._error('INVALID_PARAMETERS', 400) # Bad request

        list_key = List.get_by_id(list_search_against).key()
        query = Post.all().filter('posted_list =', list_key).order('-created')
        if not approx_results:
            query = query.filter('approx_geolocation =', False)

        center = geotypes.Point(latitude, longitude)

        proximity_posts = Post.proximity_fetch(
            query,
            center,
            max_results=max_results,
            max_distance=radius
        )

        self.response.headers['Content-Type'] = 'application/json'
        if proximity_posts:
            results = [{'title': post.title,
                        'price': post.price,
                        'location': [post.latitude, post.longitude],
                        'id': post.key().id(),
                        'distance': round(geomath.distance(center,
                            geotypes.Point(post.latitude, post.longitude))),
                        'created': post.created.ctime(),
                       } for post in proximity_posts]

            return self.response.out.write(json.dumps({
                'status': 'OK',
                'count': len(results),
                'center': [latitude, longitude],
                'results': results
            }))
        else:
            return self.response.out.write(json.dumps({
                'status': 'OK',
                'count': 0,
                'center': [latitude, longitude],
                'results': []
            }))

    def post(self):
        return self._error('INVALID_METHOD', 400)


class BoundSearchHandler(JSONHandler):
    def get(self):
        try:
            north = float(self.request.get('north'))
            east = float(self.request.get('east'))
            south = float(self.request.get('south'))
            west = float(self.request.get('west'))
            list_search_against = int(self.request.get('list'))
            max_results = int(self.request.get('max_results', 100))
        except ValueError:
            self._error('INVALID_PARAMETERS', 400) # Bad request

        approx_results = self.request.get('approx', False)

        if not north or not east or not south or not west \
                or not list_search_against:
            self._error('INVALID_PARAMETERS', 400) # Bad request

        list_key = List.get_by_id(list_search_against).key()
        query = self.apply_filters(Post.all().filter(
            'posted_list =', list_key)).order('-created')
        if not approx_results:
            query = query.filter('approx_geolocation =', False)

        bound_posts = Post.bounding_box_fetch(
            query,
            geotypes.Box(north, east, south, west),
            max_results=max_results
        )

        self.response.headers['Content-Type'] = 'application/json'
        if bound_posts:
            results = [{'title': post.title,
                        'price': post.price,
                        'location': [post.latitude, post.longitude],
                        'created': post.created.ctime(),
                        'id': post.key().id()
                       } for post in bound_posts]

            self.response.out.write(json.dumps({
                'status': 'OK',
                'count': len(results),
                'results': results
            }))
        else:
            self.response.out.write(json.dumps({
                'status': 'OK',
                'count': 0,
                'results': []
            }))

    def post(self):
        self._error('INVALID_METHOD', 400)

def main():
    application = webapp.WSGIApplication([
        ('/services/proximity/', ProximitySearchHandler),
        ('/services/bound/', BoundSearchHandler),
        ('/services/post/', PostRetrieveHandler),
        ('/services/subscribe/', SubscribeHandler),
        ('/services/filter/', FilterHandler),
        ('/services/pack/', PackHandler),
    ], debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()
