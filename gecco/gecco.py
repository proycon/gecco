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


import sys
import os
import socket
import socketserver
import yaml
import datetime
import time
import subprocess
from collections import OrderedDict
from threading import Thread, Lock
from queue import Queue
from pynlpl.formats import folia, fql
from ucto import Tokenizer #pylint: disable=import-error,no-name-in-module

import gecco.helpers.evaluation

import argparse

UCTOSEARCHDIRS = ('/usr/local/etc/ucto','/etc/ucto/',os.environ['VIRTUAL_ENV'] + '/etc/ucto/','.')
if 'VIRTUAL_ENV' in os.environ:
    UCTOSEARCHDIRS = (os.environ['VIRTUAL_ENV'] + '/etc/ucto/',) + UCTOSEARCHDIRS

VERSION = 0.1

class ProcessorThread(Thread):
    def __init__(self, parent, q, lock, loadbalancemaster, **parameters):
        self.parent = parent
        self.q = q
        self.lock = lock
        self._stop = False
        self.loadbalancemaster = loadbalancemaster
        self.parameters = parameters
        self.debug  = 'debug' in parameters and parameters['debug']
        self.clients = {} #each thread keeps a bunch of clients open to the servers of the various modules so we don't have to reconnect constantly (= faster)
        super().__init__()

    def run(self):
        while not self._stop:
            if not self.q.empty():
                module, data = self.q.get() #data is an instance of module.UNIT
                if not module.UNITFILTER or module.UNITFILTER(data):
                    if not module.submodule: #modules marked a submodule won't be called by the main process, but are invoked by other modules instead
                        module.prepare() #will block until all dependencies are done
                        if module.local:
                            if self.debug:
                                begintime = time.time()
                                module.log(" (Running " + module.id + " on '" + str(data) + "' [local])")
                            module.run(data, self.lock, **self.parameters)
                            if self.debug:
                                duration = round(time.time() - begintime,4)
                                module.log(" (...took " + str(duration) + "s)")
                        else:
                            skipservers= []
                            connected = False
                            if self.debug:
                                begintime = time.time()
                                module.log(" (Running " + module.id + " on '" + str(data) + "' [remote]")
                            for server,port in  module.findserver(self.loadbalancemaster):
                                try:
                                    if (server,port) not in self.clients:
                                        self.clients[(server,port)] = module.CLIENT(server,port)
                                    if self.debug:
                                        module.log(" (server=" + server + ", port=" + str(port) + ")")
                                    module.runclient( self.clients[(server,port)], data, self.lock,  **self.parameters)
                                    #will only be executed when connection succeeded:
                                    connected = True
                                    break
                                except ConnectionRefusedError:
                                    del self.clients[(server,port)]
                            if not connected:
                                self.q.task_done()
                                raise Exception("Unable to connect client to server! All servers for module " + module.id + " are down!")
                            if self.debug:
                                duration = round(time.time() - begintime,4)
                                module.log(" (...took " + str(duration) + "s)")
                self.q.task_done()
                self.parent.done.add(module.id)

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
            self.q.task_done()



