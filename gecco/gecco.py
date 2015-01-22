#!/usr/bin/env python3
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


from collections import OrderedDict
from threading import Thread, Lock
from queue import Queue
import sys
import os
import socket
import socketserver
import yaml
from pynlpl.formats import folia
from ucto import Tokenizer

import argparse

UCTOSEARCHDIRS = ('/usr/local/etc/ucto','/etc/ucto/','.')

VERSION = 0.1


class ProcessorThread(Thread):
    def __init__(self, q, lock, loadbalancemaster, **parameters):
        self.q = q
        self.lock = lock
        self._stop = False
        self.loadbalancemaster = loadbalancemaster
        self.parameters = parameters
        self.clients = {} #each thread keeps a bunch of clients open to the servers of the various modules so we don't have to reconnect constantly (= faster)
        super().__init__()

    def run(self):
        while not self._stop:
            if not self.q.empty():
                module, data = self.q.get() #data is an instance of module.UNIT
                if module.local:
                    module.run(data, self.lock, **self.parameters)
                else:
                    server, port = module.findserver(self.loadbalancemaster)
                    if (server,port) not in self.clients:
                        self.clients[(server,port)] = module.CLIENT(host,port)
                    module.runclient( self.clients[(server,port)], data, self.lock,  **self.parameters)
                self.q.task_done()

    def stop(self):
        self._stop = True


class LoaderThread(Thread):
    def __init__(self, q):
        self.q = q
        super().__init__()

    def run(self):
        while not self.q.empty():
            module = self.q.get() #data is an instance of module.UNIT
            module.load()



