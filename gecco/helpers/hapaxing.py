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

import colibricore


def gethapaxer(settings):
    hapaxer = None
    if 'hapaxsource' not in self.settings:
        settings['hapaxsource'] = ""
    if 'hapaxmodel' not in self.settings:
        settings['hapaxmodel'] = ""
    if 'hapaxthreshold' not in self.settings:
        settings['hapaxthreshold'] = 2
    if 'hapaxminlength' not in self.settings:
        settings['hapaxminlength'] = 0
    if 'hapaxmaxlength' not in self.settings:
        settings['hapaxmaxlength'] = 0
    if 'hapaxplaceholder' not in self.settings:
        settings['hapaxplaceholder'] = "<hapax>"

    if settings['hapaxmodel']:
        hapaxer = Hapaxer(settings['hapaxsource'], settings['hapaxmodel'], settings['hapaxthreshold'], settings['hapaxminlength'], settings['hapaxmaxlength'], settings['hapaxplaceholder'] )

    return hapaxer

class Hapaxer:
    def __init__(self, sourcefile, modelfile, threshold, minlength=0,maxlength=0, placeholder="<hapax>"):
        self.sourcefile = sourcefile
        self.modelfile = modelfile
        self.threshold = threshold
        self.placeholder = placeholder
        self.minlength = minlength
        self.maxlength = maxlength


    def train(self):
        if self.sourcefile and not os.path.exists(self.modelfile):
            classfile = self.modelfile  +  ".cls"
            corpusfile = self.modelfile +  ".dat"

            if not os.path.exists(classfile):
                classencoder = colibricore.ClassEncoder(self.minlength,self.maxlength)
                classencoder.build(self.sourcefile)
                classencoder.save(classfile)
            else:
                classencoder = colibricore.ClassEncoder(classfile, self.minlength, self.maxlength)


            if not os.path.exists(corpusfile):
                classencoder.encodefile( sourcefile, corpusfile)

            options = colibricore.PatternModelOptions(mintokens=self.threshold,minlength=1,maxlength=1)
            model = colibricore.UnindexedPatternModel()
            model.train(corpusfile, options)
            model.save(self.modelfile)

    def load(self):
        if not os.path.exists(self.modelfile):
            raise IOError("Missing expected model file for hapaxer:" + self.modelfile)
        self.classencoder = colibricore.ClassEncoder(self.modelfile + '.cls')
        self.classdecoder = colibricore.ClassDecoder(self.modelfile + '.cls')
        self.lexicon = colibricore.UnindexedPatternModel(self.modelfile)

    def __getitem__(self, word):
        pattern = self.classencoder.buildpattern(word)
        if pattern.unknown():
            return self.placeholder

        count = self.lexicon[pattern]
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

