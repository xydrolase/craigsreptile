#!/usr/bin/env python

from google.appengine.ext import db
from geo.geomodel import GeoModel

class List(db.Model):
    city = db.StringProperty(required=True)
    state = db.StringProperty()
    category = db.StringProperty(required=True)
    aggregated_prices = db.ListProperty(item_type=int, default=[0, 0, 0])
    last_updated = db.DateTimeProperty()

    def _get_rss_url(self):
        return 'http://%(city)s.craigslist.org/%(category)s/index.rss' % {
            'city': self.city,
            'category': self.category
        }

    rss_url = property(_get_rss_url)

    def pack(self):
        return {'city': self.city,
                'state': self.state,
                'category': self.category,
                'aggregated_prices': self.aggregated_prices,
               }

class Post(GeoModel):
    link = db.StringProperty(required=True)
    title = db.StringProperty(required=True)
    description = db.TextProperty(required=True)
    price = db.IntegerProperty(required=True, default=0)
    created = db.DateTimeProperty()
    approx_geolocation = db.BooleanProperty(required=True, default=False)
    posted_list = db.ReferenceProperty(collection_name="posts")

    def _get_latitude(self):
        return self.location.lat if self.location else None

    def _set_latitude(self, lat):
        if not self.location:
            self.location = db.GeoPt()

        self.location.lat = lat

    latitude = property(_get_latitude, _set_latitude)

    def _get_longitude(self):
        return self.location.lon if self.location else None

    def _set_longitude(self, lon):
        if not self.location:
            self.location = db.GeoPt()

        self.location.lon = lon

    longitude = property(_get_longitude, _set_longitude)

    def pack(self):
        return {'title': self.title,
                'description': self.description,
                'price': self.price,
                'created': self.created.ctime(),
                'posted_list': self.posted_list.key().id(),
                'location': [self.location.lat, self.location.lon]
               }

class ListSubscriber(db.Model):
    sublist = db.ReferenceProperty(List, required=True)
    subscriber = db.UserProperty(required=True)

class AlertFilter(db.Model):
    sublist = db.ReferenceProperty(List, required=True)
    owner = db.UserProperty(required=True)
    max_price = db.IntegerProperty(required=True, default=0)
    street_name = db.StringProperty(required=True)
    geo_region = db.ByteStringProperty(required=True)

class Favorite(db.Model):
    post = db.ReferenceProperty(Post, required=True)
    owner = db.UserProperty(required=True)
    created = db.DateTimeProperty(auto_now_add=True)
