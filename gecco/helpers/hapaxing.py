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
            self.log("Preparing to generate hapaxer")
            classfile = self.modelfile  +  ".cls"
            corpusfile = self.modelfile +  ".dat"

            if not os.path.exists(classfile):
                self.log("Building class file")
                classencoder = colibricore.ClassEncoder(self.minlength,self.maxlength)
                classencoder.build(self.sourcefile)
                classencoder.save(classfile)
            else:
                classencoder = colibricore.ClassEncoder(classfile, self.minlength, self.maxlength)


            if not os.path.exists(corpusfile):
                self.log("Encoding corpus")
                classencoder.encodefile( sourcefile, corpusfile)

            self.log("Generating frequency list")
            options = colibricore.PatternModelOptions(mintokens=self.threshold,minlength=1,maxlength=1)
            model = colibricore.UnindexedPatternModel()
            model.train(corpusfile, options)
            model.save(self.modelfile)

    def load(self):
        if not os.path.exists(self.modelfile):
            raise IOError("Missing expected model file for hapaxer:" + self.modelfile)
        self.log("Loading colibri model file " + self.modelfile)
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


