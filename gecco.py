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

import argparse

UCTOSEARCHDIRS = ('/usr/local/etc/ucto','/etc/ucto/','.')


def processor(queue, lock, data, parameters):
    while True:
        module = queue.get()
        queue.task_done()


class ProcessorThread(Thread):
    def __init__(self, q, lock, loadbalancemaster, **parameters):
        self.q = q
        self.lock = lock
        self.abort = False
        self.loadbalancemaster = loadbalancemaster
        self.parameters = parameters

    def run(self):
        while not self.abort:
            if not q.empty():
                module, data = q.get() #data is an instance of module.UNIT
                if module.local:
                    module.run(data, lock, **self.parameters)
                else:
                    host, port = module.findserver(self.loadbalancemaster)
                    module.client(data, lock, host, port, **parameters)

    def abort(self):
        self.abort = True






class Corrector:
    def __init__(self, id, root=".", **settings):
        self.id = id
        self.root = root
        self.settings = settings
        self.verifysettings()
        self.tokenizer = Tokenizer(self.settings['ucto'])
        self.modules = OrderedDict()

        #Gather servers
        self.servers = set()
        for module in self:
            if not module.local:
                for host, port in module.settings['servers']:
                    self.servers.add( (host,port) )

        self.loadbalancemaster = LoadBalanceMaster(self.servers)

        self.units = set( [m.server for m in self] )

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
            self.settings['logfunction'] = lambda x: print("[" + self.__class__.__name__ + "] " + x,file=sys.stderr)
        self.log = self.settings['logfunction']


        if not 'threads' in self.settings:
            self.settings['threads'] = 1

        if not 'minpollinterval' in self.settings:
            self.settings['minpollinterval'] = 30 #30 sec



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


        self.log("Initialising modules on document") #not parellel, acts on same document anyway, should be very quick
        for module in self:
            module.init(foliadoc)

        self.log("Initialising threads")


        lock = Lock()
        threads = []
        for i in range(self.settings['threads']):
            thread = ProcessorThread(queue, lock, self.loadbalancemaster, **parameters)
            thread.setDaemon(True)
            thread.start()
            threads.append(thread)


        queue = Queue() #data in queue takes the form (module, data), where data is an instance of module.UNIT (a folia document or element)

        if folia.Document in units:
            self.log("\tQueuing modules handling " + str(type(folia.Document)))

            for module in self:
                if module.UNIT is folia.Document:
                    queue.put( (module, foliadoc) )

        for unit in units:
            if unit is not folia.Document:
                self.log("\tQueuing modules handling " + str(type(unit)))
                for data in foliadoc.select(unit):
                    for module in self:
                        if module.UNIT is unit:
                            queue.put( (module, data) )


        self.log("Processing all modules....")
        queue.join()

        self.log("Finalising modules on document") #not parellel, acts on same document anyway, should be fairly quick depending on module
        for module in self:
            module.finish(foliadoc)

        self.log("Processing all modules....")
        #Store FoLiA document
        foliadoc.save()

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


class LoadBalanceMaster: #will cache thingies
    def __init__(self, availableservers, minpollinterval):
        self.availableservers = availableservers
        self.minpollinterval = minpollinterval


    def get(self,servers):
        """Returns the server from servers with the lowest load"""
        #TODO


class LoadBalanceServer: #Reports load balance back to master
    pass


