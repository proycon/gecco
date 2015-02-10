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
import colibricore


def splits(s):
    for i in range(1,len(s) -2):
        yield (s[:i], s[i:])

class RunOnModule(Module):
    """Detects words that have been joined together but should be split"""
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'runonerror'

        super().verifysettings()

        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 10


    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate bigram model")
        classfile = modelfile  +  ".cls"
        corpusfile = modelfile +  ".dat"

        if not os.path.exists(classfile):
            self.log("Building class file")
            classencoder = colibricore.ClassEncoder() #character length constraints
            classencoder.build(sourcefile)
            classencoder.save(classfile)
        else:
            classencoder = colibricore.ClassEncoder(classfile)


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
            if freq > freq_joined:
                if freq > maxfreq:
                    maxfreq = freq
                suggestions.append( (parts, freq) )

        return [ (parts, freq / maxfreq) for parts, freq in suggestions ] #normalise confidence score (highest option = 1)

    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordstr = str(word)
        suggestions = self.splitsuggestions(wordstr)
        if suggestions:
            self.splitcorrection(lock, word, suggestions)


    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        wordstr = str(word)
        suggestions = json.loads(client.communicate(wordstr))
        if suggestions:
            self.splitcorrection(lock, word, suggestions )

    def server_handler(self, word):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        return json.dumps(self.splitsuggestions(word))


class SplitModule(Module):
    """Detects words that have been split but should be merged together as one"""
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'spliterror'

        super().verifysettings()

        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 10


    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate bigram model")
        classfile = modelfile  +  ".cls"
        corpusfile = modelfile +  ".dat"

        if not os.path.exists(classfile):
            self.log("Building class file")
            classencoder = colibricore.ClassEncoder() #character length constraints
            classencoder.build(sourcefile)
            classencoder.save(classfile)
        else:
            classencoder = colibricore.ClassEncoder(classfile)


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
            if freq_joined > freq:
                return word+nextword


    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        nextword = word.next()
        if nextword:
            suggestion = self.getmergesuggestion(str(word), str(nextword))
            if suggestion:
                self.mergecorrection(lock, suggestion, [word])


    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        nextword = word.next()
        if nextword:
            nextword = str(nextword)
            wordstr = str(word)
            suggestion = json.loads(client.communicate(wordstr+"\t" + nextword))
            if suggestion:
                self.mergecorrection(lock, suggestion, [word])

    def server_handler(self, input):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        word, nextword = input.split("\t")
        return json.dumps(self.getmergesuggestion(word, nextword))
