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

#pylint: disable=too-many-nested-blocks,attribute-defined-outside-init

import os
from pynlpl.formats import folia
#from pynlpl.statistics import levenshtein
import Levenshtein #pylint: disable=import-error
from gecco.gecco import Module
from gecco.helpers.caching import getcache
from gecco.helpers.filters import hasalpha
from gecco.helpers.common import stripsourceextensions
import colibricore #pylint: disable=import-error
import aspell #pylint: disable=import-error
import hunspell #pylint: disable=import-error


class LexiconModule(Module):
    """Lexicon Module. Checks an input word against a lexicon and returns suggestions with a certain Levensthein distance. The lexicon may be automatically compiled from a corpus.

    Settings:
    * ``freqthreshold`` - All words occuring at least this many times in the source corpus will be included in the lexicon (default: 100), setting this value too low decreases performance and consumes a lot of memory.
    * ``maxdistance``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions)
    * ``maxlength``  - Maximum length of words in characters, longer words are ignored (default: 25)
    * ``minlength``  - Minimum length of words in characters, shorter words are ignored (default: 5)
    * ``shortlength`` - Maximum length of words, in characters, that are considered short. Short words are measured against maxdistance_short rather than maxdistance  (default: 5)
    * ``maxdistance_short``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions), this threshold applies to short words only (use shortlength to define what a short word is)
    * ``maxnrclosest`` -  Limit the returned suggestions to this many items (default: 5)
    * ``freqfactor``   - If a word is correct according to the lexicon, only return suggestions that are more frequent (according to the source corpus) by this factor (default: 10000)

    * ``delimiter``    - The delimiter between the frequency and the word in the model file, may be 'space', 'tab' (default), 'comma'.
    * ``reversed``     - Set to true if the model has word,freq pairs rather than freq,word pairs (default: False)
    * ``ordered``      - Indicates that the model file is ordered by frequency (descending) (default: True) -  Not using ordering decreases performance!

    * ``suffixes``     - A list of suffixes that will be stripped from a word in case of a mismatch, after which the remainder is rematched against the lexicon
    * ``prefixes``     - A list of prefixes that will be stripped from a word in case of a mismatch, after which the remainder is rematched against the lexicon

    * ``class``        - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: contexterror)

    Sources and models:
    * a plain-text corpus (tokenized)  [``.txt``]     ->    a lexicon [``.txt``]
    """
    UNIT = folia.Word
    UNITFILTER = hasalpha

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

        if 'ordered ' not in self.settings:
            self.settings['ordered'] = True #Model file is ordered in descending frequency


        if 'freqthreshold' not in self.settings:
            self.settings['freqthreshold'] = 100
        if 'maxdistance' not in self.settings:
            self.settings['maxdistance'] = 2
        if 'maxdistance_short' not in self.settings:
            self.settings['maxdistance_short'] = 1
        if 'maxlength' not in self.settings:
            self.settings['maxlength'] = 25 #longer words will be ignored
        if 'minlength' not in self.settings:
            self.settings['minlength'] = 5 #shorter word will be ignored
        if 'shortlength' not in self.settings:
            self.settings['shortlength'] = self.settings['minlength']
        if 'minfreqthreshold' not in self.settings:
            self.settings['minfreqthreshold'] = 10000
        if 'freqfactor' not in self.settings:
            self.settings['freqfactor'] = 10000
        if 'maxnrclosest' not in self.settings:
            self.settings['maxnrclosest'] = 5

        self.cache = getcache(self.settings, 1000) #2nd arg is default cache size

        if 'suffixes' not in self.settings:
            self.settings['suffixes'] = []
        if 'prefixes' not in self.settings:
            self.settings['prefixes'] = []



    def train(self, sourcefile, modelfile, **parameters):
        self.log("Preparing to generate lexicon")
        classfile = stripsourceextensions(sourcefile) +  ".cls"
        corpusfile = stripsourceextensions(sourcefile) +  ".dat"

        if not os.path.exists(classfile):
            self.log("Building class file")
            classencoder = colibricore.ClassEncoder("", self.settings['minlength'], self.settings['maxlength']) #character length constraints
            classencoder.build(sourcefile)
            classencoder.save(classfile)
        else:
            classencoder = colibricore.ClassEncoder(classfile, self.settings['minlength'], self.settings['maxlength'])

        if not os.path.exists(modelfile+'.cls'):
            #make symlink to class file, using model name instead of source name
            os.symlink(classfile, modelfile + '.cls')

        if not os.path.exists(corpusfile):
            self.log("Encoding corpus")
            classencoder.encodefile( sourcefile, corpusfile)

        if not os.path.exists(modelfile+'.cls'):
            #make symlink to class file, using model name instead of source name
            os.symlink(classfile, modelfile + '.cls')

        self.log("Generating frequency list")
        options = colibricore.PatternModelOptions(mintokens=self.settings['freqthreshold'],minlength=1,maxlength=1) #unigrams only
        model = colibricore.UnindexedPatternModel()
        model.train(corpusfile, options)

        self.savemodel(model, modelfile, classfile) #in separate function so it can be overloaded


    def savemodel(self, model, modelfile, classfile):
        self.log("Saving model")
        classdecoder = colibricore.ClassDecoder(classfile)
        with open(modelfile,'w',encoding='utf-8') as f:
            if self.settings['ordered']:
                items = sorted(model.items(), key=lambda x: -1 * x[1])
            else:
                items = model.items()
            for pattern, occurrencecount in items:
                if self.settings['reversedformat']:
                    f.write(str(occurrencecount) + self.settings['delimiter'] + pattern.tostring(classdecoder) + "\n")
                else:
                    f.write(pattern.tostring(classdecoder) + self.settings['delimiter'] + str(occurrencecount) + "\n")

    def load(self):
        """Load the requested modules from self.models"""
        self.lexicon = {} #pylint: disable=attribute-defined-outside-init

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

    def filter(self, freqthreshold):
        ordered = self.settings['ordered']
        minfreqthreshold = self.settings['minfreqthreshold']
        for key, freq in self.lexicon.items():
            if ordered and (freq < freqthreshold or freq < minfreqthreshold):
                break
            yield key, freq


    def __getitem__(self, key):
        try:
            return self.lexicon[key]
        except KeyError:
            return 0

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
        else:
            freq = self[word]

            #but first try to strip known suffixes and prefixes and try again
            for suffix in self.settings['suffixes']:
                if word.endswith(suffix):
                    if word[:-len(suffix)] in self:
                        freq = max(self[word[:-len(suffix)]], freq)
            for prefix in self.settings['prefixes']:
                if word.beginswith(prefix):
                    if word[len(prefix):] in self:
                        freq = max(self[word[len(prefix):]], freq)

            #find closest matches *above threshold* by levenshtein distance

            results = []
            isshort = (len(word) <= self.settings['shortlength'])
            for key, freq in self.filter(freq*self.settings['freqfactor']):
                #ld = levenshtein(word, key, self.settings['maxdistance'])
                if isshort:
                    if abs(l - len(key)) <= self.settings['maxdistance_short']:
                        ld = Levenshtein.distance(word,key)
                        if ld <= self.settings['maxdistance_short']:
                            results.append( (key, ld) )
                else:
                    if abs(l - len(key)) <= self.settings['maxdistance']:
                        ld = Levenshtein.distance(word,key)
                        if ld <= self.settings['maxdistance']:
                            results.append( (key, ld) )

            results.sort(key=lambda x: x[1])
            results = results[:self.settings['maxnrclosest']]
            self.cache.append(word, results)
            return results


    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        return '!' + str(word) #! is the command to return closest suggestions if the word is not in the lexicon, ? merely return a boolean whether the word is in lexicon or not


    def processoutput(self, output,inputdata, unit_id,**parameters):
        return self.addsuggestions(unit_id, [ result for result,distance in output ] )

    def run(self, inputdata):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        if inputdata:
            command = inputdata[0]
            word = inputdata[1:]
            if command == '!': #find closest suggestions
                return self.findclosest(word)
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

    def __getitem__(self, key):
        pattern = self.classencoder.buildpattern(key)
        return self.lexicon.occurrencecount(pattern)

    def savemodel(self, model, modelfile, classfile): #will be called by train()
        self.log("Saving model")
        model.write(modelfile)


