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
import itertools
from collections import OrderedDict,defaultdict
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from timbl import TimblClassifier #pylint: disable=import-error
from gecco.gecco import Module
from gecco.helpers.hapaxing import gethapaxer
from gecco.helpers.caching import getcache
from gecco.helpers.common import stripsourceextensions
import colibricore #pylint: disable=import-error
import Levenshtein #pylint: disable=import-error


class TIMBLLMModule(Module):
    """The Language Model predicts words given their context (including right context). It uses a classifier-based approach.

    Settings:
    * ``threshold``    - Prediction confidence threshold, only when a prediction exceeds this threshold will it be recommended (default: 0.9, value must be higher than 0.5 by definition)
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


        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False


        self.hapaxer = gethapaxer(self.settings)

        self.cache = getcache(self.settings, 1000)

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



    def getfeatures(self, word):
        """Get features at testing time"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + rightcontext


    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word) #will be reused in processoutput
        features = self.getfeatures(word)
        if self.hapaxer: features = self.hapaxer(features) #pylint: disable=not-callable
        return wordstr, features

    def processoutput(self, outputdata, inputdata, unit_id,**parameters):
        wordstr,_ = inputdata
        best,distribution = outputdata
        if best != wordstr and distribution:
            return self.addsuggestions(unit_id, distribution)

    def run(self, inputdata):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        wordstr = inputdata[0]
        features = tuple(inputdata[1])
        if self.debug:
            begintime = time.time()
        if self.cache is not None:
            try:
                cached = self.cache[features]
                if self.debug:
                    duration = round(time.time() - begintime,4)
                    self.log(" (Return from cache in   " + str(duration) + "s)")
                return cached
            except KeyError:
                pass
        best,distribution,_ = self.classifier.classify(features)
        if self.debug:
            duration = round(time.time() - begintime,4)
            self.log(" (Classification took  " + str(duration) + "s, unfiltered distribution size=" + str(len(distribution)) + ")")

        l = len(wordstr)
        if self.settings['maxdistance']:
            #filter suggestions that are too distant
            if self.debug:
                begintime = time.time()
            dist = {}
            for key, freq in distribution.items():
                if freq >= self.threshold and abs(l - len(key)) <= self.settings['maxdistance'] and Levenshtein.distance(wordstr,key) <= self.settings['maxdistance']:
                    dist[key] = freq
            if self.debug:
                duration = round(time.time() - begintime,4)
                self.log(" (Levenshtein filtering took  " + str(duration) + "s, final distribution size=" + str(len(dist)) + ")")
            self.cache.append(features, (best,dist))
            return best, dist
        else:
            dist = [ x for x in distribution.items() if x[1] >= self.threshold ]
            self.cache.append(features, (best,dist))
            return best, dist 