class Corrector:
    def __init__(self, **settings):
        self.settings = settings
        self.modules = OrderedDict()
        self.verifysettings()
        self.tokenizer = Tokenizer(self.settings['ucto'])

        #Gather servers
        self.servers = set( [m.settings['servers'] for m in self if not m.local ] )

        self.loadbalancemaster = LoadBalanceMaster(self)

        self.units = set( [m.UNIT for m in self] )
        self.loaded = False

    def load(self):
        if not self.loaded:
            self.log("Loading local modules")
            begintime =time.time()

            queue = Queue()
            threads = []
            for _ in range(self.settings['threads']):
                thread = LoaderThread(queue)
                thread.setDaemon(True)
                threads.append(thread)


            self.log(str(len(threads)) + " threads ready.")

            for module in self:
                if module.local:
                    queue.put( module )
                    self.log("Queuing " + module.id + " for loading")

            for thread in threads:
                thread.start()
                del thread
            del threads

            queue.join()
            del queue
            self.loaded = True
            duration = time.time() - begintime
            self.log("Modules loaded (" + str(duration) + "s)")


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
        self.configfile = configfile
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
            try:
                module = ModuleClass(self, **modulespec)
            except TypeError:
                raise Exception("Error instantiating " + ModuleClass.__name__)

            self.append(module)



    def __len__(self):
        return len(self.modules)

    def _getitem__(self, id):
        return self.modules[id]

    def __iter__(self):
        #iterate in proper dependency order:
        done = set()

        modules = self.modules.values()
        while modules:
            postpone = []
            for module in self.modules.values():
                if module.settings['depends']:
                    for dep in module.settings['depends']:
                        if dep not in done:
                            postpone.append(module)
                            break
                if module not in postpone:
                    done.add(module.id)
                    yield module

            if modules == postpone:
                raise Exception("There are unsolvable (circular?) dependencies in your module definitions")
            else:
                modules = postpone

    def append(self, module):
        assert isinstance(module, Module)
        self.modules[module.id] = module

    def train(self,module_ids=[], **parameters): #pylint: disable=dangerous-default-value
        for module in self:
            if not module_ids or module.id in module_ids:
                for sourcefile, modelfile in zip(module.sources, module.models):
                    if (isinstance(modelfile, tuple) and not all([os.path.exists(f) for f in modelfile])) or not os.path.exists(modelfile):
                        self.log("Training module " + module.id + "...")
                        if (isinstance(sourcefile, tuple) and not all([os.path.exists(f) for f in sourcefile])) or not os.path.exists(sourcefile):
                            raise Exception("[" + module.id + "] Source file not found: " + sourcefile)
                        module.train(sourcefile, modelfile, **parameters)

    def evaluate(self, args):
        for  module in self.modules.values():
            module.local = True
        if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
        if args.modules: modules = args.modules.split(',')

        outputfiles = []
        if os.path.isdir(args.outputfilename):
            outputdir = args.outputfilename
        else:
            outputdir = None
            outputfiles = [args.outputfilename]

        if os.path.isdir(args.referencefilename):
            refdir = args.referencefilename
        elif os.path.isfile(args.referencefilename):
            refdir = None
        else:
            raise Exception("Reference file not found", args.referencefilename)

        inputfiles = []
        if os.path.isdir(args.inputfilename):
            for root, _, files in os.walk(args.inputfilename):
                for name in files:
                    inputfiles.append(os.path.join(root,name))
                    if outputdir:
                        outputfiles.append(os.path.join(outputdir,name))

        elif os.path.isfile(args.inputfilename):
            inputfiles = [args.inputfilename]
        else:
            raise Exception("Input file not found", args.inputfilename)



        evaldata = gecco.helpers.evaluation.Evaldata()
        for inputfilename, outputfilename in zip(inputfiles, outputfiles):
            self.run(inputfilename,modules,outputfilename, **parameters)
            if refdir:
                referencefilename = os.path.join(refdir, os.path.basename(outputfilename))
            else:
                referencefilename = args.referencefilename
            gecco.helpers.evaluation.processfile(outputfilename, referencefilename, evaldata)

        evaldata.output()

    def test(self,module_ids=[], **parameters): #pylint: disable=dangerous-default-value
        for module in self:
            if not module_ids or module.id in module_ids:
                self.log("Testing module " + module.id + "...")
                module.test(**parameters)

    def tune(self,module_ids=[], **parameters): #pylint: disable=dangerous-default-value
        for module in self:
            if not module_ids or module.id in module_ids:
                self.log("Tuning module " + module.id + "...")
                module.tune(**parameters)

    def reset(self,module_ids=[]): #pylint: disable=dangerous-default-value
        for module in self:
            if not module_ids or module.id in module_ids:
                if module.sources and module.models:
                    for sourcefile, modelfile in zip(module.sources, module.models):
                        if sourcefile:
                            if isinstance(modelfile, tuple):
                                l = modelfile
                            else:
                                l = [modelfile]
                            for modelfile in l:
                                if os.path.exists(modelfile):
                                    self.log("Deleting model " + modelfile + "...")
                                    module.reset(modelfile, sourcefile)

    def run(self, foliadoc, module_ids=[], outputfile="",**parameters): #pylint: disable=dangerous-default-value
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


        self.load() #will only do something the first time executed

        begintime = time.time()
        self.log("Initialising modules on document") #not parellel, acts on same document anyway, should be very quick
        for module in self:
            if not module_ids or module.id in module_ids:
                self.log("\tInitialising module " + module.id)
                module.init(foliadoc)



        self.done = set()

        self.log("Initialising processor threads")

        queue = Queue() #data in queue takes the form (module, data), where data is an instance of module.UNIT (a folia document or element)
        lock = Lock()
        threads = []
        for _ in range(self.settings['threads']):
            thread = ProcessorThread(self, queue, lock, self.loadbalancemaster, **parameters)
            thread.setDaemon(True)
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
                                queue.put( (module, data) )

        duration = time.time() - begintime
        self.log("Processing done (" + str(duration) + "s)")

        self.log("Processing all modules....")
        begintime = time.time()
        queue.join()
        duration = time.time() - begintime
        self.log("Processing done (" + str(duration) + "s)")

        for thread in threads:
            thread.stop()
            del thread

        del queue
        del lock
        del threads

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

        return foliadoc



    def startservers(self, module_ids=[]): #pylint: disable=dangerous-default-value
        """Starts all servers for the current host"""

        processes = []

        MYHOSTS = set( [socket.getfqdn() , socket.gethostname(), socket.gethostbyname(socket.gethostname()), '127.0.0.1'] )
        self.log("Starting servers for "  + "/".join(MYHOSTS) )

        for module in self:
            if not module.local:
                if not module_ids or module.id in module_ids:
                    for host,port in module.settings['servers']:
                        if host in MYHOSTS:
                            #Start this server *in a separate subprocess*
                            if self.configfile:
                                cmd = "gecco " + self.configfile + " "
                            else:
                                cmd = sys.argv[0] + " "
                            cmd += "startserver " + module.id + " " + host + " " + str(port)
                            processes.append( subprocess.Popen(cmd.split(' ')) )
            else:
                print("Module " + module.id + " is local",file=sys.stderr)

        self.log(str(len(processes)) + " server(s) started.")
        if processes:
            os.wait() #blocking
        self.log("All servers ended.")


    def startserver(self, module_id, host, port):
        """Start one particular module's server. This method will be launched by server() in different processes"""
        module = self.modules[module_id]
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
        parser_run.add_argument('-s',dest='settings', help="Setting overrides, specify as -s setting=value. This option can be issues multiple times.", required=False, action="append")
        parser_run.add_argument('--local', help="Run all modules locally, ignore remote servers", required=False, action='store_true')
        parser_startservers = subparsers.add_parser('startservers', help="Starts all the module servers that are configured to run on the current host. Issue once for each server used.")
        parser_startservers.add_argument('modules', help="Only start server for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_startserver = subparsers.add_parser('startserver', help="Start one module's server on the specified port, use 'startservers' instead")
        parser_startserver.add_argument('module', help="Module ID")
        parser_startserver.add_argument('host', help="Host/IP to bind to")
        parser_startserver.add_argument('port', type=int, help="Port")
        parser_train = subparsers.add_parser('train', help="Train modules")
        parser_train.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are trained)", nargs='?',default="")
        parser_train.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_eval = subparsers.add_parser('evaluate', help="Runs the spelling corrector on input data and compares it to reference data, produces an evaluation report")
        parser_eval.add_argument('inputfilename', help="File or directory containing the input (plain text or FoLiA XML)")
        parser_eval.add_argument('outputfilename', help="File or directory to store the output (FoLiA XML)")
        parser_eval.add_argument('referencefilename', help="File or directory that holds the reference data (FoLiA XML)")
        parser_eval.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are tested)", nargs='?',default="")
        parser_eval.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        #parser_test = subparsers.add_parser('test', help="Test modules")
        #parser_test.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are tested)", nargs='?',default="")
        #parser_test.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        #parser_tune = subparsers.add_parser('tune', help="Tune modules")
        #parser_tune.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are tuned)", nargs='?',default="")
        #parser_tune.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_reset  = subparsers.add_parser('reset', help="Reset modules, deletes all trained models that have sources. Issue prior to train if you want to start anew.")
        parser_reset.add_argument('modules', help="Only reset for modules with the specified IDs (comma-separated list) (if omitted, all modules are reset)", nargs='?',default="")




        args = parser.parse_args()

        try:
            if  args.settings:
                for key, value in ( tuple(p.split('=')) for p in args.settings):
                    if value.isnumeric():
                        self.settings[key] = int(value)
                    else:
                        self.settings[key] = value
        except AttributeError:
            pass

        parameters = {}
        modules = []
        if args.command == 'run':
            for  module in self.modules.values():
                module.local = True
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
        elif args.command == 'evaluate':
            self.evaluate(args)
        elif args.command == 'test':
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.modules: modules = args.modules.split(',')
            self.test(modules)
        elif args.command == 'tune':
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.modules: modules = args.modules.split(',')
            self.tune(modules)
        elif args.command == 'reset':
            if args.modules: modules = args.modules.split(',')
            self.reset(modules)
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


    def get(self,servers, skipservers=[]):
        """Generator return servers from servers from highest to lower (with caching)"""
        #TODO
        raise NotImplementedError