class ExternalSpellModule(Module):

    UNIT = folia.Word
    UNITFILTER = hasalpha

    def verifysettings(self):
        super().verifysettings()


        if 'class' not in self.settings:
            self.settings['class'] = 'nonworderror'

        if 'runonclass' not in self.settings:
            self.settings['runonclass'] = 'runonerror'
        if 'runon' not in self.settings:
            self.settings['runon'] = True

        if 'maxdistance' not in self.settings:
            self.settings['maxdistance'] = 2
        if 'maxdistance_short' not in self.settings:
            self.settings['maxdistance_short'] = 1
        if 'maxlength' not in self.settings:
            self.settings['maxlength'] = 25 #longer words will be ignored
        if 'minlength' not in self.settings:
            self.settings['minlength'] = 5 #shorter word will be ignored
        if 'shortlength' not in self.settings:
            self.settings['shortlength'] = self.settings['minlength']
        if 'maxnrclosest' not in self.settings:
            self.settings['maxnrclosest'] = 5


        if 'suffixes' not in self.settings:
            self.settings['suffixes'] = []
        if 'prefixes' not in self.settings:
            self.settings['prefixes'] = []

        self.cache = getcache(self.settings, 1000) #2nd arg is default cache size

    def prepareinput(self,word,**parameters):
        """Takes the specified FoLiA unit for the module, and returns a string that can be passed to process()"""
        wordstr = str(word)
        l = len(wordstr)
        if l < self.settings['minlength'] or l > self.settings['maxlength']:
            return None
        else:
            return wordstr

    def processoutput(self, output, inputdata, unit_id,**parameters):
        queries = []
        if output:
            queries.append( self.addsuggestions(unit_id, [ (word,confidence) for word,confidence in output if ' ' not in word]) )
            if self.settings['runon']:
                runonsuggestions = [ (word.split(' '),confidence) for word,confidence in output if ' ' in  word ]
                if runonsuggestions:
                    cls = self.settings['class'] #bit of an ugly cheat since we don't really support dual classes
                    self.settings['class'] =self.settings['runonclass']
                    queries.append( self.splitcorrection(unit_id,runonsuggestions) )
                    self.settings['class'] = cls
            return queries


    def run(self, word):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        if self.cache:
            try:
                return self.cache[word]
            except KeyError:
                pass
        suggestions = self[word]
        if word not in suggestions:
            #try to strip known suffixes and prefixes and try again
            for suffix in self.settings['suffixes']:
                if word.endswith(suffix):
                    word2 = word[:-len(suffix)]
                    suggestions2 = self[word2]
                    if word2 in suggestions2:
                        self.cache.append(word, [])
                        return []
            for prefix in self.settings['prefixes']:
                if word.beginswith(prefix):
                    word2 = word[len(prefix):]
                    suggestions2 = self[word2]
                    if word2 in suggestions2:
                        self.cache.append(word, [])
                        return []
            return self.findclosest(word,suggestions)
        else:
            self.cache.append(word, [])
            return []


    def findclosest(self,word, suggestions):
        #find closest matches *above threshold* by levenshtein distance

        results = []
        l = len(word)
        isshort = (len(word) <= self.settings['shortlength'])
        for sug in suggestions:
            #ld = levenshtein(word, key, self.settings['maxdistance'])
            if isshort:
                if abs(l - len(sug)) <= self.settings['maxdistance_short']:
                    ld = Levenshtein.distance(word,sug)
                    if ld <= self.settings['maxdistance_short']:
                        results.append( (sug, ld) )
            else:
                if abs(l - len(sug)) <= self.settings['maxdistance']:
                    ld = Levenshtein.distance(word,sug)
                    if ld <= self.settings['maxdistance']:
                        results.append( (sug, ld) )

        results.sort(key=lambda x: x[1])
        results = results[:self.settings['maxnrclosest']]
        if self.cache:
            self.cache.append(word, results)
        return results

