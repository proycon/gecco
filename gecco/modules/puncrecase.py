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

#pylint: disable=attribute-defined-outside-init

import sys
import os
import io
import bz2
import gzip
import datetime
from pynlpl.textprocessors import Windower
from pynlpl.formats import folia #pylint: disable=import-error
import colibricore #pylint: disable=import-error
from timbl import TimblClassifier #pylint: disable=import-error
from gecco.gecco import Module
from gecco.helpers.hapaxing import gethapaxer
from gecco.helpers.filters import nonumbers
from gecco.helpers.common import stripsourceextensions



class ColibriPuncRecaseModule(Module):
    """This is punctuation and recase module implemented using Colibri Core, it predicts where punctuation needs to be inserted, deleted, and whether a word needs to be written with an initial capital.

    Settings:
    * ``deletionthreshold`` - The bigram stripped of punctuation must occur at least this many times for a deletion to be predicted (must be a high value)
    * ``deletioncutoff`` - The original trigram with punctuation may not occur more than this many times. (must be a low value)
    * ``insertionthreshold`` - The trigram with punctuation must occur at least this many times for an insertion to be predicted  (must be a high value)
    * ``insertioncutoff`` - The original bigram may not occur over this-many times (must be a low value)

    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a classifier instance base model [``.ibase``]
    """

    UNIT = folia.Paragraph
    UNITFILTER = nonumbers

    EOSMARKERS = ('.','?','!')
    PUNCTUATION = EOSMARKERS + (',',';',':')

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'missingpunctuation' #will be overriden later again

        super().verifysettings()

        if 'deletionthreshold' not in self.settings:
            self.settings['deletionthreshold'] = 200

        if 'insertionthreshold' not in self.settings:
            self.settings['insertionthreshold'] = 100

        if 'insertioncutoff' not in self.settings:
            self.settings['insertioncutoff'] = 2

        if 'deletioncutoff' not in self.settings:
            self.settings['deletioncutoff'] = 2


        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False


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
        options = colibricore.PatternModelOptions(mintokens=self.settings['insertioncutoff'],minlength=2,maxlength=2) #bigrams
        model = colibricore.UnindexedPatternModel()
        model.train(corpusfile, options)

        self.log("Saving model")
        model.write(modelfile)
        del model


        filterpatterns = colibricore.PatternSet()
        for punc in ColibriPuncRecaseModule.PUNCTUATION:
            filterpattern = classencoder.build('{?} ' + punc + ' {?}')
            if not filterpattern.unknown():
                filterpatterns.add(filterpattern)

        self.log("Generating filtered trigram frequency list")
        options = colibricore.PatternModelOptions(mintokens=self.settings['deletioncutoff'],minlength=3,maxlength=3) #trigrams
        model = colibricore.UnindexedPatternModel()
        model.train_filtered(corpusfile, options, filterpatterns)

        self.log("Saving model")
        model.write(modelfile + '.3')

    def load(self):
        """Load the requested modules from self.models"""
        if not self.models:
            raise Exception("Specify one or more models to load!")

        self.log("Loading models...")
        modelfile = self.models[0]
        if not os.path.exists(modelfile):
            raise IOError("Missing expected model file: " + modelfile + ". Did you forget to train the system?")

        self.log("Loading class encoder/decoder for " + modelfile + " ...")
        self.classencoder = colibricore.ClassEncoder(modelfile + '.cls')
        self.classdecoder = colibricore.ClassDecoder(modelfile + '.cls')

        self.log("Loading model files " + modelfile + " and " + modelfile + ".3 ...")
        self.bigram_model = colibricore.UnIndexedPatternModel(modelfile)
        self.trigram_model = colibricore.UnIndexedPatternModel(modelfile + '.3')

    def prepareinput(self,paragraph,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        inputdata = []
        for word in paragraph.words():
            inputdata.append( (word.id, word.text()) )
        return inputdata

    def run(self, inputdata):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        words = [ word_text for word_id, word_text in inputdata ] #pylint: disable=unused-variable
        word_ids = [ word_id for word_id, word_text in inputdata ] #pylint: disable=unused-variable

        actions = [None] * len(words) #array of actions to be taken for each token, actions are (None,freq) for deletions or (punct,freq) for insertions

        #find possible deletions
        for i, trigram in enumerate(Windower(words,3)):
            if trigram[0] != "<begin>" and trigram[-1] != "<end>" and trigram[1] in self.PUNCTUATION and trigram[0] not in self.PUNCTUATION and trigram[-1] not in self.PUNCTUATION:
                #trigram pattern focussing on a punctuation token
                trigram_pattern = self.classencoder.buildpattern(" ".join(trigram))
                trigram_oc = self.trigram_model[trigram_pattern]
                if trigram_oc >= self.settings['deletioncutoff']:
                    continue #trigram is too frequent to be considered for deletion


                #bigram version without the punctuation token
                bigram = (trigram[0], trigram[-1])
                bigram_pattern = self.classencoder.buildpattern(" ".join(bigram))
                if bigram_pattern.unknown():
                    continue

                #get occurrences
                bigram_oc = self.bigram_model[bigram_pattern]
                if bigram_oc >= self.settings['deletionthreshold']:
                    #bigram is prevalent enough to warrant as a deletion solution
                    actions[i-2] = ('delete',trigram[1],bigram_oc)

        #find possible insertions
        for i, bigram in enumerate(Windower(words,2,None,None)):
            if bigram[0] not in self.PUNCTUATION and bigram[1] not in self.PUNCTUATION:
                bigram_pattern = self.classencoder.buildpattern(" ".join(bigram))
                bigram_oc = self.bigram_model[bigram_pattern]
                if bigram_oc >= self.settings['insertioncutoff']:
                    continue #bigram too prevalent to consider for insertion

                for punct in self.PUNCTUATION:
                    trigram = (bigram[0],punct,bigram[-1])
                    trigram_pattern = self.classencoder.buildpattern(" ".join(trigram))
                    if trigram_pattern.unknown():
                        continue

                    trigram_oc = self.trigram_model[trigram_pattern]
                    if trigram_oc >= self.settings['insertionthreshold']:
                        actions[i] = ('insert',punct, trigram_oc)

        #Consolidate all the actions through a simple survival of the fittest mechanism
        #making sure no adjacent deletions/insertion occur
        for i, (prevaction, action) in enumerate(Windower(actions,2)):
            i = i - 1
            if action is not None:
                if prevaction is not None and prevaction != "<begin>":
                    if action[2] > prevaction[2]:
                        actions[i-1] = None
                    else:
                        actions[i] = None

        #enforce final period
        if words[-1] not in self.EOSMARKERS and actions[-1] is None:
            actions[-1] = ('insert','.',1)

        return [ (word_id, (action,punct)) for word_id, (action, punct,freq) in zip(word_ids, actions)  ]


    def processoutput(self, outputdata, inputdata, unit_id,**parameters):
        queries = []
        wordstr,prevword,prevword_id, _ = inputdata
        cls, distribution = outputdata

        recase = False

        if cls[-1] == 'C':
            if wordstr[0] == wordstr[0].lower():
                if distribution[cls] >= self.settings['capitalizationthreshold']:
                    recase = True
                elif self.debug:
                    self.log(" (Capitalization threshold not reached: " + str(distribution[cls]) + ")")
            cls = cls[:-1]


        if cls == '-':
            if prevword and distribution[cls] >= self.settings['deletionthreshold'] and all( not c.isalpha() for c in  prevword ):
                if self.debug:
                    self.log(" (Redundant punctuation " + cls + " with threshold " + str(distribution[cls]) + ")")
                queries.append( self.suggestdeletion(prevword_id,(prevword in TIMBLPuncRecaseModule.EOSMARKERS), cls='redundantpunctuation') )
        elif cls and cls in distribution:
            #insertion of punctuation
            if distribution[cls] >= self.settings['insertionthreshold']:
                if all(not c.isalnum() for c in prevword):
                    #previous word is punctuation already
                    if prevword != cls:
                        self.log(" (Found punctuation confusion)")
                        queries.append( self.addsuggestions(prevword_id,cls, cls='confusion') )
                    else:
                        recase = False #no punctuation insertion? then no recasing either
                        if self.debug: self.log(" (Predicted punctuation already there, good, ignoring)")
                else:
                    if self.debug: self.log(" (Insertion " + cls + " with threshold " + str(distribution[cls]) + ")")
                    queries.append( self.suggestinsertion(unit_id, cls, (cls in TIMBLPuncRecaseModule.EOSMARKERS) ) )
            else:
                recase = False #no punctuation insertion? then no recasing either
                if self.debug: self.log(" (Insertion threshold not reached: " + str(distribution[cls]) + ")")

        if recase and wordstr[0].isalpha():
            #recase word
            t = wordstr
            if recase:
                t = t[0].upper() + t[1:]
            if self.debug:
                self.log(" (Correcting capitalization for " + wordstr + ")")
            queries.append( self.addsuggestions( unit_id, [t], cls='capitalizationerror') )

        return queries


class TIMBLPuncRecaseModule(Module):
    """This is a memory-based classification module, implemented using Timbl, that predicts where punctuation needs to be inserted, deleted, and whether a word needs to be written with an initial capital.
    NOTE: This module performs badly!!

    Settings:
    * ``leftcontext``  - Left context size (in words) for the feature vector
    * ``rightcontext`` - Right context size (in words) for the feature vector
    * ``algorithm``    - The Timbl algorithm to use (see -a parameter in timbl) (default: IGTree)
    * ``deletionthreshold`` - If no punctuation insertion is predicted and this confidence threshold is reached, then a deletion will be predicted (should be a high number), default: 0.95
    * ``insertionthreshold`` - Necessary confidence threshold to predict an insertion of punctuation (default: 0.5)

    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a classifier instance base model [``.ibase``]
    """

    UNIT = folia.Word
    UNITFILTER = nonumbers

    EOSMARKERS = ('.','?','!')
    PUNCTUATION = EOSMARKERS + (',',';',':')

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'missingpunctuation' #will be overriden later again

        super().verifysettings()

        if 'algorithm' not in self.settings:
            self.settings['algorithm'] = 1

        if 'leftcontext' not in self.settings:
            self.settings['leftcontext'] = 3

        if 'rightcontext' not in self.settings:
            self.settings['rightcontext'] = 2

        if 'deletionthreshold' not in self.settings:
            self.settings['deletionthreshold'] = 0.95

        if 'insertionthreshold' not in self.settings:
            self.settings['insertionthreshold'] = 0.5

        if 'capitalizationthreshold' not in self.settings:
            self.settings['capitalizationthreshold'] = 0.5

        if 'debug' in self.settings:
            self.debug = bool(self.settings['debug'])
        else:
            self.debug = False

        self.hapaxer = gethapaxer(self, self.settings)


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
        self.classifier = TimblClassifier(fileprefix, self.gettimbloptions())
        self.classifier.load()


    def addtraininstance(self,classifier, buffer,l,r):
        """Helper function"""
        focusword, cased, punc = buffer[l]
        cls = punc
        if cased:
            cls += 'C'
        if not cls:
            cls = '-'
        if self.hapaxer:
            features = [w for w,_,_ in buffer]
            features = [w.lower() for w in  self.hapaxer(features[:l]) + (features[l+1],) + self.hapaxer(features[l+2:])]
        else:
            features = [w.lower() for w,_,_ in buffer]
        classifier.append( tuple(features) , cls )
        return buffer[1:]

    def train(self, sourcefile, modelfile, **parameters):
        if self.hapaxer:
            self.log("Training hapaxer...")
            self.hapaxer.train()

        l = self.settings['leftcontext']
        r = self.settings['rightcontext']

        self.log("Generating training instances...")
        fileprefix = modelfile.replace(".ibase","") #has been verified earlier
        classifier = TimblClassifier(fileprefix, self.gettimbloptions())
        if sourcefile.endswith(".bz2"):
            iomodule = bz2
        elif sourcefile.endswith(".gz"):
            iomodule = gzip
        else:
            iomodule = io

        prevword = ""
        #buffer = [("<begin>",False,'')] * l
        buffer = []
        with iomodule.open(sourcefile,mode='rt',encoding='utf-8',errors='ignore') as f:
            for i, line in enumerate(f):
                if i % 100000 == 0: print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " - " + str(i),file=sys.stderr)
                words = [ w.strip() for w in line.split(' ') if w.strip() ]
                for i, word in enumerate(words):
                    if prevword in TIMBLPuncRecaseModule.PUNCTUATION:
                        punc = prevword
                    else:
                        punc = ""
                    if any(  c.isalpha() for c in word  ):
                        buffer.append( (word, word == word[0].upper() + word[1:].lower(), punc ) )
                    if len(buffer) == l + r + 1:
                        buffer = self.addtraininstance(classifier, buffer,l,r)
                    prevword = word
        #for i in range(0,r):
        #    buffer.append( ("<end>",False,'') )
        #    if len(buffer) == l + r + 1:
        #        buffer = self.addtraininstance(classifier, buffer,l,r)

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
        l = self.settings['leftcontext']
        r = self.settings['rightcontext']

        leftcontext = []
        currentword = word
        while len(leftcontext) < l:
            prevword = currentword.previous(folia.Word,None)
            if prevword:
                w = prevword.text().lower()
                if w.isalnum():
                    leftcontext.insert(0, w )
                currentword = prevword
            else:
                leftcontext.insert(0, "<begin>")

        rightcontext = []
        currentword = word
        while len(rightcontext) < r:
            nextword = currentword.next(folia.Word,None)
            if nextword:
                w = nextword.text().lower()
                if w.isalnum():
                    rightcontext.append(w )
                currentword = nextword
            else:
                rightcontext.append("<end>")

        return leftcontext + [word.text().lower()] + rightcontext





    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word) #will be reused in processoutput
        if not any( c.isalnum() for c in wordstr):
            #this is punctuation, skip
            return None
        prevword = word.previous(folia.Word,None)
        if prevword:
            prevwordstr = str(prevword)
            prevword_id = prevword.id
        else:
            prevwordstr = ""
            prevword_id = ""
        features = self.getfeatures(word)
        return wordstr, prevwordstr, prevword_id,features

    def run(self, inputdata):
        """This method gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        wordstr,prevword,prevword_id, features = inputdata
        if self.debug:
            self.log(" (Processing word " + wordstr + ", features: " + repr(features) + ")")
        if self.hapaxer: features = self.hapaxer(features)
        best,distribution,_ = self.classifier.classify(features)
        if self.debug:
            self.log(" (Best: "  + best + ")")
        return [best,distribution]

    def processoutput(self, outputdata, inputdata, unit_id,**parameters):
        queries = []
        wordstr,prevword,prevword_id, _ = inputdata
        cls, distribution = outputdata

        recase = False

        if cls[-1] == 'C':
            if wordstr[0] == wordstr[0].lower():
                if distribution[cls] >= self.settings['capitalizationthreshold']:
                    recase = True
                elif self.debug:
                    self.log(" (Capitalization threshold not reached: " + str(distribution[cls]) + ")")
            cls = cls[:-1]


        if cls == '-':
            if prevword and distribution[cls] >= self.settings['deletionthreshold'] and all( not c.isalpha() for c in  prevword ):
                if self.debug:
                    self.log(" (Redundant punctuation " + cls + " with threshold " + str(distribution[cls]) + ")")
                queries.append( self.suggestdeletion(prevword_id,(prevword in TIMBLPuncRecaseModule.EOSMARKERS), cls='redundantpunctuation') )
        elif cls and cls in distribution:
            #insertion of punctuation
            if distribution[cls] >= self.settings['insertionthreshold']:
                if all(not c.isalnum() for c in prevword):
                    #previous word is punctuation already
                    if prevword != cls:
                        self.log(" (Found punctuation confusion)")
                        queries.append( self.addsuggestions(prevword_id,cls, cls='confusion') )
                    else:
                        recase = False #no punctuation insertion? then no recasing either
                        if self.debug: self.log(" (Predicted punctuation already there, good, ignoring)")
                else:
                    if self.debug: self.log(" (Insertion " + cls + " with threshold " + str(distribution[cls]) + ")")
                    queries.append( self.suggestinsertion(unit_id, cls, (cls in TIMBLPuncRecaseModule.EOSMARKERS) ) )
            else:
                recase = False #no punctuation insertion? then no recasing either
                if self.debug: self.log(" (Insertion threshold not reached: " + str(distribution[cls]) + ")")

        if recase and wordstr[0].isalpha():
            #recase word
            t = wordstr
            if recase:
                t = t[0].upper() + t[1:]
            if self.debug:
                self.log(" (Correcting capitalization for " + wordstr + ")")
            queries.append( self.addsuggestions( unit_id, [t], cls='capitalizationerror') )

        return queries
