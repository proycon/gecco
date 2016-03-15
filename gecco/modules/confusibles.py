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

#pylint: disable=too-many-nested-blocks

import os
import io
import bz2
import gzip
import sys
import datetime
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from timbl import TimblClassifier #pylint: disable=import-error
import colibricore #pylint: disable=import-error
from gecco.gecco import Module
from gecco.helpers.hapaxing import gethapaxer
from gecco.helpers.common import stripsourceextensions
from gecco.helpers.filters import nonumbers


class TIMBLWordConfusibleModule(Module):
    """The Word Confusible module is capable of disambiguating two or more words that are often confused, by looking at their context.
    The module is implemented using memory-based classifiers in Timbl.

    Settings:
    * ``confusibles``  - List of words (strings) that form a single set of confusibles.
    * ``leftcontext``  - Left context size (in words) for the feature vector (changing this requires retraining)
    * ``rightcontext`` - Right context size (in words) for the feature vector (changing this requires retraining)
    * ``algorithm``    - The Timbl algorithm to use (see -a parameter in timbl) (default: IGTree, changing this requires retraining)
    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: confusible)
    * ``threshold``    - The probability threshold that classifier options must attain to be passed on as suggestions. (default: 0.8)
    * ``minocc``       - The minimum number of occurrences (sum of all class weights) (default: 5)

    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a classifier instance base model [``.ibase``]

    Hapaxer: This module supports hapaxing
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
            self.settings['threshold'] = 0.8

        if 'minocc' not in self.settings:
            self.settings['minocc'] = 5

        self.hapaxer = gethapaxer(self, self.settings)

        if 'confusibles' not in self.settings:
            raise Exception("No confusibles specified for " + self.id + "!")
        self.confusibles = self.settings['confusibles']

        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False

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
        if self.hapaxer:
            self.log("Loading hapaxer...")
            self.hapaxer.load()

        if not self.models:
            raise Exception("Specify one or more models to load!")

        self.log("Loading models...")
        modelfile = self.models[0]
        if not os.path.exists(modelfile):
            raise IOError("Missing expected model file: " + modelfile + ". Did you forget to train the system?")
        self.log("Loading model file " + modelfile + "...")
        fileprefix = modelfile.replace(".ibase","") #has been verified earlier
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions(), normalize=False) #pylint: disable=attribute-defined-outside-init
        self.classifier.load()

    def train(self, sourcefile, modelfile, **parameters):
        if self.hapaxer:
            self.log("Training hapaxer...")
            self.hapaxer.train()

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
        with iomodule.open(sourcefile,mode='rt',encoding='utf-8',errors='ignore') as f:
            for i, line in enumerate(f):
                if i % 100000 == 0: print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " - " + str(i),file=sys.stderr)
                for ngram in Windower(line, n):
                    confusible = ngram[l]
                    if confusible in self.settings['confusibles']:
                        if self.hapaxer:
                            ngram = self.hapaxer(ngram)
                        leftcontext = tuple(ngram[:l])
                        rightcontext = tuple(ngram[l+1:])
                        classifier.append( leftcontext + rightcontext , confusible )

        self.log("Training classifier...")
        classifier.train()

        self.log("Saving model " + modelfile)
        classifier.save()


    def getfeatures(self, word):
        """Get features at testing time, crosses sentence boundaries"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + rightcontext


    def classify(self, features):
        if self.hapaxer: features = self.hapaxer(features)
        best,distribution,_ = self.classifier.classify(features)
        sumweights = sum(distribution.values())
        if self.debug: self.log("(Classified " + repr(features) + ", best=" + best + ", sumweights=" + str(sumweights) + ", distribution=" + repr(distribution) + ")")
        if sumweights < self.settings['minocc']:
            if self.debug: self.log("(Not passing minocc threshold)")
            return best, []
        distribution = { sug: weight/sumweights for sug,weight in distribution.items() if weight/sumweights >= self.settings['threshold'] }
        if self.debug: self.log("(Returning " + str(len(distribution)) + " suggestions after filtering)")
        return best,distribution

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word) #will be reused in processoutput
        if wordstr in self.confusibles:
            features = self.getfeatures(word)
            return wordstr, features

    def run(self, inputdata):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        _, features = inputdata
        best, distribution = self.classify(features)
        return (best,distribution)

    def processoutput(self, output, inputdata, unit_id,**parameters):
        wordstr, _  = inputdata
        best,distribution = output
        if best and best != wordstr and distribution:
            return self.addsuggestions(unit_id, list(distribution.items()))


