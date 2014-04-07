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

from craigslist import List, Post, ListSubscriber

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
from google.appengine.api import users

import os

class BaseHandler(webapp.RequestHandler):
    def template_path(self, filename):
        """Returns the full path for a template from its path relative to here."""
        return os.path.join(os.path.dirname(__file__), os.path.pardir,
            filename)

    def render_to_response(self, filename, template_args):
        """Renders a Django template and sends it to the client.

        Args:
          filename: template path (relative to this file)
          template_args: argument dict for the template
        """
        template_args.setdefault('current_uri', self.request.uri)
        self.response.out.write(
            template.render(self.template_path(filename), template_args)
        )

class MapHandler(BaseHandler):
    def get(self):
        if users.get_current_user():
            user = users.get_current_user()
            subscribed_lists = [subscription.sublist
                for subscription in ListSubscriber.all().filter(
                    'subscriber =', user)]

            return self.render_to_response('templates/mapview.html', {
                'user': user,
                'user_logout_url': users.create_logout_url('/'),
                'lists': subscribed_lists
            })
        else:
            all_lists = List.all()
            return self.render_to_response('templates/mapview.html', {
                'user': None,
                'user_login_url': users.create_login_url('/'),
                'lists': all_lists
            })

class MainHandler(webapp.RequestHandler):
    def geocode(self, address):
        from google.appengine.api import urlfetch
        from urllib import urlencode
        from django.utils import simplejson as json

        geocoding_api = 'http://maps.googleapis.com/maps/api/geocode/\
json?%s' % urlencode([
            ('address', address),
            ('sensor', 'false')
        ])

        result = urlfetch.fetch(geocoding_api)
        if result.status_code == 200:
            response = json.loads(result.content)
            if response['status'] == 'OK':
                location = response['results'][0]['geometry']['location']
                low_res_flag = 'political'\
                        in response['results'][0]['types']

                return low_res_flag, [location['lat'], location['lng']]
            else:
                return response['status'], None

    def get(self):
        from datetime import datetime, timedelta
        from time import mktime
        if self.request.get('init'):
            query = List.all().filter('city =', 'minneapolis').filter(
                'category =', 'roo')

            if not query:
                new_list = List(city='minneapolis',
                                category='roo',
                                last_updated=mktime(
                                    datetime.fromtimestamp(0).timetuple())
                            )

                new_list.put()
                self.response.out.write("Inited!!")
            else:
                foo_list = query.fetch(1)[0]
                self.response.out.write("<br />".join([
                    foo_list.city,
                    foo_list.category,
                    foo_list.last_updated.ctime()
                ]))

        elif self.request.get('filter'):
            from google.appengine.api.taskqueue import Task
            ts = datetime.now() - timedelta(days=1)
            for lst in List.all():
                task = Task(url='/tasks/filter/',
                            params={'id': lst.key().id(),
                                    'since': mktime(ts.timetuple())
                            })
                task.add('postqueue')

        else:
            post_list = List.all().filter('city =', 'minneapolis').filter(
                'category =', 'roo').fetch(1)

            if post_list:
                posts = Post.all()
                for post in posts:
                    self.response.out.write("<br />".join([
                        post.title,
                        post.link,
                        ','.join(map(str, [post.latitude, post.longitude])),
                        str(post.approx_geolocation),
                    ]))
                    self.response.out.write("<hr />")
            else:
                if users.is_current_user_admin():
                    self.redirect('/tasks/sync/')
                else:
                    self.response.out.write(
                        "<h1><a href='%s'>Login</a></h1>" % 
                        users.create_login_url('/'))


def main():
    application = webapp.WSGIApplication([
        ('/', MapHandler),
        ('/test/', MainHandler),
    ], debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
