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
from gecco.helpers.common import stripsourceextensions
import colibricore #pylint: disable=import-error


def splits(s):
    for i in range(1,len(s) -2):
        yield (s[:i], s[i:])

class RunOnModule(Module):
    """Detects words that have been joined together but should be split. It uses a bigram model.
    
    Settings:
    * ``freqthreshold`` - Frequency threshold for unigrams and bigrams to make it into the model (default: 10)  (you need to retrain the model if you change this value)
    * ``partthreshold`` - Each of the parts must occur over this threshold (default: 10), should be >= freqthreshold
    * ``class``         - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: runonerror) 
    """
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'runonerror'

        super().verifysettings()

        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 10

        if 'partthreshold' not in self.settings:
            self.settings['partthreshold'] = 10

    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate bigram model")
        classfile = stripsourceextensions(sourcefile) +  ".cls"
        corpusfile = stripsourceextensions(sourcefile) +  ".dat"

        if not os.path.exists(classfile):
            self.log("Building class file")
            classencoder = colibricore.ClassEncoder() #character length constraints
            classencoder.build(sourcefile)
            classencoder.save(classfile)
        else:
            classencoder = colibricore.ClassEncoder(classfile)

        if not os.path.exists(modelfile+'.cls'):
            #make symlink to class file, using model name instead of source name
            os.symlink(classfile, modelfile + '.cls')

        if not os.path.exists(corpusfile):
            self.log("Encoding corpus")
            classencoder.encodefile( sourcefile, corpusfile)

        self.log("Generating bigram frequency list")
        options = colibricore.PatternModelOptions(mintokens=self.settings['freqthreshold'],minlength=1,maxlength=2) #unigrams and bigrams
        model = colibricore.UnindexedPatternModel()
        model.train(corpusfile, options)

        self.log("Saving model")
        model.write(modelfile)

    def load(self):
        """Load the requested modules from self.models"""
        if len(self.models) != 1:
            raise Exception("Specify one and only one model to load!")

        modelfile = self.models[0]
        if not os.path.exists(modelfile):
            raise IOError("Missing expected model file:" + modelfile)
        self.log("Loading colibri model file " + modelfile)
        self.classencoder = colibricore.ClassEncoder(modelfile + '.cls')
        self.classdecoder = colibricore.ClassDecoder(modelfile + '.cls')
        self.patternmodel = colibricore.UnindexedPatternModel(modelfile)


    def splitsuggestions(self, word):
        pattern_joined = self.classencoder.buildpattern(word)
        if pattern_joined.unknown():
            freq_joined = 0
        else:
            try:
                freq_joined = self.patternmodel[pattern_joined]
            except KeyError:
                freq_joined = 0

        suggestions = []
        maxfreq = 0
        for parts in splits(word):
            pattern = self.classencoder.buildpattern(" ".join(parts))
            if pattern.unknown():
                freq = 0
            else:
                try:
                    freq = self.patternmodel[pattern]
                except KeyError:
                    freq = 0
            if freq < self.settings['partthreshold']:
                continue
            if freq > freq_joined:
                if freq > maxfreq:
                    maxfreq = freq
                suggestions.append( (parts, freq) )

        return [ (parts, freq / maxfreq) for parts, freq in suggestions ] #normalise confidence score (highest option = 1)


    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        return str(word) 

    def processoutput(self, suggestions, inputdata, unit_id,**parameters):
        return self.splitcorrection(unit_id, suggestions)

    def run(self, word):
        return self.splitsuggestions(word)


class SplitModule(Module):
    """Detects words that have been split but should be merged together as one

    Settings:
    * ``freqthreshold`` - Frequency threshold for bigrams to make it into the model (default: 10)  (you need to retrain the model if you change this value)
    * ``freqratio``     - The bigram's frequency must be larger than any of the unigram frequencies by this factor (default: 0.5)
    * ``class``         - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: runonerror) 
    """
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'spliterror'

        super().verifysettings()

        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 10

        if 'freqratio' not in self.settings:
            self.settings['freqratio'] = 0.5 

    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate bigram model")
        classfile = stripsourceextensions(sourcefile) +  ".cls"
        corpusfile = stripsourceextensions(sourcefile) +  ".dat"

        if not os.path.exists(classfile):
            self.log("Building class file")
            classencoder = colibricore.ClassEncoder() #character length constraints
            classencoder.build(sourcefile)
            classencoder.save(classfile)
        else:
            classencoder = colibricore.ClassEncoder(classfile)

        if not os.path.exists(modelfile+'.cls'):
            #make symlink to class file, using model name instead of source name
            os.symlink(classfile, modelfile + '.cls')

        if not os.path.exists(corpusfile):
            self.log("Encoding corpus")
            classencoder.encodefile( sourcefile, corpusfile)

        self.log("Generating bigram frequency list")
        options = colibricore.PatternModelOptions(mintokens=self.settings['freqthreshold'],minlength=1,maxlength=2) #unigrams and bigrams
        model = colibricore.UnindexedPatternModel()
        model.train(corpusfile, options)


        self.log("Saving model")
        model.write(modelfile)

    def load(self):
        """Load the requested modules from self.models"""
        if len(self.models) != 1:
            raise Exception("Specify one and only one model to load!")

        modelfile = self.models[0]
        if not os.path.exists(modelfile):
            raise IOError("Missing expected model file:" + modelfile)
        self.log("Loading colibri model file " + modelfile)
        self.classencoder = colibricore.ClassEncoder(modelfile + '.cls')
        self.classdecoder = colibricore.ClassDecoder(modelfile + '.cls')
        self.patternmodel = colibricore.UnindexedPatternModel(modelfile)


    def getmergesuggestion(self, word, nextword):
        suggestions = []
        if nextword:
            pattern_joined = self.classencoder.buildpattern(word+nextword)
            if pattern_joined.unknown():
                freq_joined = 0
            else:
                try:
                    freq_joined = self.patternmodel[pattern_joined]
                except KeyError:
                    freq_joined = 0

            maxfreq = 0
            pattern = self.classencoder.buildpattern(word + " " + nextword)
            if pattern.unknown():
                freq = 0
            else:
                try:
                    freq = self.patternmodel[pattern]
                except KeyError:
                    freq = 0
            if freq_joined > freq * self.settings['freqratio']:
                return word+nextword


    def server_handler(self, input):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        word, nextword = input.split("\t")
        return json.dumps(self.getmergesuggestion(word, nextword))

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        nextword = word.next()
        if nextword:
            return (str(word), str(nextword), nextword.id )

    def processoutput(self, suggestions, inputdata, unit_id,**parameters):
        _,_,next_id = inputdata
        return self.mergecorrection(suggestions, (unit_id, next_id))

    def run(self, input):
        word, nextword, _ = input
        return self.getmergesuggestion(word, nextword)

