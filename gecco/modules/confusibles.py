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
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from timbl import TimblClassifier
from gecco.gecco import Module


class TIMBLWordConfusibleModule(Module):
    UNIT = folia.Word

    def verifysettings(self):
        super().verifysettings()

        if 'algorithm' not in self.settings:
            self.settings['algorithm'] = "IG"

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        if 'confusibles' not in self.settings:
            raise Exception("No confusibles specified for " + self.id + "!")
        self.confusibles = self.settings['confusibles']

        try:
            modelfile = self.models[0]
            if not modelfile.endswith(".ibase"):
                raise Exception("TIMBL models must have the extension ibase, got " + modelfile + " instead")
        except:
            raise Exception("Expected one model, got 0 or more")

    def gettimbloptions(self):
        return "-F Tabbed " + "-a " + self.settings['algorithm'] + " +vdb -G0"

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
            for line in f:
                for ngram in Windower(line, n):
                    confusible = ngram[l]
                    leftcontext = tuple(ngram[:l])
                    rightcontext = tuple(ngram[l+1:])
                    if confusible in self.settings['confusibles']:
                        classifier.append( leftcontext + rightcontext , confusible )

        self.log("Training classifier...")
        classifier.train()

        self.log("Saving model " + modelfile)
        classifier.save()


    def classify(self, word):
        features = self.getfeatures(word)
        _,distribution,_ = self.classifier.classify(features)
        return distribution


    def getfeatures(self, word):
        """Get features at testing time"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + rightcontext


    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            #the word is one of our confusibles
            distribution = self.classify(word)
            self.addwordsuggestions(lock, word, list(distribution.items()))

    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            distribution = json.loads(client.communicate(json.dumps(self.getfeatures())))
            self.addwordsuggestions(lock, word, list(distribution.items()))

    def server_handler(self, features):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        features = tuple(json.loads(features))
        _,distribution,_ = self.classifier.classify(features)
        return json.dumps(distribution)

