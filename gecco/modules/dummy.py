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

from pynlpl.formats import folia
from gecco.gecco import Module

class DummyModule(Module):
    UNIT = folia.Word

    def verifysettings(self):
        super().verifysettings()


    def load(self):
        """Load the requested modules from self.models"""

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        return str(word)

    def processoutput(self, response, wordstr, unit_id, **parameters):
        return None

    def run(self, word):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        return word   #server will echo back the same thing if it's not in the error list
