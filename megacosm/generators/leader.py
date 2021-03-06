#!/usr/bin/env python
# -*- coding: utf-8 -*-
from country import Country
from npc import NPC
import logging


class Leader(NPC):

    """ Generate a god for your world"""

    def __init__(self, redis, features={}):
        NPC.__init__(self, redis, features, 'npc')
        self.logger = logging.getLogger(__name__)

        self.generate_features('leader')
        self.generate_features('leader' + self.kind)

        if self.kind_description['scope'] == 'country':
            self.location = Country(self.redis, {'leader': self})
        else:
            # elif self.kind_description['scope'] == 'city':
            #   self.location=City(self.redis, {'leader':self})
            #   TODO This should default to organization...

            self.location = Country(self.redis, {'leader': self})

        self.set_title()

    def set_title(self):
        self.name['title'] = self.leader_description[self.sex['name']]
        self.name['fulltitled'] = self.name['title'] + ' ' + self.name['full']