class Module:

    UNIT = folia.Document #Specifies on type of input tbe module gets. An entire FoLiA document is the default, any smaller structure element can be assigned, such as folia.Sentence or folia.Word . More fine-grained levels usually increase efficiency.

    def __init__(self,id, **settings):
        self.id = id
        self.settings = settings
        self.verifysettings()


    def verifysettings(self):
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


        if not 'logfunction' in self.settings:
            self.settings['logfunction'] = lambda x: print(x,file=sys.stderr) #will be rather messy when multithreaded
        self.log = self.settings['logfunction']

        #Some defaults for FoLiA processing
        if not 'set' in self.settings:
            self.settings['set'] = "https://raw.githubusercontent.com/proycon/folia/master/setdefinitions/spellingcorrection.foliaset.xml"
        if not 'class' in self.settings:
            self.settings['class'] = "nonworderror"
        if not 'annotator' in self.settings:
            self.settings['annotator'] = "Gecco-" + self.__class__.__name__

    def findserver(self, loadbalanceserver):
        """Finds a suitable server for this module"""
        if self.local:
            raise Exception("Module is local")
        elif len(self.settings['servers']) == 1:
            #Easy, there is only one
            return self.settings['servers'][0] #2-tuple (host, port)
        else:
            #TODO: Do load balancing, find least busy server
            return loadbalancemaster.get(self.settings['servers'])


    ####################### CALLBACKS ###########################

    # These callbacks are called by the Corrector


    def init(self, foliadoc):
        """Initialises the module on the document. This method should set all the necessary declarations if they are not already present. It will be called sequentially."""
        if 'set' in self.settings and self.settings['set']:
            if not foliadoc.declared(folia.Correction, self.settings['set']):
                foliadoc.declare(folia.Correction, self.settings['set'])

    def finish(self, foliadoc):
        """Finishes the module on the document. This method can do post-processing. It will be called sequentially."""

    def train(self, **parameters):
        """This method gets invoked by the Corrector to train the model. Override it in your own model, use the input files in self.sources and for each entry create the corresponding file in self.models """

    def run(self, data, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally."""

    def client(self, data, lock, host, port, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the host and port are passed."""


    def server(self, port):
        """This methods gets called by the Corrector to start the module's server"""


    ######################## OPTIONAL CALLBACKS  ####################################

    # These callbacks are called by the module itself

    def load(self):
        """Load the requested modules from self.models, module-specific so doesn't do anything by default"""
        pass

    def process(self, word, suggestions):
        """This callback is not directly invoked by the Corrector, but can be invoked by run() or client() to process the obtained list of suggestions. The default implementation of client() uses it"""
        if not isinstance(suggestions, tuple):
            self.addcorrection(word, suggestion=suggestions)
        else:
            self.addcorrection(word, suggestions=suggestions)

    ######################### FOLIA EDITING ##############################


    def addcorrection(self, word, confidence=None  ):
        self.log("Adding correction for " + word.id + " " + word.text())

        #Determine an ID for the next correction
        correction_id = word.generate_id(folia.Correction)

        if 'suggestions' in kwargs:
            #add the correction
            word.correct(
                suggestions=kwargs['suggestions'],
                id=correction_id,
                set=self.settings['set'],
                cls=self.settings['class'],
                annotator=self.settings['annotator'],
                annotatortype=folia.AnnotatorType.AUTO,
                datetime=datetime.datetime.now(),
                confidence=confidence
            )
        elif 'suggestion' in kwargs:
            #add the correction
            word.correct(
                suggestion=kwargs['suggestion'],
                id=correction_id,
                set=self.settings['set'],
                cls=self.settings['class'],
                annotator=self.settings['annotator'],
                annotatortype=folia.AnnotatorType.AUTO,
                datetime=datetime.datetime.now(),
                confidence=confidence
            )
        else:
            raise Exception("No suggestions= specified!")


    def adderrordetection(self, word):
        self.log("Adding correction for " + word.id + " " + word.text())

        #add the correction
        word.append(
            folia.ErrorDetection(
                self.doc,
                set=self.settings['set'],
                cls=self.settings['class'],
                annotator=self.settings['annotator'],
                annotatortype='auto',
                datetime=datetime.datetime.now()
            )
        )

    def splitcorrection(self, word, newwords,**kwargs):
        sentence = word.sentence()
        newwords = [ folia.Word(self.doc, generate_id_in=sentence, text=w) for w in newwords ]
        kwargs['suggest'] = True
        kwargs['datetime'] = datetime.datetime.now()
        word.split(
            *newwords,
            **kwargs
        )

    def mergecorrection(self, newword, originalwords, **kwargs):
        sentence = originalwords[0].sentence()
        if not sentence:
            raise Exception("Expected sentence for " + str(repr(originalwords[0])) + ", got " + str(repr(sentence)))
        newword = folia.Word(self.doc, generate_id_in=sentence, text=newword)
        kwargs['suggest'] = True
        kwargs['datetime'] = datetime.datetime.now()
        sentence.mergewords(
            newword,
            *originalwords,
            **kwargs
        )








