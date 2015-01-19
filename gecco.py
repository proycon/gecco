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

import import argparse

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
        module.parent = self

    def train(self,id=None):
        return self.modules[id]




    def run(self, foliadoc, id=None, **parameters):
        if isinstance(foliadoc, str):
            #We got a filename instead of a FoLiA document, that's okay
            ext = foliadoc.split('.')[-1].lower()
            if not ext in ('xml','folia','gz','bz2'):
                #Preprocessing - Tokenize input text (plaintext) and produce FoLiA output
                self.log("Starting Tokeniser")

                inputtextfile = foliadoc

                if ext == 'txt':
                    ouputtextfile = '.'.join(inputtextfile.split('.')[:-1]) + '.folia.xml'
                else:
                    outputtextfile = inputtextfile + '.folia.xml'

                tokenizer = Tokenizer(self.settings['ucto'],xmloutput=True)
                tokenizer.process(inputtextfile, outputtextfile)

                foliadoc = outputtextfile

                self.log("Tokeniser finished")

            #good, load
            self.log("Reading FoLiA document")
            foliadoc = folia.Document(file=foliadoc)


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
                if module.local:
                    module.run(foliadoc)
                else:
                    module.client(foliadoc)


        #Store FoLiA document
        if save:
            if not standalone and statusfile: clam.common.status.write(statusfile, "Saving document",99)
            errout( "Saving document")
            doc.save()

    def main(self):
        #command line tool
        parser = argparse.ArgumentParser(description="", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        #parser.add_argument('--run',dest='settype',help="", action='store_const',const='somevalue')
        #parser.add_argument('-f','--dataset', type=str,help="", action='store',default="",required=False)
        #parser.add_argument('-i','--number',dest="num", type=int,help="", action='store',default="",required=False)
        #parser.add_argument('bar', nargs='+', help='bar help')
        args = parser.parse_args()
        #args.storeconst, args.dataset, args.num, args.bar
        pass


class Module:
    def __init__(self,id, **settings):
        self.id = id
        self.settings = settings
        self.verifysettings()


    def verifysettings():
        self.local = 'servers' in self.settings
        if 'source' in self.settings:
            is isinstance(self.settings['source'],str):
                self.sources = [ self.settings['source'] ]
            else:
                self.sources = self.settings['source']
        elif 'sources' in self.settings:
            self.sources = self.settings['sources']

        if 'model' in self.settings:
            is isinstance(self.settings['model'],str):
                self.models = [ self.settings['model'] ]
            else:
                self.models = self.settings['model']
        elif 'models' in self.settings:
            self.models = self.settings['models']


    #callbacks:

    def train(self, **parameters):
        """This method gets invoked by the Corrector to train the model. Override it in your own model, use the input files in self.sources and for each entry create the corresponding file in self.models """

    def run(self, foliadoc, **parameters):
        """This method gets invoked by the Corrector when it runs locally"""

    def client(self, foliadoc, host, port, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the host and port are passed"""

    def server(self, port):
        """This methods gets called by the Corrector to start the module's server"""








