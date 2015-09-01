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

import colibricore #pylint: disable=import-error
import os.path

from gecco.helpers.common import stripsourceextensions

def gethapaxer(module, settings):
    hapaxer = None
    if 'hapaxsource' not in settings:
        hapaxsource = ""
    else:
        hapaxsource = module.getfilename(settings['hapaxsource'])
    if 'hapaxmodel' not in settings:
        hapaxmodel = ""
    else:
        hapaxmodel = module.getfilename(settings['hapaxmodel'])
    if 'hapaxthreshold' not in settings:
        settings['hapaxthreshold'] = 2
    if 'hapaxminlength' not in settings:
        settings['hapaxminlength'] = 0
    if 'hapaxmaxlength' not in settings:
        settings['hapaxmaxlength'] = 0
    if 'hapaxplaceholder' not in settings:
        settings['hapaxplaceholder'] = "<hapax>"


    if hapaxmodel:
        hapaxer = Hapaxer(hapaxsource, hapaxmodel, settings['hapaxthreshold'], settings['hapaxminlength'], settings['hapaxmaxlength'], settings['hapaxplaceholder'] )

    return hapaxer

class Hapaxer:
    """The Hapaxer checks words against a lexicon and replaces low-frequency words with a dummy placeholder.
    
    Settings:
        * ``hapaxsource``        - The source corpus from which the hapax lexicon is derived
        * ``hapaxmodel``         - The hapax model file (mandatory!)
        * ``hapaxthreshold``     - The threshold below which words are considered hapaxes (default: 2)
        * ``hapaxplaceholder``   - The placeholder symbol for all hapaxes (default: <hapax>)
        * ``hapaxminlength``     - The minimum length, in characters, of allowed (i.e non-hapax) words (default: 0, unlimited)
        * ``hapaxmaxlength``     - The maximum length, in characters, of allowed (i.e non-hapax) words (default: 0, unlimited)

    """

    def __init__(self, sourcefile, modelfile, threshold, minlength=0,maxlength=0, placeholder="<hapax>"):
        self.sourcefile = sourcefile
        self.modelfile = modelfile
        self.threshold = threshold
        self.placeholder = placeholder
        self.minlength = minlength
        self.maxlength = maxlength

        self.classencoder = None
        self.lexicon = None


    def train(self):
        if self.sourcefile and not os.path.exists(self.modelfile):
            classfile = stripsourceextensions(self.sourcefile) +  ".cls"
            corpusfile = stripsourceextensions(self.sourcefile) +  ".dat"

            if not os.path.exists(classfile):
                self.classencoder = colibricore.ClassEncoder(self.minlength,self.maxlength)
                self.classencoder.build(self.sourcefile)
                self.classencoder.save(classfile)
            else:
                self.classencoder = colibricore.ClassEncoder(classfile, self.minlength, self.maxlength)

            if not os.path.exists(self.modelfile + '.cls'):
                #make symlink to class file, using model name instead of source name
                os.symlink(classfile, self.modelfile + '.cls')

            if not os.path.exists(corpusfile):
                self.classencoder.encodefile( self.sourcefile, corpusfile)

            options = colibricore.PatternModelOptions(mintokens=self.threshold,minlength=1,maxlength=1)
            self.lexicon = colibricore.UnindexedPatternModel()
            self.lexicon.train(corpusfile, options)
            self.lexicon.write(self.modelfile)


    def load(self):
        if not os.path.exists(self.modelfile):
            raise IOError("Missing expected model file for hapaxer:" + self.modelfile)
        self.classencoder = colibricore.ClassEncoder(self.modelfile + '.cls')
        #self.classdecoder = colibricore.ClassDecoder(self.modelfile + '.cls')
        self.lexicon = colibricore.UnindexedPatternModel(self.modelfile)

    def __getitem__(self, word):
        if word in ('<begin>','<end>'): #EOS markers are never hapaxes
            return word
        if self.lexicon is None: self.load()
        pattern = self.classencoder.buildpattern(word)
        if pattern.unknown():
            return self.placeholder

        try:
            count = self.lexicon[pattern]
        except KeyError:
            return self.placeholder
        if count < self.threshold:
            return self.placeholder
        else:
            return word

    def __exists__(self, word):
        """Checks if the word is in the hapaxer, returns True when a word does NOT exist in the lexicon and is thus a hapax"""

        pattern = self.classencoder.buildpattern(word)
        if pattern.unknown():
            return True

        return self.lexicon[pattern] < self.threshold

    def __call__(self, tokens):
        return tuple( self[x] for x in tokens )

