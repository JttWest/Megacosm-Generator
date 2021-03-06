#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    Generators package
"""

from jinja2.environment import Environment
from megacosm.util import Filters
from megacosm.util import Seeds
import json
import logging
import random


class Generator(object):

    """ An abstracted Generator that all generators are based from """

    def __init__(self, redis, features={}, namekey=None):
        self.logger = logging.getLogger(__name__)

        # Redis is the source of all data.

        self.redis = redis
        self.pipeline = self.redis.pipeline

        # We use our class name as a key for redis

        if namekey is None:
            namekey = self.__class__.__name__.lower()

        # see if we have a seed to use, otherwise generate a new one.

        if 'seed' in features:
            self.seed = Seeds.set_seed(features['seed'])
        else:
            self.seed = Seeds.set_seed()
        self.logger.debug('new generator %s with seed %i', namekey, self.seed)

        # For naming conventions, we use "name"+classname+"stuff"

        self.name = self.generate_name('name_' + namekey)

        # For each feature, set it as an attribute for this generator

        for (feature, value) in features.iteritems():

            # This bit of meta code saves soooo much hassle and getters/setters.
            # especially with testing.

            setattr(self, feature, value)

        # This is the guts of the Generator...

        self.generate_features(namekey)

    def generate_features(self, namekey):
        """ Given a namekey, add those features to this object."""

        # find all keys matching our namekey

        self.logger.debug('Generating features for %s with seed %i', namekey, self.seed)
        for key in self.redis.keys(namekey + '_*'):
            self.generate_feature(namekey, key)

    def generate_feature(self, namekey, key):

        # check to see if your key has a related chance key

        if self.redis.exists(key + '_chance'):

            # make sure the value is not already set, then grab it.

            if not hasattr(self, key + '_chance'):
                setattr(self, key + '_chance', int(self.redis.get(key + '_chance')))

            # check to see if you have a preset roll; if not, roll 1-100

            if not hasattr(self, key + '_roll'):
                setattr(self, key + '_roll', random.randint(1, 100))

            # if the roll is greater than the chance, you have failed, and don't get to use this stat.
            # Go to the next entry in the for loop.

            if int(getattr(self, key + '_roll')) > getattr(self, key + '_chance'):
                return

        # #########################################################################################
        # Provided you had no associated _chance or that you succeeded on the chance roll, you can
        # Move on to actually setting the value.

        # Most features don't need the namekey on the front since it's redundant
        # so we shorten the name for brevity.

        featurename = key.replace(namekey + '_', '')

        # Zset means it's a 1-100 stat;

        if self.redis.type(key) == 'zset':
            setattr(self, featurename, Generator.select_by_roll(self, key))
        elif self.redis.type(key) == 'string':

            # string means it's a simple value that plugs right in
            setattr(self, featurename, self.redis.get(key))
        elif self.redis.type(key) == 'list':

            # List gets a bit tricky; select a value, then see if it has an associated description
            # If feature isn't set, grab a rand value from the list.

            if not hasattr(self, featurename):
                featurevalue = Generator.rand_value(self, key)
                setattr(self, featurename, featurevalue)

            # if the description hasn't been set and exists in redis.

            if not hasattr(self, featurename + '_description'):
                try:
                    desc_text = self.redis.hmget(key + '_description', getattr(self, featurename))[0]
                    if desc_text is not None:
                        featurevalue = json.loads(desc_text)
                        setattr(self, featurename + '_description', featurevalue)
                except ValueError:
                    self.logger.critical("JSON parsing error: Couldn't read json %s", desc_text)
                    raise ValueError("JSON parsing error: Couldn't read json", desc_text)

####################################################
# needs refactoring below here.

    # FIXME this needs to be integrated with what NPC races use...

    def generate_name(self, key):
        """ Given a key, query redis and check if all 5 parts of a name exist, then generate a name structure.
            This creates the structure "Title PreRootPost Trailer"
            Note that in the full name, the title has a trailing space and the trailer has a preceeding space.
            Pre, Root and Post have no spaces."""
        name = {'full': ''}

        if self.redis.exists(key + 'title'):
            roll = random.randint(1, 100)
            if not self.redis.exists(key + 'title_chance') or roll < int(self.redis.get(key + 'title_chance')):
                name['title'] = self.rand_value(key + 'title')
                name['full'] = name['title'] + ' '

        for part in ['pre', 'root', 'post']:
            if self.redis.exists(key + part):
                if (not self.redis.exists(key + part + '_chance') or
                        random.randint(1, 100) < int(self.redis.get(key + part + '_chance'))):
                    name[part] = self.rand_value(key + part)
                    name['full'] += name[part]

        if self.redis.exists(key + 'trailer'):
            roll = random.randint(1, 100)
            if not self.redis.exists(key + 'trailer_chance') or roll < int(self.redis.get(key + 'trailer_chance')):
                name['trailer'] = self.rand_value(key + 'trailer')
                name['full'] += ' ' + name['trailer']
        return name

    def rand_value(self, key):
        """ Select a Random Value from the list matching the key in redis. """

        try:
            total = self.redis.llen(key)
            value = self.redis.lindex(key, random.randint(0, total - 1))
            return value
        except Exception:
            raise Exception("the key (%s) doesn't appear to exist or isn't a list (%s)." % (key, self.redis.type(key)))

    def select_by_roll(self, key):
        """ Using roll, select the closest matching score from key in Redis. """

        if key + '_roll' not in self.__dict__:
            setattr(self, key + '_roll', random.randint(1, 100))

        roll = max(1, min(getattr(self, key + '_roll'), 100))

        try:
            rollvalue = self.redis.zrangebyscore(key, roll, 100, 0, 1)
            if rollvalue is None:
                raise LookupError
            return json.loads(rollvalue[0])
        except IndexError:
            raise IndexError('Is %s a valid key?' % key)
        except LookupError:
            raise Exception('the key (%s) appears to be empty for a roll of %s- This should never happen.' % (key,
                            roll))
        except ValueError:
            raise Exception("JSON parsing error: Couldn't read json", rollvalue[0])
        except Exception:
            raise Exception("the key (%s) doesn't appear to exist or isn't a zset (%s)." % (key, self.redis.type(key)))

    def render_template(self, template):
        """ Renders a given template using itself."""

        environment = Environment()
        environment.filters['article'] = Filters.select_article
        environment.filters['pluralize'] = Filters.select_pluralize
        environment.filters['conjunction'] = Filters.select_conjunction
        environment.filters['plural_verb'] = Filters.select_plural_verb
        environment.filters['plural_adj'] = Filters.select_plural_adj

        template = environment.from_string(template)

        return template.render(params=self)