class LoadBalanceServer: #Reports load balance back to master
    pass #TODO


class LineByLineClient:
    """Simple communication protocol between client and server, newline-delimited"""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connected = False

    def connect(self):
        print("Connecting to "  + self.host + ":" + str(self.port) ,file=sys.stderr)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect( (self.host,self.port) )
        self.connected = True

    def communicate(self, msg):
        self.send(msg)
        answer = self.receive()
        #print("Output: [" + msg + "], Response: [" + answer + "]",file=sys.stderr)
        return answer

    def send(self, msg):
        if not self.connected: self.connect()
        if isinstance(msg, str): msg = msg.encode('utf-8')
        if msg[-1] != 10: msg += b"\n"
        self.socket.sendall(msg)

    def receive(self):
        if not self.connected: self.connect()
        buffer = b''
        cont_recv = True
        while cont_recv:
            chunk = self.socket.recv(1024)
            if not chunk or chunk[-1] == 10: #newline
                cont_recv = False
            buffer += chunk
        return str(buffer,'utf-8').strip()

    def close(self):
        if self.connected:
            self.socket.close()
            self.connected = False

class LineByLineServerHandler(socketserver.BaseRequestHandler):
    """
    The generic RequestHandler class for our server. Instantiated once per connection to the server, invokes the module's server_handler()
    """

    def handle(self):
        while True: #We have to loop so connection is not closed after one request
            # self.request is the TCP socket connected to the client, self.server is the server
            cont_recv = True
            buffer = b''
            while cont_recv:
                chunk = self.request.recv(1024)
                if not chunk or chunk[-1] == 10: #newline
                    cont_recv = False
                buffer += chunk
            if not chunk: #connection broken
                break
            msg = str(buffer,'utf-8').strip()
            response = self.server.module.server_handler(msg)
            #print("Input: [" + msg + "], Response: [" + response + "]",file=sys.stderr)
            if isinstance(response,str):
                response = response.encode('utf-8')
            if response[-1] != 10: response += b"\n"
            self.request.sendall(response)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

