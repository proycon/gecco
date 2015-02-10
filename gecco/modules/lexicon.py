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
from collections import OrderedDict
from pynlpl.formats import folia
from pynlpl.statistics import levenshtein
from gecco.gecco import Module
from gecco.helpers.caching import getcache
import colibricore
import aspell

class LexiconModule(Module):
    UNIT = folia.Word

    def verifysettings(self):
        if 'class' not in self.settings:
            self.settings['class'] = 'nonworderror'

        super().verifysettings()

        if 'delimiter' not in self.settings:
            self.settings['delimiter'] = "\t"
        elif self.settings['delimiter'].lower() == 'space':
            self.settings['delimiter'] = " "
        elif self.settings['delimiter'].lower() == 'tab':
            self.settings['delimiter'] = "\t"
        elif self.settings['delimiter'].lower() == 'comma':
            self.settings['delimiter'] = ","
        if 'reversedformat' not in self.settings: #reverse format has (word,freq) pairs rather than (freq,word) pairs
            self.settings['reversedformat'] = False

        if 'maxdistance' not in self.settings:
            self.settings['maxdistance'] = 2
        if 'maxlength' not in self.settings:
            self.settings['maxlength'] = 15 #longer words will be ignored
        if 'minlength' not in self.settings:
            self.settings['minlength'] = 5 #shorter word will be ignored
        if 'minfreqthreshold' not in self.settings:
            self.settings['minfreqthreshold'] = 10000
        if 'maxnrclosest' not in self.settings:
            self.settings['maxnrclosest'] = 5

        self.cache = getcache(self.settings, 1000) #2nd arg is default cache size

        if 'suffixes' not in self.settings:
            self.settings['suffixes'] = []
        if 'prefixes' not in self.settings:
            self.settings['prefixes'] = []

        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 20


    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate lexicon")
        classfile = modelfile  +  ".cls"
        corpusfile = modelfile +  ".dat"

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

        self.savemodel(model, modelfile) #in separate function so it can be overloaded


    def savemodel(self, model, modelfile):
        self.log("Saving model")
        classfile = modelfile  +  ".cls"
        classdecoder = colibri.ClassDecoder(classfile)
        with open(modelfile,'w',encoding='utf-8') as f:
            for pattern, occurrencecount in model.items():
                if self.settings['reversedformat']:
                    f.write(pattern.tostring(classdecoder) + self.settings['delimiter'] + str(occurrencecount) + "\n")
                else:
                    f.write(str(occurrencecount) + self.settings['delimiter'] + pattern.tostring(classdecoder) + "\n")

    def load(self):
        """Load the requested modules from self.models"""
        self.lexicon = {}

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
                            freq, word = fields
                        else:
                            word, freq = fields
                        freq = int(freq)

                        if freq > self.settings['minfreqthreshold']:
                            self.lexicon[word] = freq

    def __exists__(self, word):
        return word in self.lexicon

    def __iter__(self):
        for key, freq in self.lexicon.items():
            yield key, freq

    def findclosest(self, word):
        #first try the cache
        if self.cache:
            try:
                return self.cache[word]
            except KeyError:
                pass

        l = len(word)
        if l < self.settings['minlength'] or l > self.settings['maxlength']:
            #word too long or too short, ignore
            return False
        elif word in self:
            #word is in lexicon, no need to find suggestions
            return False
        else:
            #word is not in lexicon

            #but first try to strip known suffixes and prefixes and try again
            for suffix in self.settings['suffixes']:
                if word.endswith(suffix):
                    if word[:-len(suffix)] in self:
                        return False
            for prefix in self.settings['prefixes']:
                if word.beginswith(prefix):
                    if word[len(prefix):] in self:
                        return False

            #ok, not found, let's find closest matches by levenshtein distance

            results = []
            for key, freq in self:
                ld = levenshtein(word, key, self.settings['maxdistance'])
                if ld <= self.settings['maxdistance']:
                    self.results.append( (key, ld) )

            results.sort(key=lambda x: x[1])[:self.settings['maxnrclosest']]
            self.cache.append(word, results)
            return results



    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordstr = str(word)
        results = self.findclosest(wordstr)
        if results:
            self.addwordsuggestions(lock, word, [ result for result,distance in results ] )

    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        wordstr = str(word)
        results = json.loads(client.communicate('!' + wordstr)) #! is the command to return closest suggestions, ? merely return a boolean whether the word is in lexicon or not
        if results:
            self.addwordsuggestions(lock, word, [ result for result,distance in results ] )

    def server_handler(self, input):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        if input:
            command = input[0]
            word = input[1:]
            if command == '!': #find closest suggestions
                return json.dumps(self.findclosest(word))
            elif command == '?':
                try:
                    return str(self[word])
                except KeyError:
                    return "0"
        return "INVALID INPUT"



class ColibriLexiconModule(LexiconModule):

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
        self.lexicon = colibricore.UnindexedPatternModel(modelfile)

    def __exists__(self, word):
        pattern = self.classencoder.buildpattern(word)
        if pattern.unknown():
            return False
        else:
            return pattern in self.lexicon

    def __iter__(self):
        for pattern, freq in self.lexicon.items():
            yield (pattern.tostring(self.classdecoder), freq)

    def savemodel(self, model, modelfile): #will be called by train()
        self.log("Saving model")
        model.write(modelfile)


class AspellModule(Module):
    UNIT = folia.Word


    def verifysettings(self):
        super().verifysettings()

        if 'language' not in self.settings:
            raise Exception("Mandatory argument to aspell module missing: language")

    def load(self):
        self.speller = aspell.Speller('lang',self.settings['language'])
        self.encoding = self.speller.ConfigKeys()['encoding'][2]

    def run(self, word, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally. word is a folia.Word instance"""
        wordenc = str(word).encode(self.encoding)
        suggestions = [ str(w, self.encoding) for w in self.speller.suggest(wordenc) ]
        if suggestions:
            self.addwordsuggestions(lock, word, suggestions )

    def runclient(self, client, word, lock, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). word is a folia.Word instance"""
        suggestions= json.loads(client.communicate(str(word)))
        if suggestions:
            self.addwordsuggestions(lock, word, suggestions )

    def server_handler(self, word):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        wordenc = word.encode(self.encoding)
        suggestions = [ str(w, self.encoding) for w in self.speller.suggest(wordenc) ]
        return json.dumps(suggestions)