class AspellModule(ExternalSpellModule):
    """Looks up the word in an Aspell lexicon, and returns suggestions

    Settings:
    * ``language``      - The language code (see http://aspell.net/man-html/Supported.html)
    * ``class``         - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: nonworderror)
    * ``maxdistance``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions)
    * ``maxlength``  - Maximum length of words in characters, longer words are ignored (default: 25)
    * ``minlength``  - Minimum length of words in characters, shorter words are ignored (default: 5)
    * ``shortlength`` - Maximum length of words, in characters, that are considered short. Short words are measured against maxdistance_short rather than maxdistance  (default: 5)
    * ``maxdistance_short``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions), this threshold applies to short words only (use shortlength to define what a short word is)
    * ``maxnrclosest`` -  Limit the returned suggestions to this many items (default: 5)
    * ``suffixes``     - A list of suffixes that will be stripped from a word in case of a mismatch, after which the remainder is rematched against the lexicon
    * ``prefixes``     - A list of prefixes that will be stripped from a word in case of a mismatch, after which the remainder is rematched against the lexicon
    """
    UNIT = folia.Word
    UNITFILTER = hasalpha

    def verifysettings(self):
        super().verifysettings()
        if 'language' not in self.settings:
            raise Exception("Mandatory argument to spell module missing: language")

    def load(self):
        self.log("Loading aspell dictionary")
        self.speller = aspell.Speller('lang',self.settings['language'])
        self.encoding = self.speller.ConfigKeys()['encoding'][1]
        self.log( "Dictionary encoding: " + self.encoding)

    def __getitem__(self, word):
        wordenc = word.encode(self.encoding)
        return list(self.speller.suggest(wordenc))