class ColibriLMModule(Module):

    """The Language Model predicts words given their context (including right context). It uses a classifier-based approach.

    Settings:
    * ``threshold``    - Prediction confidence threshold, only when a prediction exceeds this threshold will it be recommended (default: 0.9, value must be higher than 0.5 by definition)
    * ``freqthreshold`` - Frequency threshold for patterns to be included in the model
    * ``leftcontext``  - Maximum left context size (in words) 
    * ``rightcontext``  - Maximum right context size (in words) 
    * ``maxdistance``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions)
    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: contexterror) 
    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a colibri indexed pattern model 

    """

    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'contexterror'

        super().verifysettings()

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        self.maxcontext = max(self.settings['leftcontext'], self.settings['rightcontext'])

        if 'freqthreshold' not in self.settings:
            self.threshold = 25

        if 'threshold' not in self.settings:
            self.threshold = self.settings['threshold']
        else:
            self.threshold = 0.9

        if 'maxdistance' not in self.settings:
            self.settings['maxdistance'] = 2


        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False


        self.hapaxer = gethapaxer(self.settings)

        self.cache = getcache(self.settings, 1000)

        try:
            modelfile = self.models[0]
        except:
            raise Exception("Expected one model, got 0 or more")

    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate Language Model")
        classfile = stripsourceextensions(sourcefile) +  ".cls"
        corpusfile = stripsourceextensions(sourcefile) +  ".dat"

        if not os.path.exists(classfile):
            self.log("Building class file")
            classencoder = colibricore.ClassEncoder() 
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

        if not os.path.exists(modelfile+'.cls'):
            #make symlink to class file, using model name instead of source name
            os.symlink(classfile, modelfile + '.cls')

        self.log("Generating pattern model")
        options = colibricore.PatternModelOptions(mintokens=self.settings['freqthreshold'],minlength=1,maxlength=self.maxcontext) 
        model = colibricore.IndexedPatternModel()
        model.train(corpusfile, options)

        self.log("Saving model " + modelfile)
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
        self.lexicon = colibricore.IndexedPatternModel(modelfile)

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word) #will be reused in processoutput
        leftcontext = [ str(w) for w in word.leftcontext(word, self.settings['leftcontext']) if w is not None ]
        rightcontext = [ str(w) for w in word.rightcontext(word, self.settings['rightcontext']) if w is not None ]
        if self.hapaxer: 
            leftcontext = self.hapaxer(leftcontext) #pylint: disable=not-callable
            rightcontext = self.hapaxer(rightcontext) #pylint: disable=not-callable
        return wordstr, leftcontext, rightcontext

    def run(self, input):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        word, leftcontext, rightcontext = input

        if self.debug:
            begintime = time.time()

        leftcontext = self.classencoder.buildpattern(" ".join(leftcontext))
        rightdist = {}
        while leftcontext:
            if not leftcontext.unknown():
                for p, freq in self.model.getrightneighbours(leftcontext, 0, 0, 1): #unigram focus only
                    rightdist[p] = freq
                if rightdist: 
                    break
            #shorten for next round
            leftcontext = leftcontext[1:]

        rightcontext = self.classencoder.buildpattern(" ".join(rightcontext))
        leftdist = {}
        while rightcontext:
            if not rightcontext.unknown():
                for p, freq in self.model.getleftneighbours(rightcontext, 0, 0, 1): #unigram focus only
                    leftdist[p] = freq

                if leftdist: 
                    break
            #shorten for next round
            rightcontext = rightcontext[:-1]

        if self.debug:
            lookupduration = round(time.time() - begintime,4)
            begintime = time.time()

        if not leftcontext:
            it = rightcontext.items()
        elif not rightcontext:
            it = leftcontext.items()
        elif not leftcontext and not rightcontext:
            if self.debug:
                self.log("(Nothing found, " + str(lookupduration) + "s)")
            return None
        else:
            it = itertools.chain(leftcontext.items(), rightcontext.items()) 


        distribution = defaultdict(int)
        l = len(word)
        bestfreq = 0
        best = None
        if self.debug: unfilteredcount = 0
        for w,freq in it:
            if self.debug: unfilteredcount += 1
            w = w.tostring(self.classdecoder)
            if self.settings['maxdistance'] and  abs(l - len(w)) <= self.settings['maxdistance'] and Levenshtein.distance(word,w) <= self.settings['maxdistance']:
                distribution[w] += freq 
            elif not self.settings['maxdistance']:
                distribution[w] += freq 
            if freq> bestfreq:
                best = w
                bestfreq = freq

    
        total = sum( ( x[1] for x in distribution) )
        normdist = {}
        for w, freq in distribution:
            if freq > total >= self.threshold:
                normdist[w] = freq / total

        if self.debug:
            filterduration = round(time.time() - begintime,4)
            self.log(" (Lookup took  " + str(lookupduration) + "s, filtering took " + str(filterduration) + ", unfiltered distribution size=" + str(unfilteredcount) + ", filtered size + " + str(len(normdist)) + ")")

        return best, normdist
            

    def processoutput(self, outputdata, inputdata, unit_id,**parameters):
        wordstr,_ = inputdata
        best,distribution = outputdata
        if best != wordstr and distribution:
            return self.addsuggestions(unit_id, distribution)
