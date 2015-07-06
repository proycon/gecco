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
import time
import datetime
from collections import OrderedDict
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from timbl import TimblClassifier #pylint: disable=import-error
from gecco.gecco import Module
from pynlpl.statistics import levenshtein


class TIMBLLMModule(Module):
    """The Language Model predicts words given their context (including right context). It uses a classifier-based approach.

    Settings:
    * ``threshold``    - Prediction confidence threshold, only when a prediction exceeds this threshold will it be recommended (default: 0.9, value must be higher than 0.5 by definition)
    * ``minlength``    - Only consider words with a suffix that are at least this long (in characters)
    * ``maxlength``    - Only consider words with a suffix that are at most this long (in characters)
    * ``leftcontext``  - Left context size (in words) for the feature vector
    * ``rightcontext`` - Right context size (in words) for the feature vector
    * ``maxdistance``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions)
    * ``algorithm``    - The Timbl algorithm to use (see -a parameter in timbl) (default: IGTree)
    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: contexterror) 
    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a classifier instance base model [``.ibase``]

    """
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'contexterror'

        super().verifysettings()

        if 'algorithm' not in self.settings:
            self.settings['algorithm'] = 1

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        if 'threshold' not in self.settings:
            self.threshold = self.settings['threshold']
        else:
            self.threshold = 0.9

        if 'maxdistance' not in self.settings:
            self.settings['maxdistance'] = 2


        #self.cache = getcache(self.settings, 1000)

        try:
            modelfile = self.models[0]
            if not modelfile.endswith(".ibase"):
                raise Exception("TIMBL models must have the extension ibase, got " + modelfile + " instead")
        except:
            raise Exception("Expected one model, got 0 or more")

    def gettimbloptions(self):
        return "-F Tabbed " + "-a " + str(self.settings['algorithm']) + " +D +vdb -G0"

    def load(self):
        """Load the requested modules from self.models"""
        self.errorlist = {}

        if not self.models:
            raise Exception("Specify one or more models to load!")

        self.log("Loading models...")
        modelfile = self.models[0]
        if not os.path.exists(modelfile):
            raise IOError("Missing expected model file: " + modelfile + ". Did you forget to train the system?")
        self.log("Loading model file " + modelfile + "...")
        fileprefix = modelfile.replace(".ibase","") #has been verified earlier
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions())
        self.classifier.load()

    def train(self, sourcefile, modelfile, **parameters):
        l = self.settings['leftcontext']
        r = self.settings['rightcontext']
        n = l + 1 + r

        self.log("Generating training instances...")
        fileprefix = modelfile.replace(".ibase","") #has been verified earlier
        classifier = TimblClassifier(fileprefix, self.gettimbloptions())
        if sourcefile.endswith(".bz2"):
            iomodule = bz2
        elif sourcefile.endswith(".gz"):
            iomodule = gzip
        else:
            iomodule = io
        with iomodule.open(sourcefile,mode='rt',encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i % 100000 == 0: print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " - " + str(i),file=sys.stderr)
                for ngram in Windower(line, n):
                    focus = ngram[l]
                    leftcontext = tuple(ngram[:l])
                    rightcontext = tuple(ngram[l+1:])
                    classifier.append( leftcontext + rightcontext , focus )

        self.log("Training classifier...")
        classifier.train()

        self.log("Saving model " + modelfile)
        classifier.save()


    def classify(self, word,debug=False):
        features = self.getfeatures(word)
        if debug:
            begintime = time.time()
        best, distribution,_ = self.classifier.classify(features)
        if debug:
            duration = round(time.time() - begintime,4)
            self.log(" (Classification took  " + str(duration) + "s, unfiltered distribution size=" + str(len(distribution)) + ")")

        if self.settings['maxdistance']:
            #filter suggestions that are too distant
            if debug:
                begintime = time.time()
            dist = {}
            for key, freq in distribution.items():
                if freq >= self.threshold and levenshtein(word,key) <= self.settings['maxdistance']:
                    dist[key] = freq
            if debug:
                duration = round(time.time() - begintime,4)
                self.log(" (Levenshtein filtering took  " + str(duration) + "s, final distribution size=" + str(len(dist)) + ")")
            return best, dist
        else:
            return best, distribution


    def getfeatures(self, word):
        """Get features at testing time"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + rightcontext


    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordstr = str(word)
        best, distribution = self.classify(word, 'debug' in parameters and parameters['debug'])
        if best != wordstr:
            distribution = [ x for x in distribution.items() if x[1] >= self.threshold ]
            if distribution:
                self.addsuggestions(lock, word, distribution)

    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        wordstr = str(word)
        best, distribution = json.loads(client.communicate(json.dumps(self.getfeatures(word))))
        if best != wordstr and distribution: #distribution filtering is done server-side
            self.addsuggestions(lock, word,distribution)

    def server_handler(self, features):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        features = tuple(json.loads(features))
        best,distribution,_ = self.classifier.classify(features)
        distribution = [ x for x in distribution.items() if x[1] >= self.threshold ]
        return json.dumps([best,distribution])

