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



