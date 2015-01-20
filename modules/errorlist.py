from pynlpl.formats import folia
from gecco import gecco

class WordErrorListModule(gecco.Module):
    UNIT = folia.Word

    def verifysettings(self):
        super().verifysettings()

        if 'delimiter' not in self.settings:
            self.settings['delimiter'] = "\t"
        if 'reversedformat' not in self.settings: #reverse format has (correct,wrong) pairs rather than (wrong,correct) pairs
            self.settings['reversedformat'] = False

    def load(self):
        self.errorlist = {}

        if not self.models:
            raise Exception("Specify one or more models to load!")

        for modelfile in self.models:
            if not os.path.exists(modelfile):
                raise IOError("Missing expected model file:" + modelfile)
            self.log("Loading model file" + modelfile)
            with open(modelfile,'r',encoding='utf-8') as f:
                for line in f:
                    if line:
                        fields = line.split(self.settings['delimiter'])
                        if  len(fields) != 2:
                            raise Exception("Syntax error in " + modelfile + ", expected two items, got " + str(len(fields)))

                        if self.settings['reversedformat']:
                            correct, wrong = fields
                        else:
                            wrong, correct = fields

                        if wrong in self.errorlist:
                            current = self.errorlist[wrong]
                            if isinstance(current, tuple):
                                self.errorlist[wrong] = current + (correct,)
                            else:
                                self.errorlist[wrong] = (current, correct)
                        else:
                            self.errorlist[wrong] = correct

    def run(self, word, lock, **parameters):
        wordstr = str(word)
        if wordstr in self.errorlist:
            suggestions = self.errorlist[wordstr]
            self.process(word, suggestions)


    def client(self, word, lock, client, **parameters):
        wordstr = str(word)
        response = client.communicate(wordstr)
        if response != wordstr: #server will echo back the same thing if it's not in error list
            suggestions = response.split("\t")
            self.process(word, suggestions)


