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
from pynlpl.formats import folia
from gecco.gecco import Module
from gecco.helpers.filters import hasalpha

class WordErrorListModule(Module):
    """Lexicon Module. Checks an input word against a lexicon and returns suggestions with a certain Levensthein distance. The lexicon may be automatically compiled from a corpus.

    Settings:

    * ``delimiter``    - The delimiter between the frequency and the word in the model file, may be 'space', 'tab' (default), 'comma', 'tilde'
    * ``reversedformat``     - Set to true if the model has correct->wrong pairs rather than wrong->correct pairs (default: False)

    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: nonworderror) 

    Models:
    * An error list   (manually compiled, not trainable from source)
    """
    UNIT = folia.Word
    UNITFILTER = hasalpha

    def verifysettings(self):
        super().verifysettings()

        if 'delimiter' not in self.settings or not self.settings['delimiter']:
            self.settings['delimiter'] = "\t"

        if self.settings['delimiter'].lower() == 'space':
            self.settings['delimiter'] = " "
        elif self.settings['delimiter'].lower() == 'tab':
            self.settings['delimiter'] = "\t"
        elif self.settings['delimiter'].lower() == 'tilde':
            self.settings['delimiter'] = "~"
        elif self.settings['delimiter'].lower() == 'comma':
            self.settings['delimiter'] = ","

        if 'class' not in self.settings:
            self.settings['class'] = 'nonworderror'

        if 'reversedformat' not in self.settings: #reverse format has (correct,wrong) pairs rather than (wrong,correct) pairs
            self.settings['reversedformat'] = False

    def load(self):
        """Load the requested modules from self.models"""
        self.errorlist = {}

        if not self.models:
            raise Exception("Specify one or more models to load!")

        for modelfile in self.models:
            if not os.path.exists(modelfile):
                raise IOError("Missing expected model file:" + modelfile)
            self.log("Loading model file " + modelfile)
            with open(modelfile,'r',encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        fields = [ x.strip() for x in line.split(self.settings['delimiter']) ]
                        if  len(fields) != 2:
                            raise Exception("Syntax error in " + modelfile + ", expected two items, got " + str(len(fields)))

                        if self.settings['reversedformat']:
                            correct, wrong = fields
                        else:
                            wrong, correct = fields

                        if wrong in self.errorlist:
                            current = self.errorlist[wrong]
                            if isinstance(current, tuple):
                                self.errorlist[wrong] = current + (correct,)
                            else:
                                self.errorlist[wrong] = (current, correct)
                        else:
                            self.errorlist[wrong] = correct

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        return str(word)

    def processoutput(self, response, wordstr, unit_id, **parameters):
        if response != wordstr: #server will echo back the same thing if it's not in the error list
            suggestions = response.split("\t")
            return self.addsuggestions(unit_id, suggestions)

    def run(self, word):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        if word in self.errorlist:
            suggestions = self.errorlist[word]
            if isinstance(suggestions, str):
                return suggestions
            else:
                return "\t".join(suggestions)
        else:
            return word   #server will echo back the same thing if it's not in the error list
