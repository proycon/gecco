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

import sys
import os
import json
import io
import bz2
import gzip
from collections import OrderedDict
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from gecco.gecco import Module
from gecco.modules.lexicon import LexiconModule


def splits(s):
    for i in range(1,len(s) -2):
        yield (s[:i], s[i:])

class RunOnModule:
    UNIT = folia.Word

    def verifysettings(self):
        super().verifysettings()

        #We use a lexiconmodule as a submodule
        self.lexiconmodule = None
        for submod in self.submodules:
            if isinstance(submod, LexiconModule):
                self.lexiconmodule = submod

        if not self.lexiconmodule:
            raise Exception("RunOnModule requires a submodule of type LexiconModule, none found")




    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        submodclient = self.getsubmoduleclient(self.lexiconmodule)

        wordstr = str(word)
        for parts in splits(wordstr):
            for part in parts:
                #communicate with lexicon submodule,'?' is the command to checker whether the word exists, returns the frequency
                exists = int(client.communicate('?' + wordstr), submodclient, lock ) #? is the command to the lexicon server
                if exists:








        best, distribution = self.classify(word)
        if best != word:
            distribution = [ x for x in distribution.items() if x[1] >= self.threshold ]
            if distribution:
                self.addwordsuggestions(lock, word, distribution)