class Module:

    UNIT = folia.Document #Specifies on type of input tbe module gets. An entire FoLiA document is the default, any smaller structure element can be assigned, such as folia.Sentence or folia.Word . More fine-grained levels usually increase efficiency.
    UNITFILTER = None #Can be a function that takes a unit and return True if it has to be processed
    CLIENT = LineByLineClient
    SERVER = LineByLineServerHandler

    def __init__(self, parent,**settings):
        self.parent = parent
        self.settings = settings
        self.submodclients = {} #each module keeps a bunch of clients open to the servers of the various isubmodules so we don't have to reconnect constantly (= faster)
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
            self.settings['annotator'] = self.id

        if not 'depends' in self.settings:
            self.settings['depends'] = []

        if not 'submodules' in self.settings:
            self.submodules = {}
        else:
            try:
                self.submodules = { self.parent[x].id :  self.parent[x] for x in self.settings['submodules'] }
            except KeyError:
                raise Exception("One or more submodules are not defined")

            for m in self.submodules.values():
                if m.local:
                    raise Exception("Module " + m.id + " is used as a submodule, but no servers are defined, submodules can not be local only")
                if m.UNIT != self.UNIT:
                    raise Exception("Module " + m.id + " is used as a submodule of " + self.id  + ", but they do not take the same unit")


        if not 'submodule' in self.settings:
            self.submodule = False
        else:
            self.submodule = bool(self.settings['submodule'])

        self.local = not ('servers' in self.settings and self.settings['servers']) #will be overriden later if --local is set

        if self.submodule and self.local:
            raise Exception("Module " + self.id + " is a submodule, but no servers are defined, submodules can not be local only")


    def findserver(self, loadbalanceserver):
        """Finds a suitable server for this module"""
        if self.local:
            raise Exception("Module is local")
        elif len(self.settings['servers']) == 1:
            #Easy, there is only one
            yield self.settings['servers'][0] #2-tuple (host, port)
        else:
            #TODO: Do load balancing, find least busy server
            for host, port in self.loadbalancemaster.get(self.settings['servers']):
                yield host, port

    def getsubmoduleclient(self, submodule):
        submodule.prepare() #will block until all submod dependencies are done
        for server,port in submodule.findserver(self.parent.loadbalancemaster):
            if (server,port) not in self.submodclients:
                self.submodclients[(server,port)] = submodule.CLIENT(server,port)
            return self.submodclients[(server,port)]
        raise Exception("Could not find server for submodule " + submodule.id)

    def prepare(self):
        """Executed prior to running the module, waits until all dependencies have completed"""
        waiting = True
        while waiting:
            waiting = False
            for dep in self.settings['depends']:
                if dep not in self.parent.done:
                    waiting = True
                    break
            if waiting:
                time.sleep(0.05)

    ####################### CALLBACKS ###########################


    ##### Optional callbacks invoked by the Corrector (defaults may suffice)

    def init(self, foliadoc):
        """Initialises the module on the document. This method should set all the necessary declarations if they are not already present. It will be called sequentially and only once on the entire document."""
        if 'set' in self.settings and self.settings['set']:
            if not foliadoc.declared(folia.Correction, self.settings['set']):
                foliadoc.declare(folia.Correction, self.settings['set'])
        return True

    def runserver(self, host, port):
        """Runs the server. Invoked by the Corrector on start. """
        server = ThreadedTCPServer((host, port), self.SERVER)
        server.allow_reuse_address = True
        server.module = self
        # Start a thread with the server -- that thread will then start one more thread for each request
        server_thread = Thread(target=server.serve_forever)
        # Exit the server thread when the main thread terminates
        server_thread.setDaemon(True)
        server_thread.start()

        server_thread.join() #block until done

        server.shutdown()


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
        """This method gets invoked by the Corrector to tune the model. Override it in your own model, use the input files in self.sources and for each entry create the corresponding file in self.models """
        return False #Implies there is nothing to tune for this module

    def reset(self, modelfile, sourcefile):
        """Resets a module, should delete the specified modelfile (NOT THE SOURCEFILE!)"""
        filenames = (modelfile, modelfile.replace(".ibase",".wgt"), modelfile.replace(".ibase",".train"))
        for filename in filenames:
            if os.path.exists(filename):
                os.unlink(filename)

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

    def addsuggestions(self, lock, element, suggestions, **kwargs):
        self.log("Adding correction for " + element.id + " " + element.text())

        if 'cls' in kwargs:
            cls = kwargs['cls']
        else:
            cls = self.settings['class']

        if isinstance(suggestions,str):
            suggestions = [suggestions]

        q = "EDIT t (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + cls + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        for suggestion in suggestions:
            if isinstance(suggestion, tuple):
                suggestion, confidence = suggestion
            else:
                confidence = None
            q += " SUGGESTION text \"" + suggestion + "\""
            if confidence is not None:
                q += " WITH confidence " + str(confidence)

        q += ") FOR ID \"" + element.id + "\" RETURN nothing"
        self.log(" FQL: " + q)
        q = fql.Query(q)
        lock.acquire()
        #begintime = time.time()
        q(element.doc)
        #duration = time.time() - begintime
        #self.log(" (Query took " + str(duration) + "s)")
        lock.release()


    def adderrordetection(self, lock, element):
        self.log("Adding correction for " + element.id + " " + element.text())

        #add the correction
        q =fql.Query("ADD errordetection OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now FOR ID \"" + element.id + "\" RETURN nothing")
        lock.acquire()
        q(element.doc)
        lock.release()

    def splitcorrection(self, lock, word, suggestions):
        #suggestions is a list of  ([word], confidence) tuples
        q = "SUBSTITUTE (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        for suggestion, confidence in suggestions:
            q += " SUGGESTION ("
            for i, newword in enumerate(suggestion):
                if i > 0: q += " "
                q += "SUBSTITUTE w WITH text \"" + newword + "\""
            q += ") WITH confidence " + str(confidence)
        q = ") FOR SPAN ID \"" + word.id + "\""
        q += " RETURN nothing"
        self.log(" FQL: " + q)
        q = fql.Query(q)
        lock.acquire()
        q(word.doc)
        lock.release()

    def mergecorrection(self, lock, newword, originalwords):
        q = "SUBSTITUTE (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        q += " SUGGESTION"
        q += " (SUBSTITUTE w WITH text \"" + newword + "\")"
        #q += " WITH confidence " + str(confidence)
        q += ") FOR SPAN"
        for i, ow in enumerate(originalwords):
            if i > 0: q += " &"
            q += " ID \"" + ow.id + "\""
        q += " RETURN nothing"
        self.log(" FQL: " + q)
        q = fql.Query(q)
        lock.acquire()
        q(originalwords[0].doc)
        lock.release()

    def suggestdeletion(self, lock, word,merge=False, **kwargs):
        #MAYBE TODO: Convert to FQL
        lock.acquire()
        parent = word.parent
        index = parent.getindex(word,False)
        if 'cls' in kwargs:
            cls = kwargs['cls']
        else:
            cls = self.settings['class']
        if index != -1:
            self.log(" Suggesting deletion of " + str(word.id))
            sugkwargs = {}
            if merge:
                sugkwargs['merge'] = word.ancestor(folia.StructureElement).id
            parent.data[index] = folia.Correction(word.doc, folia.Suggestion(word.doc, **sugkwargs), folia.Current(word.doc, word), set=self.settings['set'],cls=cls, annotator=self.settings['annotator'],annotatortype=folia.AnnotatorType.AUTO, datetime=datetime.datetime.now())
        else:
            self.log(" ERROR: Unable to suggest deletion of " + str(word.id) + ", item index not found")
        lock.release()

    def suggestinsertion(self,lock,pivotword, text,split=False):
        #MAYBE TODO: Convert to FQL
        lock.acquire()
        index = pivotword.parent.getindex(pivotword)
        if index != -1:
            self.log(" Suggesting insertion before " + str(pivotword.id))
            sugkwargs = {}
            if split:
                sugkwargs['split'] = pivotword.ancestor(folia.StructureElement).id
            doc = pivotword.doc
            pivotword.parent.insert(index,folia.Correction(doc, folia.Suggestion(doc, folia.Word(doc,text,generate_id_in=pivotword.parent)), folia.Current(doc), set=self.settings['set'],cls=self.settings['class'], annotator=self.settings['annotator'],annotatortype=folia.AnnotatorType.AUTO, datetime=datetime.datetime.now(), generate_id_in=pivotword.parent))
        else:
            self.log(" ERROR: Unable to suggest insertion before " + str(pivotword.id) + ", item index not found")
        lock.release()


def main():
    try:
        configfile = sys.argv[1]
        if configfile in ("-h","--help"):
            raise
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    except:
        print("Syntax: gecco [configfile.yml] (First specify a config file, for help then add -h)" ,file=sys.stderr)
        sys.exit(2)
    corrector = Corrector(config=configfile)
    corrector.main()


if __name__ == '__main__':
    main()
