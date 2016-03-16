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
import io
import bz2
import gzip
import time
import datetime
import itertools
from collections import defaultdict
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from timbl import TimblClassifier #pylint: disable=import-error
from gecco.gecco import Module
from gecco.helpers.hapaxing import gethapaxer
from gecco.helpers.caching import getcache
from gecco.helpers.common import stripsourceextensions
from gecco.helpers.filters import nonumbers
import colibricore #pylint: disable=import-error
import Levenshtein #pylint: disable=import-error

#pylint: disable=too-many-nested-blocks,attribute-defined-outside-init

class TIMBLLMModule(Module):
    """The Language Model predicts words given their context (including right context). It uses a classifier-based approach.

    Settings:
    * ``threshold``    - Prediction confidence threshold, only when a prediction exceeds this threshold will it be recommended (default: 0.9, value must be higher than 0.5 by definition)
    * ``freqthreshold`` - If the previous word occurs below this threshold, then no classification will take place. Only has an effect when a lexicon is enabled (default: 2)
    * ``leftcontext``  - Left context size (in words) for the feature vector
    * ``rightcontext`` - Right context size (in words) for the feature vector
    * ``maxdistance``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions)
    * ``minlength``    - Minimum length (in characters) for a word to be considered by the LM module
    * ``probfactor``   - If the predicted word is in the target distribution, any suggestions must be more probable by this factor (default: 10)
    * ``algorithm``    - The Timbl algorithm to use (see -a parameter in timbl) (default: IGTree)
    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: confusion)

    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a classifier instance base model [``.ibase``]
    * optional: a plain-text corpus (tokenized)  [``.txt``]     ->    a lexicon model [``.colibri.patternmodel``]

    Hapaxer: This module supports hapaxing
    Caching: This module supports caching
    """
    UNIT = folia.Word
    UNITFILTER = nonumbers

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'confusion'

        super().verifysettings()

        if 'algorithm' not in self.settings:
            self.settings['algorithm'] = 1

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        if 'threshold' not in self.settings:
            self.threshold = 0.9
        else:
            self.threshold = self.settings['threshold']

        if 'freqthreshold' not in self.settings:
            self.freqthreshold = 2
        else:
            self.freqthreshold = self.settings['freqthreshold']

        if 'minlength' not in self.settings:
            self.minlength = 5
        else:
            self.minlength = self.settings['minlength']

        if 'probfactor' not in self.settings:
            self.probfactor = 10
        else:
            self.probfactor = self.settings['probfactor']


        if 'maxdistance' not in self.settings:
            self.settings['maxdistance'] = 2


        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False


        self.hapaxer = gethapaxer(self, self.settings)

        self.cache = getcache(self.settings, 1000)

        try:
            modelfile = self.models[0]
            if not modelfile.endswith(".ibase"):
                raise Exception("First model must be a TIMBL instance base model, which must have the extension '.ibase', got " + modelfile + " instead")
            if len(self.models) > 1:
                lexiconfile = self.models[1]
                if not lexiconfile.endswith("colibri.patternmodel"):
                    raise Exception("Second model must be a Colibri pattern model, which must have the extensions '.colibri.patternmodel', got " + modelfile + " instead")
        except:
            raise Exception("Expected one or two models, the first a TIMBL instance base, and the optional second a colibri patternmodel, got " + str(len(self.models)) )

    def gettimbloptions(self):
        return "-F Tabbed " + "-a " + str(self.settings['algorithm']) + " +D +vdb -G0"

    def load(self):
        """Load the requested modules from self.models"""
        self.errorlist = {}

        if not self.models:
            raise Exception("Specify one or more models to load!")

        if self.hapaxer:
            self.log("Loading hapaxer...")
            self.hapaxer.load()

        self.log("Loading models...")
        if len(self.models) == 2:
            modelfile, lexiconfile = self.models
        else:
            modelfile = self.models[0]
            lexiconfile = None
        if not os.path.exists(modelfile):
            raise IOError("Missing expected timbl model file: " + modelfile + ". Did you forget to train the system?")
        if lexiconfile and not os.path.exists(lexiconfile):
            raise IOError("Missing expected lexicon model file: " + lexiconfile + ". Did you forget to train the system?")
        self.log("Loading model file " + modelfile + "...")
        fileprefix = modelfile.replace(".ibase","") #has been verified earlier
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions(),threading=True, debug=self.debug)
        self.classifier.load()

        if lexiconfile:
            self.log("Loading colibri model file for lexicon " + lexiconfile)
            self.classencoder = colibricore.ClassEncoder(lexiconfile + '.cls')
            self.lexicon = colibricore.UnindexedPatternModel(lexiconfile)
        else:
            self.lexicon = None

    def train(self, sourcefile, modelfile, **parameters):
        if self.hapaxer:
            self.log("Training hapaxer...")
            self.hapaxer.train()
        if modelfile.endswith('.ibase'):
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
                        if self.hapaxer:
                            ngram = self.hapaxer(ngram)
                        focus = ngram[l]
                        if self.hapaxer and focus == self.hapaxer.placeholder:
                            continue
                        leftcontext = tuple(ngram[:l])
                        rightcontext = tuple(ngram[l+1:])
                        classifier.append( leftcontext + rightcontext , focus )

            self.log("Training classifier...")
            classifier.train()

            self.log("Saving model " + modelfile)
            classifier.save()
        elif modelfile.endswith('.patternmodel'):
            self.log("Preparing to generate lexicon for Language Model")
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
            options = colibricore.PatternModelOptions(mintokens=self.settings['freqthreshold'],minlength=1,maxlength=1)
            model = colibricore.UnindexedPatternModel()
            model.train(corpusfile, options)

            self.log("Saving model " + modelfile)
            model.write(modelfile)


    def getfeatures(self, word):
        """Get features at testing time"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + rightcontext


    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word) #will be reused in processoutput
        if len(wordstr) > self.minlength:
            features = self.getfeatures(word)
            return wordstr, features

    def processoutput(self, outputdata, inputdata, unit_id,**parameters):
        wordstr,_ = inputdata
        if wordstr is not None:
            best,distribution = outputdata
            if best != wordstr and distribution:
                return self.addsuggestions(unit_id, distribution)

    def run(self, inputdata):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        if self.debug:
            begintime = time.time()

        wordstr = inputdata[0]
        features = tuple(inputdata[1])
        if self.debug:
            self.log(" (Processing word " + wordstr + ", features: " + repr(features) + ")")

        if self.hapaxer:
            features = self.hapaxer(features) #pylint: disable=not-callable
            previousword = features[self.settings['leftcontext'] - 1]
            if previousword == self.hapaxer.placeholder:
                if self.debug:
                    duration = round(time.time() - begintime,4)
                    self.log(" (Previous word not in hapaxer, returned in   " + str(duration) + "s)")
                return None,None

        if self.cache is not None:
            try:
                cached = self.cache[features]
                if self.debug:
                    duration = round(time.time() - begintime,4)
                    self.log(" (Return from cache in   " + str(duration) + "s)")
                return cached
            except KeyError:
                pass

        if self.lexicon:
            #ensure the previous word exists
            previousword = features[self.settings['leftcontext'] - 1]
            pattern = self.classencoder.buildpattern(previousword)
            if pattern.unknown() or pattern not in self.lexicon:
                if self.debug:
                    duration = round(time.time() - begintime,4)
                    self.log(" (Previous word not in lexicon, returned in   " + str(duration) + "s)")
                return None,None
                #if self.settings['rightcontext']:
                #    nextword = features[self.settings['leftcontext']]
                #    pattern = self.classencoder.buildpattern(nextword)
                #    if pattern.unknown() or pattern not in self.lexicon:
                #        return None,None
                #else:
                #    return None,None



        best,distribution,_ = self.classifier.classify(features,allowtopdistribution=False)
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
            if wordstr in dist:
                #typed word is part of distribution, are any of the candidates far more likely?
                basefreq = dist[wordstr]
                dist = { key: freq for key, freq in dist.items() if key == wordstr or freq > basefreq * self.probfactor }
                if len(dist) == 1:
                    #no correction necessary
                    return None, None
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
    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: confusion)
    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a colibri indexed pattern model

    """

    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'confusion'

        super().verifysettings()

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        self.maxcontext = max(self.settings['leftcontext'], self.settings['rightcontext'])

        if 'freqthreshold' not in self.settings:
            self.freqthreshold = 25

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


        self.hapaxer = gethapaxer(self, self.settings)

        self.cache = getcache(self.settings, 1000)

        try:
            self.models[0]
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
        self.model = colibricore.IndexedPatternModel(modelfile)

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word) #will be reused in processoutput
        leftcontext = [ str(w) for w in word.leftcontext(self.settings['leftcontext']) if w is not None ]
        rightcontext = [ str(w) for w in word.rightcontext(self.settings['rightcontext']) if w is not None ]
        if self.hapaxer:
            leftcontext = self.hapaxer(leftcontext) #pylint: disable=not-callable
            rightcontext = self.hapaxer(rightcontext) #pylint: disable=not-callable
        return wordstr, leftcontext, rightcontext

    def run(self, inputdata):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        word, leftcontext, rightcontext = inputdata

        if self.debug:
            begintime = time.time()

        leftdist = {}
        rightdist = {}

        if leftcontext:
            leftcontext = self.classencoder.buildpattern(" ".join(leftcontext))
            while len(leftcontext) > 0:
                if not leftcontext.unknown() and leftcontext in self.model:
                    for p, freq in self.model.getrightneighbours(leftcontext, 0, 0, 1,10000): #unigram focus only, cutoff at 10000 (trades accuracy for speed)
                        rightdist[p] = freq
                    if rightdist:
                        break
                #shorten for next round
                if len(leftcontext) == 1:
                    break
                else:
                    leftcontext = leftcontext[1:]

        if rightcontext:
            rightcontext = self.classencoder.buildpattern(" ".join(rightcontext))
            while len(rightcontext) > 0:
                if not rightcontext.unknown() and rightcontext in self.model:
                    for p, freq in self.model.getleftneighbours(rightcontext, 0, 0, 1,10000): #unigram focus only, cutoff at 10000 (trades accuracy for speed)
                        leftdist[p] = freq

                    if leftdist:
                        break

                #shorten for next round
                if len(rightcontext) == 1:
                    break
                else:
                    rightcontext = rightcontext[:len(rightcontext) - 1]

        if self.debug:
            lookupduration = round(time.time() - begintime,4)
            begintime = time.time()

        if not leftcontext:
            it = rightdist.items()
        elif not rightcontext:
            it = leftdist.items()
        elif not leftcontext and not rightcontext:
            if self.debug:
                self.log("(Nothing found, " + str(lookupduration) + "s)")
            return None
        else:
            it = itertools.chain(leftdist.items(), rightdist.items())



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


        total = sum(  distribution.values() )
        normdist = {}
        for w, freq in distribution.items():
            freqnorm = freq/total
            if freqnorm >= self.threshold:
                normdist[w] = freqnorm

        if self.debug:
            filterduration = round(time.time() - begintime,4)
            self.log(" (Lookup took  " + str(lookupduration) + "s, filtering took " + str(filterduration) + ", unfiltered distribution size=" + str(unfilteredcount) + ", filtered size= " + str(len(normdist)) + ")")

        return best, normdist


    def processoutput(self, outputdata, inputdata, unit_id,**parameters):
        wordstr,_,_ = inputdata
        best,distribution = outputdata
        if best != wordstr and distribution:
            return self.addsuggestions(unit_id, distribution)
