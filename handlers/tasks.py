#!/usr/bin/env python

from craigslist import List, Post, ListSubscriber, AlertFilter

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.api import urlfetch
from google.appengine.api import mail
from google.appengine.ext import db
from google.appengine.api.taskqueue import Task
from django.utils import simplejson as json
from geo.geotypes import Point

import re
import time
import pickle
from math import floor
from datetime import datetime, timedelta
from urllib import unquote_plus, urlencode
from xml.dom.minidom import parseString as xml_parse

RE_LOC = re.compile(r'http://maps.google.com/\?q=loc\%3A(.+)"')
RE_ALT_LOC = re.compile(r'-->Location: (.+)\s*<li>')
RE_DATE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})([-+]\d{2}:\d{2})$')

def strip_tags(html):
    """Remove all HTML tags"""
    html = re.sub(r'\n', '', html)
    html = re.sub(r'<br[^>]*>', '\n', html)
    html = re.sub(r'</?\w[^>]*?>', '', html)
    html = re.sub('\n', '<br />', html)
    return re.sub(r'&#\d+;', ' ', html).strip()

class SyncHandler(webapp.RequestHandler):
    """Synchronize RSS feeds from Craigslist. All new advertisements will be
    inserted into a taskqueue, waiting for processing, if valid."""
    def get(self):
        lists = List.all()
        for sync_list in lists:
            rss_url = sync_list.rss_url

            result = urlfetch.fetch(rss_url)
            if result.status_code == 200:
                list_dom = xml_parse(result.content)
                posts = list_dom.getElementsByTagName("item")
                
                self.process_posts(sync_list, posts)

    def process_posts(self, assoc_list, posts):
        text = lambda post, tag: \
                post.getElementsByTagName(tag)[0].firstChild.nodeValue

        ref_time = assoc_list.last_updated
        latest_time = datetime.utcfromtimestamp(0)

        price_list = []

        for raw_post in posts:
            created = self.parse_raw_date(text(raw_post, 'dc:date'))

            title = text(raw_post, 'title')
            prices = map(int, re.findall(r'\$(\d+)', title))
            if not prices:
                self.response.out.write(title + ' Price not found<br />')
                continue

            price = max(prices)
            price_list.append(price)

            if not created or created <= ref_time:
                self.response.out.write('Timing issue<br />')
                continue
            if created > latest_time:
                latest_time = created

            description = text(raw_post, 'description')
            addr_match = RE_LOC.search(description)
            alt_addr_match = RE_ALT_LOC.search(description)

            if not addr_match and not alt_addr_match:
                self.response.out.write(title + ' No valid address<br />')
                continue

            # Always try to follow the more accurate position first.
            address = addr_match.group(1) if addr_match else \
                alt_addr_match.group(1)
            alt_addr_flag = addr_match is None

            link = text(raw_post, 'link')

            self.response.out.write('Task: ' + link + ' added to queue.<br />')

            task = Task(url='/tasks/post/',
                        params={'title': title,
                         'price': price,
                         'description': strip_tags(description),
                         'link': link,
                         'created': time.mktime(created.timetuple()),
                         'address': unquote_plus(address),
                         'alt_addr': int(alt_addr_flag),
                         'list': assoc_list.key().id()
                        })

            task.add('postqueue')

        if latest_time > ref_time:
            # Aggregate results
            task = Task(url='/tasks/aggregate/',
                        params={
                            'id': assoc_list.key().id(),
                            'prices': ','.join(map(str, price_list))
                        })

            # Add to the same queue, so we can guarantee that the aggregation
            # is executed after processing all posts.
            task.add('postqueue') 

            # Filter the newly synced results
            task = Task(url='/tasks/filter/',
                        params={'id': assoc_list.key().id(),
                                'since': time.mktime(
                                    assoc_list.last_updated.timetuple())
                        })
            task.add('postqueue')

            assoc_list.last_updated = latest_time
            assoc_list.put()

    def parse_raw_date(self, raw_date):
        match = RE_DATE.match(raw_date)
        if match:
            post_date, post_time, tz_info = match.groups()
            utc_minutes_offset = -reduce(lambda x, y: x*60+y, 
                                        map(int, tz_info.split(':')))
            return datetime.strptime(
                ' '.join([post_date, post_time]),
                '%Y-%m-%d %H:%M:%S') + timedelta(minutes=utc_minutes_offset)

class MailTaskHandler(webapp.RequestHandler):
    def post(self):
        body = self.request.get('body')
        subject = self.request.get('subject')
        recipient = self.request.get('to')

        if body and subject and mail.is_email_valid(recipient):
            mail.send_mail(
                'Craigsreptile Alert <alert@craigsreptile.appspotmail.com>',
                recipient,
                subject,
                body
            )

        pass

class CleanupTaskHandler(webapp.RequestHandler):
    def get(self):
        timestamp_outdated = datetime.now() - timedelta(days=7)
        outdated_posts = Post.all().filter('created <', timestamp_outdated)

        db.delete(outdated_posts)

