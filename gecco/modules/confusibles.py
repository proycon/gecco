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

import os
import json
import io
import bz2
import gzip
from pynlpl.formats import folia
from pynlpl.textprocessors import Windower
from timbl import TimblClassifier
import colibricore #pylint: disable=import-error
from gecco.gecco import Module
from gecco.helpers.hapaxing import gethapaxer


class TIMBLWordConfusibleModule(Module):
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'confusible'

        super().verifysettings()

        if 'algorithm' not in self.settings:
            self.settings['algorithm'] = 1

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        self.hapaxer = gethapaxer(self.settings)

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
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions()) #pylint: disable=attribute-defined-outside-init
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
        with iomodule.open(sourcefile,mode='rt',encoding='utf-8') as f:
            for line in f:
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


    def classify(self, word):
        features = self.getfeatures(word)
        if self.hapaxer: features = self.hapaxer(features)
        best, distribution,_ = self.classifier.classify(features)
        return best, distribution


    def getfeatures(self, word):
        """Get features at testing time, crosses sentence boundaries"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + rightcontext


    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            #the word is one of our confusibles
            best, distribution = self.classify(word)
            if best != word:
                self.addsuggestions(lock, word, list(distribution.items()))

    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            best, distribution = json.loads(client.communicate(json.dumps(self.getfeatures(word))))
            if best != word:
                self.addsuggestions(lock, word, list(distribution.items()))

    def server_handler(self, features):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        features = tuple(json.loads(features))
        best,distribution,_ = self.classifier.classify(features)
        return json.dumps([best,distribution])


class TIMBLSuffixConfusibleModule(Module):
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'confusible'

        super().verifysettings()

        if 'algorithm' not in self.settings:
            self.settings['algorithm'] = 1

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 3

        self.hapaxer = gethapaxer(self.settings)

        if 'confusibles' not in self.settings:
            raise Exception("No confusibles specified for " + self.id + "!")
        self.confusibles = self.settings['confusibles']

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
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions()) #pylint: disable=attribute-defined-outside-init
        self.classifier.load()

    def train(self, sourcefile, modelfile, **parameters):
        if modelfile == self.confusiblefile:
            #Build frequency list
            self.log("Preparing to generate lexicon for suffix confusible module")
            classfile = modelfile.replace('.lst','')  +  ".cls"
            corpusfile = modelfile.replace('.lst','') +  ".dat"

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
                pattern_s = pattern.tostring(classdecoder)
                for suffix in self.suffixes:
                    if pattern_s.endswith(suffix) and not pattern_s in self.confusibles:
                        found = []
                        for othersuffix in self.suffixes:
                            if othersuffix != suffix:
                                otherpattern_s = pattern_s[:-len(suffix)] + othersuffix
                                try:
                                    pattern_s = classencoder.buildpattern(otherpattern_s,False,False)
                                except KeyError:
                                    if found: found = []
                                    break
                                if not pattern_s in model:
                                    if found: found = []
                                    break
                                found.append(otherpattern_s)
                        if found:
                            self.confusibles.append(pattern_s)
                            for s in found:
                                self.confusibles.append(s)

            self.log("Writing confusible list")
            with open(modelfile,'w',encoding='utf-8') as f:
                for confusible in self.confusibles:
                    f.write(confusible + "\n")

        elif modelfile == self.modelfile:
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
            with iomodule.open(sourcefile,mode='rt',encoding='utf-8') as f:
                for line in f:
                    for ngram in Windower(line, n):
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
        suffix = None
        for suffix in self.suffixes: #suffixes are sorted from long to short
            if confusible.endswith(suffix):
                break
        if suffix is None:
            raise ValueError("No suffix found!")
        return suffix, confusible[:-len(suffix)] + self.suffixes[0]  #suffix, normalized



    def classify(self, word):
        features = self.getfeatures(word)
        if self.hapaxer: features = self.hapaxer(features)
        best, distribution,_ = self.classifier.classify(features)
        return best, distribution


    def getfeatures(self, word):
        """Get features at testing time, crosses sentence boundaries"""
        leftcontext = tuple([ str(w) for w in word.leftcontext(self.settings['leftcontext'],"<begin>") ])
        _, normalized = self.getsuffix(word)
        rightcontext = tuple([ str(w) for w in word.rightcontext(self.settings['rightcontext'],"<end>") ])
        return leftcontext + tuple(normalized,) + rightcontext


    def processresult(self,word, lock, best, distribution):
        suffix,_ = self.getsuffix(word)
        if word != word[:-len(suffix)] + best:
            self.addsuggestions(lock, word, [ (word[:-len(suffix)] + suggestion,p) for suggestion,p in distribution.items() if suggestion != suffix] )


    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            #the word is one of our confusibles
            best, distribution = self.classify(word)
            self.processresult(word,lock,best,distribution)

    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        wordstr = str(word)
        if wordstr in self.confusibles:
            best, distribution = json.loads(client.communicate(json.dumps(self.getfeatures(word))))
            self.processresult(word,lock,best,distribution)

    def server_handler(self, features):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        features = tuple(json.loads(features))
        best,distribution,_ = self.classifier.classify(features)
        return json.dumps([best,distribution])