class TIMBLSuffixConfusibleModule(Module):
    """The Suffix Confusible module is capable of disambiguating suffixes on words. The suffixes are passes to the ``suffixes`` settings (a list of string). All words using these suffixes above a certain threshold (``freqthtreshold``) will be found at training time and disambiguated using context. The module is implemented using Timbl.

    Settings:
    * ``suffixes``     - List of suffixes (strings) that form a single set of confusibles. (changing this requires retraining)
    * ``freqthreshold``- Only consider words with a suffix that occur at least this many times (changing this requires retraining)
    * ``maxratio``     - Maximum ratio expressing the maximally allowed frequency difference between the confusibles (value > 1, 0 = no limit) (changing this requires retraining)
    * ``minlength``    - Only consider words with a suffix that are at least this long (in characters) (changing this requires retraining)
    * ``maxlength``    - Only consider words with a suffix that are at most this long (in characters) (changing this requires retraining)
    * ``leftcontext``  - Left context size (in words) for the feature vector (changing this requires retraining)
    * ``rightcontext`` - Right context size (in words) for the feature vector (changing this requires retraining)
    * ``algorithm``    - The Timbl algorithm to use (see -a parameter in timbl) (default: IGTree) (changing this requires retraining)
    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: confusible)
    * ``threshold``    - The probability threshold that classifier options must attain to be passed on as suggestions. (default: 0.8)
    * ``minocc``       - The minimum number of occurrences (sum of all class weights) (default: 5)

    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a list of confusibles [``.lst``]
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a classifier instance base model [``.ibase``]

    Hapaxer: This module supports hapaxing
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
            self.settings['threshold'] = 0.8
        if 'minocc' not in self.settings:
            self.settings['minocc'] = 5

        self.hapaxer = gethapaxer(self, self.settings)


        if 'suffixes' not in self.settings:
            raise Exception("No suffixes specified for " + self.id + "!")
        self.suffixes = sorted(self.settings['suffixes'], key= lambda x: -1* len(x))  #sort from long to short

        #settings for computation of confusible list
        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 20
        if 'maxlength' not in self.settings:
            self.settings['maxlength'] = 25 #longer words will be ignored
        if 'minlength' not in self.settings:
            self.settings['minlength'] = 3 #shorter word will be ignored
        if 'maxratio' not in self.settings:
            self.settings['maxratio'] = 0 #no limit

        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False


        ibasefound = lstfound = False
        for filename in self.models:
            if filename.endswith('.ibase'):
                ibasefound = True
                self.modelfile = filename
            elif filename.endswith('.lst'):
                lstfound = True
                self.confusiblefile = filename

        if not ibasefound:
            raise Exception("TIMBL models must have the extension ibase, not model file was supplies with that extension")
        if not lstfound:
            raise Exception("Specify a model file with extension lst that will store all confusibles found")

    def gettimbloptions(self):
        return "-F Tabbed " + "-a " + str(self.settings['algorithm']) + " +D +vdb -G0"

    def load(self):
        """Load the requested modules from self.models"""
        if self.hapaxer:
            self.log("Loading hapaxer...")
            self.hapaxer.load()

        if not self.models:
            raise Exception("Specify one or more models to load!")


        self.confusibles = []#pylint: disable=attribute-defined-outside-init

        self.log("Loading models...")
        if not os.path.exists(self.confusiblefile):
            raise IOError("Missing expected confusible file: "  + self.confusiblefile + ". Did you forget to train the system?")
        with open(self.confusiblefile,'r',encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    self.confusibles.append(line)
        if not os.path.exists(self.modelfile):
            raise IOError("Missing expected model file: " + self.modelfile + ". Did you forget to train the system?")
        self.log("Loading Timbl model file " + self.modelfile + "...")
        fileprefix = self.modelfile.replace(".ibase","") #has been verified earlier
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions(), normalize=False) #pylint: disable=attribute-defined-outside-init
        self.classifier.load()

    def clientload(self):
        self.log("Loading models (for client)...")
        self.confusibles = []#pylint: disable=attribute-defined-outside-init
        if not os.path.exists(self.confusiblefile):
            raise IOError("Missing expected confusible file: "  + self.confusiblefile + ". Did you forget to train the system?")
        with open(self.confusiblefile,'r',encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    self.confusibles.append(line)

    def train(self, sourcefile, modelfile, **parameters):
        if modelfile == self.confusiblefile:
            #Build frequency list
            self.log("Preparing to generate lexicon for suffix confusible module")
            classfile = stripsourceextensions(sourcefile) +  ".cls"
            corpusfile = stripsourceextensions(sourcefile) +  ".dat"

            if not os.path.exists(classfile):

                self.log("Building class file")
                classencoder = colibricore.ClassEncoder("", self.settings['minlength'], self.settings['maxlength']) #character length constraints
                classencoder.build(sourcefile)
                classencoder.save(classfile)
            else:
                classencoder = colibricore.ClassEncoder(classfile, self.settings['minlength'], self.settings['maxlength'])


            if not os.path.exists(corpusfile):
                self.log("Encoding corpus")
                classencoder.encodefile( sourcefile, corpusfile)

            self.log("Generating frequency list")
            options = colibricore.PatternModelOptions(mintokens=self.settings['freqthreshold'],minlength=1,maxlength=1) #unigrams only
            model = colibricore.UnindexedPatternModel()
            model.train(corpusfile, options)


            self.log("Finding confusible pairs")
            classdecoder = colibricore.ClassDecoder(classfile)
            self.confusibles = [] #pylint: disable=attribute-defined-outside-init
            for pattern in model:
                try:
                    pattern_s = pattern.tostring(classdecoder)
                except UnicodeDecodeError:
                    self.log("WARNING: Unable to decode a pattern in the model!!! Invalid utf-8!")
                for suffix in self.suffixes:
                    if pattern_s.endswith(suffix) and not pattern_s in self.confusibles:
                        found = []
                        for othersuffix in self.suffixes:
                            if othersuffix != suffix:
                                otherpattern_s = pattern_s[:-len(suffix)] + othersuffix
                                try:
                                    otherpattern = classencoder.buildpattern(otherpattern_s,False,False)
                                except KeyError:
                                    if found: found = []
                                    break
                                if not otherpattern in model:
                                    if found: found = []
                                    break
                                if self.settings['maxratio'] != 0:
                                    freqs = (model.occurrencecount(pattern), model.occurrencecount(otherpattern))
                                    ratio = max(freqs) / min(freqs)
                                    if ratio < self.settings['maxratio']:
                                        if found: found = []
                                        break
                                found.append(otherpattern_s )
                        if found:
                            self.confusibles.append(pattern_s)
                            for s in found:
                                self.confusibles.append(s)

            self.log("Writing confusible list")
            with open(modelfile,'w',encoding='utf-8') as f:
                for confusible in self.confusibles:
                    f.write(confusible + "\n")

        elif modelfile == self.modelfile:
            try:
                self.confusibles
            except AttributeError:
                self.confusibles = []
                self.log("Loading confusiblefile")
                with open(self.confusiblefile,'r',encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.confusibles.append(line)

            if self.hapaxer:
                self.log("Training hapaxer...")
                self.hapaxer.train()

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
            with iomodule.open(sourcefile,mode='rt',encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f):
                    for ngram in Windower(line, n):
                        if i % 100000 == 0: print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " - " + str(i),file=sys.stderr)
                        confusible = ngram[l]
                        if confusible in self.confusibles:
                            if self.hapaxer:
                                ngram = self.hapaxer(ngram)
                            leftcontext = tuple(ngram[:l])
                            rightcontext = tuple(ngram[l+1:])
                            suffix, normalized = self.getsuffix(confusible)
                            if suffix is not None:
                                classifier.append( leftcontext + (normalized,) + rightcontext , suffix )

            self.log("Training classifier...")
            classifier.train()

            self.log("Saving model " + modelfile)
            classifier.save()


    def getsuffix(self, confusible):
        assert isinstance(confusible, str)
        suffix = None
        for suffix in self.suffixes: #suffixes are sorted from long to short
            if confusible.endswith(suffix):
                break
        if suffix is None:
            raise ValueError("No suffix found!")
        return suffix, confusible[:-len(suffix)] + self.suffixes[0]  #suffix, normalized



    def classify(self, features):
        if self.hapaxer: features = self.hapaxer(features)
        best,distribution,_ = self.classifier.classify(features)
        sumweights = sum(distribution.values())
        if sumweights < self.settings['minocc']:
            return best, []
        distribution = { sug: weight/sumweights for sug,weight in distribution.items() if weight/sumweights >= self.settings['threshold'] }
        if self.debug: self.log("(Returning " + str(len(distribution)) + " suggestions after filtering)")
        return (best,distribution)

    def getfeatures(self, word):
        """Get features at testing time, crosses sentence boundaries"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        _, normalized = self.getsuffix(word.text())
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + (normalized,) + rightcontext


    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            features = self.getfeatures(word)
            return wordstr, features

    def run(self, inputdata):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        _,features = inputdata
        best,distribution = self.classify(features)
        return (best,distribution)

    def processoutput(self, output, inputdata, unit_id,**parameters):
        wordstr,_ = inputdata
        best,distribution = output
        suffix,_ = self.getsuffix(wordstr)
        if wordstr != wordstr[:-len(suffix)] + best:
            return self.addsuggestions(unit_id, [ (wordstr[:-len(suffix)] + suggestion,p) for suggestion,p in distribution.items() if suggestion != suffix] )