class FilterTaskHandler(webapp.RequestHandler):
    def post(self):
        try:
            list_id = int(self.request.get('id', 0))
            filter_since = datetime.fromtimestamp(float(
                self.request.get('since', 0.0)))
        except:
            self.error(500)

        if list_id:
            assoc_list = db.Key.from_path('List', list_id)
            filters = AlertFilter.all().filter('sublist =', assoc_list)
            for user_filter in filters:
                watched_cond = pickle.loads(user_filter.geo_region)

                posts_query = Post.all().filter(
                    'posted_list =', assoc_list).filter(
                        'created >', filter_since)

                match_posts = filter(
                    lambda post: user_filter.max_price == 0 or \
                        post.price <= user_filter.max_price,
                    Post.proximity_fetch(
                        posts_query,
                        Point(*watched_cond['center']),
                        max_distance=watched_cond['radius']
                    )
                )

                # Dispatch tasks to send emails to users
                if match_posts:
                    message_body = """Hey %(nickname)s,

    We are happy to notify you that %(count)d housing ads were posted moments
ago that we thought you might be interested in, based on your criteria:

        <%(distance)d> meters around <%(location)s> and less than <$%(price)d>

    You can either follow the link(s) below, or visit your Craigsreptile
website for map visualization.

%(updates)s

    NOTE: Please do not reply this email. Thanks.""" % {
    'nickname': user_filter.owner.nickname(),
    'count': len(match_posts),
    'distance': watched_cond['radius'],
    'location': user_filter.street_name,
    'price': user_filter.max_price,
    'updates' : '\n\n'.join(['    %s\n%s' % (post.link, post.title)
                             for post in match_posts])
}

                    message_subject = 'Craigsreptile Alert: %d new ads you \
might be interested in' % len(match_posts)

                    email_task = Task(
                        url='/tasks/mail/',
                        params={
                            'to':user_filter.owner.email(),
                            'subject': message_subject,
                            'body': message_body
                    })

                    email_task.add('emailqueue')

class AggregationTaskHandler(webapp.RequestHandler):
    """This worker will be called by a scheduled cron job, to aggregate over
    cached posts in the datastore. 
    Currently, we will aggregate the lower/upper quantile and median of prices
    posted on the list, as a reference for users seeking for
    apartments/houses/rooms."""
    def post(self):
        aggre_list_id = int(self.request.get('id', 0))
        prices = map(int, self.request.get('prices').split(','))

        if aggre_list_id:
            post_list = List.get_by_id(aggre_list_id)
            prices.sort()
            # Quantile values
            uq_idx = int(floor(len(prices)*0.75))
            uq = prices[uq_idx]
            lq = prices[int(floor(len(prices)*0.25))]
            median = prices[int(floor(len(prices)*0.5))]

            post_list.aggregated_prices = [lq, median, uq]
            post_list.put()

class PostTaskHandler(webapp.RequestHandler):
    """The worker for processing posted advertisement on subscribed lists. 
    The worker will try to get the coordinates corresponding to the
    advertisement posted for map overlaying visulization."""
    
    def geocode(self, address):
        geocoding_api = 'http://beta.tremblefrog.org/geocoding.php?%s' % \
            urlencode([ ('address', address), ('sensor', 'false') ])

        result = urlfetch.fetch(geocoding_api)
        if result.status_code == 200:
            response = json.loads(result.content)
            if response['status'] == 'OK':
                location = response['results'][0]['geometry']['location']
                low_res_flag = 'political'\
                        in response['results'][0]['types']

                return low_res_flag, db.GeoPt(
                    location['lat'], location['lng'])
            else:
                return response['status'], None

    def post(self):
        title = self.request.get('title')
        created = datetime.utcfromtimestamp(float(self.request.get('created')))
        description = self.request.get('description')
        link = self.request.get('link')
        price = int(self.request.get('price'))
        address = self.request.get('address')
        alt_addr_flag = self.request.get('alt_addr')
        posted_list = db.Key.from_path('List', 
                                    int(self.request.get('list')))

        # To retrieve the geolocation and geocode the address into coordinates
        # for geospatial indexing.

        # If an alternative address is indicated, try append (maybe redundant)
        # the city name to the address for correct geocoding.
        if not alt_addr_flag:
            address = self.request.get('address')
        else: 
            assoc_list = List.get_by_id(posted_list.id())
            city, state = re.compile(assoc_list.city, re.IGNORECASE),\
                    re.compile(assoc_list.state, re.IGNORECASE)
            if not city.search(self.request.get('address')) and not\
                   state.search(self.request.get('address')):
                address = ' '.join([self.request.get('address'),
                                    assoc_list.city,
                                    assoc_list.state
                                   ])
            else:
                address = self.request.get('address')

        status, post_geolocation = self.geocode(address)
        if post_geolocation:
            post = Post(title=title,
                        description=description,
                        link=link,
                        created=created,
                        price=price,
                        posted_list=posted_list,
                        location=post_geolocation,
                        approx_geolocation=status
                       )
            post.update_location()
            post.put()
        else:
            # If the error happens to be over query limit, generate an internal
            # error, signaling the taskqueue to re-process the task after an
            # interval.
            if status == 'OVER_QUERY_LIMIT':
                self.error(500)
            # Otherwise, if it's zero results or request denied error, do
            # nothing

def main():
    application = webapp.WSGIApplication([
        ('/tasks/sync/', SyncHandler),
        ('/tasks/post/', PostTaskHandler),
        ('/tasks/aggregate/', AggregationTaskHandler),
        ('/tasks/mail/', MailTaskHandler),
        ('/tasks/filter/', FilterTaskHandler),
        ('/tasks/cleanup/', CleanupTaskHandler),
    ], debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()