class Corrector:
    def __init__(self, **settings):
        self.settings = settings
        self.modules = OrderedDict()
        self.verifysettings()
        self.tokenizer = Tokenizer(self.settings['ucto'])

        #Gather servers
        self.servers = set()
        for module in self:
            if not module.local:
                for host, port in module.settings['servers']:
                    self.servers.add( (host,port) )

        self.loadbalancemaster = LoadBalanceMaster(self)

        self.servers = set( [m.servers for m in self if not m.local] )
        self.units = set( [m.UNIT for m in self] )

    def verifysettings(self):
        if 'config' in self.settings:
            #Settings are in external configuration, parse config and return (verifysettings will be reinvoked from parseconfig)
            self.parseconfig(self.settings['config'])
            return

        if 'id' not in self.settings:
            raise Exception("No ID specified")

        if 'root' not in self.settings:
            self.root = self.settings['root'] = os.path.abspath('.')
        else:
            self.root = os.path.abspath(self.settings['root'])

        if self.root[-1] != '/': self.root += '/'

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

        if not 'minpollinterval' in self.settings:
            self.settings['minpollinterval'] = 30 #30 sec


    def parseconfig(self,configfile):
        config = yaml.load(open(configfile,'r',encoding='utf-8').read())

        if 'modules' not in config:
            raise Exception("No Modules specified")

        modulespecs = config['modules']
        del config['modules']
        self.settings = config
        self.verifysettings()

        for modulespec in modulespecs:
            #import modules:
            pymodule = '.'.join(modulespec['module'].split('.')[:-1])
            moduleclass = modulespec['module'].split('.')[-1]
            exec("from " + pymodule + " import " + moduleclass)
            ModuleClass = locals()[moduleclass]
            if 'servers' in modulespec:
                modulespec['servers'] =  tuple( ( (x['host'],x['port']) for x in modulespec['servers']) )
            module = ModuleClass(self, **modulespec)
            self.append(module)



    def __len__(self):
        return len(self.modules)

    def _getitem__(self, id):
        return self.modules[id]

    def __iter__(self):
        for module in self.modules.values():
            yield module

    def append(self, module):
        assert isinstance(module, Module)
        self.modules[module.id] = module

    def train(self,module_ids=[], **parameters):
        for module in self:
            if not module_ids or module.id in module_ids:
                for sourcefile, modelfile in zip(module.sources, module.models):
                    if (isinstance(modelfile, tuple) and not all([os.path.exists(f) for f in modelfile])) or not os.path.exists(modelfile):
                        self.log("Training module " + module.id + "...")
                        if (isinstance(sourcefile, tuple) and not all([os.path.exists(f) for f in sourcefile])) or not os.path.exists(sourcefile):
                            raise Exception("[" + module.id + "] Source file not found: " + sourcefile)
                        module.train(sourcefile, modelfile, **parameters)

    def test(self,module_ids=[], **parameters):
        for module in self:
            if not module_ids or module.id in module_ids:
                self.log("Testing module " + module.id + "...")
                module.test(**parameters)

    def tune(self,module_ids=[], **parameters):
        for module in self:
            if not module_ids or module.id in module_ids:
                self.log("Tuning module " + module.id + "...")
                module.tune(**parameters)

    def run(self, foliadoc, module_ids=[], outputfile="",**parameters):
        if isinstance(foliadoc, str):
            #We got a filename instead of a FoLiA document, that's okay
            ext = foliadoc.split('.')[-1].lower()
            if not ext in ('xml','folia','gz','bz2'):
                #Preprocessing - Tokenize input text (plaintext) and produce FoLiA output
                self.log("Starting Tokeniser")

                inputtextfile = foliadoc

                if ext == 'txt':
                    outputtextfile = '.'.join(inputtextfile.split('.')[:-1]) + '.folia.xml'
                else:
                    outputtextfile = inputtextfile + '.folia.xml'

                tokenizer = Tokenizer(self.settings['ucto'],xmloutput=True)
                tokenizer.tokenize(inputtextfile, outputtextfile)

                foliadoc = outputtextfile

                self.log("Tokeniser finished")

            #good, load
            self.log("Reading FoLiA document")
            foliadoc = folia.Document(file=foliadoc)




        self.log("Loading local modules")

        queue = Queue()
        threads = []
        for i in range(self.settings['threads']):
            thread = LoaderThread(queue)
            threads.append(thread)


        self.log(str(len(threads)) + " threads ready.")

        for module in self:
            if module.local:
                if not module_ids or module.id in module_ids:
                    queue.put( module )

        for thread in threads:
            thread.start()

        queue.join()


        self.log("Initialising modules on document") #not parellel, acts on same document anyway, should be very quick
        for module in self:
            if not module_ids or module.id in module_ids:
                self.log("\t\Initialising module " + module.id)
                module.init(foliadoc)



        self.log("Initialising processor threads")

        queue = Queue() #data in queue takes the form (module, data), where data is an instance of module.UNIT (a folia document or element)
        threads = []
        for i in range(self.settings['threads']):
            thread = ProcessorThread(queue, lock, self.loadbalancemaster, **parameters)
            thread.start()
            threads.append(thread)

        self.log(str(len(threads)) + " threads ready.")

        if folia.Document in self.units:
            self.log("\tQueuing modules handling full documents")

            for module in self:
                if not module_ids or module.id in module_ids:
                    if module.UNIT is folia.Document:
                        self.log("\t\tQueuing module " + module.id)
                        queue.put( (module, foliadoc) )

        for unit in self.units:
            if unit is not folia.Document:
                self.log("\tQueuing modules handling " + str(unit.__name__))
                for data in foliadoc.select(unit):
                    for module in self:
                        if not module_ids or module.id in module_ids:
                            if module.UNIT is unit:
                                self.log("\t\tQueuing module " + module.id)
                                queue.put( (module, data) )


        self.log("Processing all modules....")
        queue.join()

        for thread in threads:
            thread.stop()

        self.log("Finalising modules on document") #not parellel, acts on same document anyway, should be fairly quick depending on module
        for module in self:
            if not module_ids or module.id in module_ids:
                module.finish(foliadoc)


        #Store FoLiA document
        if outputfile:
            self.log("Saving document " + outputfile + "....")
            foliadoc.save(outputfile)
        else:
            self.log("Saving document " + foliadoc.filename + "....")
            foliadoc.save()

    def startservers(self, module_ids=[]):
        """Starts all servers for the current host"""

        processes = []

        self.log("Starting servers...")
        HOST = socket.getfqdn()
        for module in self:
            if not module.local:
                if not module_ids or module.id in module_ids:
                    for h,port in module.settings['servers']:
                        if h == HOST:
                            #Start this server *in a separate subprocess*
                            if 'config' in settings:
                                cmd = "gecco " + settings['config'] + " "
                            else:
                                cmd = sys.argv[0] + " "
                            cmd += "startserver " + module.id + " " + host + " " + str(port)
                            processes.append( subprocess.Popen(cmd) )

        self.log("Servers started..")
        os.wait() #blocking
        self.log("All servers ended.")


    def startserver(self, module_id, host, port):
        """Start one particular module's server. This method will be launched by server() in different processes"""
        module = self.module[module_id]
        self.log("Loading module")
        module.load()
        self.log("Running server...")
        module.runserver(host,port) #blocking
        self.log("Server ended.")

    def main(self):
        """Parse command line options and run the desired part of the system"""
        parser = argparse.ArgumentParser(description="Gecco is a generic, scalable and modular spelling correction framework", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        subparsers = parser.add_subparsers(dest='command',title='Commands')
        parser_run = subparsers.add_parser('run', help="Run the spelling corrector on the specified input file")
        parser_run.add_argument('-o',dest="outputfile", help="Output filename (if not specified, the input file will be edited in-place",required=False,default="")
        parser_run.add_argument('filename', help="The file to correct, can be either a FoLiA XML file or a plain-text file which will be automatically tokenised and converted on-the-fly. The XML file will also be the output file. The XML file is edited in place, it will also be the output file unless -o is specified")
        parser_run.add_argument('modules', help="Only run the modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_run.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_startservers = subparsers.add_parser('startservers', help="Starts all the module servers that are configured to run on the current host. Issue once for each server used.")
        parser_startservers.add_argument('modules', help="Only start server for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_startserver = subparsers.add_parser('startserver', help="Start one module's server on the specified port, use 'startservers' instead")
        parser_startserver.add_argument('module', help="Module ID")
        parser_startserver.add_argument('host', help="Host/IP to bind to")
        parser_startserver.add_argument('port', type=int, help="Port")
        parser_train = subparsers.add_parser('train', help="Train modules")
        parser_train.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_train.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_test = subparsers.add_parser('test', help="Test modules")
        parser_test.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_test.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_tune = subparsers.add_parser('tune', help="Tune modules")
        parser_tune.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_tune.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")

        args = parser.parse_args()

        parameters = {}
        modules = []
        if args.command == 'run':
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.modules: modules = args.modules.split(',')
            self.run(args.filename,modules, args.outputfile, **parameters)
        elif args.command == 'startservers':
            self.startservers(modules)
        elif args.command == 'startserver':
            self.startserver(args.module, args.host, args.port)
        elif args.command == 'train':
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.modules: modules = args.modules.split(',')
            self.train(modules)
        elif args.command == 'test':
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.modules: modules = args.modules.split(',')
            self.test(modules)
        elif args.command == 'tune':
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.modules: modules = args.modules.split(',')
            self.tune(modules)
        elif not args.command:
            parser.print_help()
        else:
            print("No such command: " + args.command,file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

class LoadBalanceMaster: #will cache thingies
    def __init__(self, parent):
        self.parent = parent
        self.availableservers = self.parent.servers
        self.minpollinterval = self.parent.settings['minpollinterval']


    def get(self,servers):
        """Returns the server from servers with the lowest load"""
        #TODO


class LoadBalanceServer: #Reports load balance back to master
    pass #TODO


class LineByLineClient:
    """Simple communication protocol between client and server, newline-delimited"""

    def __init__(self, host, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False

    def connect(self):
        self.socket.connect( (host,port) )
        self.connected = True

    def communicate(self, msg):
        self.send(msg)
        answer = self.receive()

    def send(self, msg):
        if not self.connected: self.connect()
        if isinstance(msg, str): msg = msg.encode('utf-8')
        if msg[-1] != b"\n": msg += b"\n"
        self.sock.sendall(msg)

    def receive(self):
        buffer = b''
        cont_recv = True
        while cont_recv:
            buffer += socket.recv(1024)
            if buffer[-1] == b"\n":
                cont_recv = False
        return str(buffer,'utf-8')

class LineByLineServerHandler(socketserver.BaseRequestHandler):
    """
    The generic RequestHandler class for our server. Instantiated once per connection to the server, invokes the module's server_handler()
    """

    def handle(self):
        # self.request is the TCP socket connected to the client, self.server is the server
        cont_recv = True
        while cont_recv:
            buffer += self.request.recv(1024)
            if buffer[-1] == b"\n":
                cont_recv = False
        msg = str(buffer,'utf-8')
        response = self.server.module.server_handler(msg)
        if isinstance(response,str):
            response = response.encode('utf-8')
        if response[-1] != b"\n": response += b"\n"
        self.request.sendall(response)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

class Module:

    UNIT = folia.Document #Specifies on type of input tbe module gets. An entire FoLiA document is the default, any smaller structure element can be assigned, such as folia.Sentence or folia.Word . More fine-grained levels usually increase efficiency.
    CLIENT = LineByLineClient
    SERVER = LineByLineServerHandler

    def __init__(self, parent,**settings):
        self.parent = parent
        self.settings = settings
        self.verifysettings()

    def getfilename(self, filename):
        if isinstance(filename, tuple):
            return tuple( ( self.getfilename(x) for x in filename ) )
        elif filename[0] == '/':
            return filename
        else:
            return self.parent.root + filename

    def verifysettings(self):
        if 'id' not in self.settings:
            raise Exception("Module must have an ID!")
        self.id = self.settings['id']

        self.local = 'servers' in self.settings
        if 'source' in self.settings:
            if isinstance(self.settings['source'],str):
                self.sources = [ self.settings['source'] ]
            else:
                self.sources = self.settings['source']
        elif 'sources' in self.settings:
            self.sources = self.settings['sources']
        else:
            self.sources = []
        self.sources = [ self.getfilename(f) for f in self.sources ]


        if 'model' in self.settings:
            if isinstance(self.settings['model'],str):
                self.models = [ self.settings['model'] ]
            else:
                self.models = self.settings['model']
        elif 'models' in self.settings:
            self.models = self.settings['models']
        else:
            self.models = []
        self.models = [ self.getfilename(f) for f in self.models ]

        if self.sources and len(self.sources) != len(self.models):
            raise Exception("Number of specified sources and models for module " + self.id + " should be equal!")

        if not 'logfunction' in self.settings:
            self.settings['logfunction'] = lambda x: print("[" + self.id + "] " + x,file=sys.stderr) #will be rather messy when multithreaded
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


    ##### Optional callbacks invoked by the Corrector (defaults may suffice)

    def init(self, foliadoc):
        """Initialises the module on the document. This method should set all the necessary declarations if they are not already present. It will be called sequentially."""
        if 'set' in self.settings and self.settings['set']:
            if not foliadoc.declared(folia.Correction, self.settings['set']):
                foliadoc.declare(folia.Correction, self.settings['set'])
        return True

    def runserver(self, host, port):
        """Runs the server. Invoked by the Corrector on start. """
        server = ThreadedTCPServer((host, port), LineByLineServerHandler)
        # Start a thread with the server -- that thread will then start one more thread for each request
        server_thread = Thread(target=server.serve_forever)
        # Exit the server thread when the main thread terminates
        server_thread.daemon = True
        server_thread.start()


    def finish(self, foliadoc):
        """Finishes the module on the document. This method can do post-processing. It will be called sequentially."""
        return False #Nothing to finish for this module

    def train(self, sourcefile, modelfile, **parameters):
        """This method gets invoked by the Corrector to train the model. Build modelfile out of sourcefile. Either may be a tuple if multiple files are required/requested. The function may be invoked multiple times with differences source and model files"""
        return False #Implies there is nothing to train for this module

    def test(self, **parameters):
        """This method gets invoked by the Corrector to test the model. Override it in your own model, use the input files in self.sources and for each entry create the corresponding file in self.models """
        return False #Implies there is nothing to test for this module

    def tune(self, **parameters):
        """This method gets invoked by the Corrector to test the model. Override it in your own model, use the input files in self.sources and for each entry create the corresponding file in self.models """
        return False #Implies there is nothing to tune for this module

    ##### Callbacks invoked by the Corrector that MUST be implemented:

    def run(self, data, lock, **parameters):
        """This method gets invoked by the Corrector when it runs locally."""
        raise NotImplementedError

    def runclient(self, client, data, lock,  **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication)"""
        raise NotImplementedError

    ##### Callback invoked by module's server, MUST be implemented:

    def server_handler(self, msg):
        """This methods gets called by the module's server and handles a message by the client. The return value (str) is returned to the client"""
        raise NotImplementedError


    #### Callback invoked by the module itself, MUST be implemented

    def load(self):
        """Load the requested modules from self.models, module-specific so doesn't do anything by default"""
        pass


    ######################### FOLIA EDITING ##############################
    #
    # These methods are *NOT* available to server_handler() !
    # Locks ensure that the state of the FoLiA document can't be corrupted by partial unfinished edits

    def addwordsuggestions(self, lock, word, suggestions, confidence=None  ):
        self.log("Adding correction for " + word.id + " " + word.text())

        lock.acquire()
        #Determine an ID for the next correction
        correction_id = word.generate_id(folia.Correction)

        #add the correction
        word.correct(
            suggestions=suggestion,
            id=correction_id,
            set=self.settings['set'],
            cls=self.settings['class'],
            annotator=self.settings['annotator'],
            annotatortype=folia.AnnotatorType.AUTO,
            datetime=datetime.datetime.now(),
            confidence=confidence
        )
        lock.release()



    def adderrordetection(self, lock, word):
        self.log("Adding correction for " + word.id + " " + word.text())

        lock.acquire()
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
        lock.release()

    def splitcorrection(self, lock, word, newwords,**kwargs):
        lock.acquire()
        sentence = word.sentence()
        newwords = [ folia.Word(self.doc, generate_id_in=sentence, text=w) for w in newwords ]
        kwargs['suggest'] = True
        kwargs['datetime'] = datetime.datetime.now()
        word.split(
            *newwords,
            **kwargs
        )
        lock.release()

    def mergecorrection(self, lock, newword, originalwords, **kwargs):
        lock.acquire()
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
        lock.release()


def main():
    try:
        configfile = sys.argv[1]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    except:
        print("Syntax: gecco [configfile.yml]" ,file=sys.stderr)
        sys.exit(2)
    corrector = Corrector(config=configfile)
    corrector.main()


if __name__ == '__main__':
    main()