class HunspellModule(ExternalSpellModule):
    """Looks up the word in a HunSpell lexicon, and returns suggestions

    Settings:
    * ``path``          - Path to hunspel (defaults to: /usr/share/hunspell/)
    * ``language``      - The language (follows locale syntax, i.e. en_GB for British English)
    * ``class``         - Errors found by this module will be assigned the specified class in the resulting FoLiA output (default: nonworderror)
    * ``runon``         - Boolean, handle runons as well? (default: True)
    * ``runonclass``    - Runon errors found by this module will be assigned the specified class in the resulting FoLiA output (default: runonerror)
    * ``maxdistance``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions)
    * ``maxlength``  - Maximum length of words in characters, longer words are ignored (default: 25)
    * ``minlength``  - Minimum length of words in characters, shorter words are ignored (default: 5)
    * ``shortlength`` - Maximum length of words, in characters, that are considered short. Short words are measured against maxdistance_short rather than maxdistance  (default: 5)
    * ``maxdistance_short``  - Maximum Levenshtein distance between a word and its correction (larger distances are pruned from suggestions), this threshold applies to short words only (use shortlength to define what a short word is)
    * ``maxnrclosest`` -  Limit the returned suggestions to this many items (default: 5)
    * ``suffixes``     - A list of suffixes that will be stripped from a word in case of a mismatch, after which the remainder is rematched against the lexicon
    * ``prefixes``     - A list of prefixes that will be stripped from a word in case of a mismatch, after which the remainder is rematched against the lexicon
    """

    UNIT = folia.Word
    UNITFILTER = hasalpha

    def verifysettings(self):
        super().verifysettings()

        if 'language' not in self.settings:
            raise Exception("Mandatory argument to hunspell module missing: language")

        if 'path' not in self.settings:
            self.settings['path'] = '/usr/share/hunspell'

    def load(self):
        self.log("Loading aspell dictionary")
        self.speller = hunspell.HunSpell(self.settings['path'] + '/' + self.settings['language'] + '.dic', self.settings['path'] + '/' + self.settings['language'] + '.aff' )

    def __getitem__(self, word):
        if self.speller.spell(word):
            return [word]
        else:
            return [ str(w,'utf-8') for w in self.speller.suggest(word) ]
