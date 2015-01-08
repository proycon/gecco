#!/usr/bin/env python3
#========================================================================
#GECCO - Generic Enviroment for Context-Aware Correction of Orthography
# Maarten van Gompel, Wessel Stoop, Antal van den Bosch
# Centre for Language and Speech Technology
# Radboud University Nijmegen
#
# Licensed under GPLv3
#=======================================================================


from collections import OrderedDict
from threading import Thread, Queue, Lock
from pynlpl.formats import folia
from ucto import Tokenizer


UCTOSEARCHDIRS = ('/usr/local/etc/ucto','/etc/ucto/','.')


def processor(queue, foliadoc, parameters):
    while True:
        job = queue.get()
        job.run(foliadoc, **parameters)
        queue.task_done()

class Corrector:
    def __init__(self, id, root=".", **settings):
        self.id = id
        self.root = root
        self.settings = settings
        self.verifysettings()
        self.tokenizer = Tokenizer(self.settings['ucto'])
        self.modules = OrderedDict()

    def verifysettings():
        if not 'ucto' in self.settings:
            if 'language' in self.settings:
                for dir in UCTOSEARCHDIRS:
                    if os.path.exists(dir + "/tokconfig-" + self.settings['language']):
                        self.settings['ucto'] = dir + '/tokconfig-' + self.settings['language']
            if not 'ucto' in self.settings:
                for dir in UCTOSEARCHDIRS:
                    if os.path.exists(dir + "/tokconfig-generic"):
                        self.settings['ucto'] = dir + '/tokconfig-generic'
                if not 'ucto' in self.settings:
                    raise Exception("Ucto configuration file not specified and no default found (use setting ucto=)")
        elif not os.path.exists(self.settings['ucto']):
            raise Exception("Specified ucto configuration file not found")


        if not 'logfunction' in self.settings:
            self.settings['logfunction'] = lambda x: print(x,file=sys.stderr)
        self.log = self.settings['logfunction']


        if not 'threads' in self.settings:
            self.settings['threads'] = 1



    def __len__(self):
        return len(self.modules)

    def _getitem__(self, id):
        return self.modules[id]

    def __iter__(self):
        for module in self.modules.values():
            yield module

    def append(self, id, module):
        assert isinstance(module, Module)
        self.modules[id] = module

    def train(self,id=None):
        return self.modules[id]

    def run(self, foliadoc, id=None, **parameters):
        if isinstance(foliadoc, str):
            #We got a filename instead of a FoLiA document
            ext = foliadoc.split('.')[-1].lower()
            if ext in ('xml','folia','gz','bz2'):
                #good, load
                self.log("Reading FoLiA document")
                foliadoc = folia.Document(file=foliadoc)
            else:
                #Preprocessing - Tokenize input text (plaintext) and produce FoLiA output
                self.log("Starting Tokeniser")

                #TODO: Upgrade python-ucto
                #os.system(self.settings.ucto + ' -L nl -x ' + id + ' ' + inputfile + ' > ' + outputdir + id + '.xml')

                self.log("Tokeniser finished")


        queue = Queue()

        lock = Lock()
        for i in range(self.settings['threads']):
            thread = Thread(target=processor,args=[queue, lock, foliadoc, parameters])
            thread.setDaemon(True)
            thread.start()

        for module in self:
            queue.put(module)

        queue.join()
        #all modules done

        #process results and integrate into FoLiA
        for module in self:
            if id is None or module.id == id:
                module.run(foliadoc)

        #Store FoLiA document
        if save:
            if not standalone and statusfile: clam.common.status.write(statusfile, "Saving document",99)
            errout( "Saving document")
            doc.save()


class Module:
    def __init__(self,id, **settings):
        self.id = id
        self.settings = settings

    def train(self):
        pass

    def test(self):
        pass

    def load(self):
        pass

    def save(self):
        pass

    def run(self, foliadoc, **parameters)






