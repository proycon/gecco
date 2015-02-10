#========================================================================
#GECCO - Generic Enviroment for Context-Aware Correction of Orthography
# Maarten van Gompel, Wessel Stoop, Antal van den Bosch
# Centre for Language and Speech Technology
# Radboud University Nijmegen
#
# Sponsored by Revisely (http://revise.ly)
#
# Licensed under the GNU Public License v3
#
#=======================================================================

from collections import OrderedDict

def getcache(settings, cachesize=1000):
    if 'cachesize' not in settings:
        settings['cachesize'] = cachesize
    if 'cachetype' not in settings:
        settings['cachetype'] = 'fifo'

    if settings['cachetype'] == 'fifo':
        return FIFOCache(cachesize)
    else:
        raise Exception("invalid cache type: " + settings['cachetype'])

class FIFOCache(OrderedDict):
    def __init__(self, size):
        self.size = size
        super().__init__()

    def append(self, key, value):
        if self.size > 0:
            if len(self) == self.size:
                self.popitem(False)
            self[key] = value


