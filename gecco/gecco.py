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

#pylint: disable=too-many-nested-blocks

import sys
import os
import socket
import socketserver
import datetime
import time
import subprocess
import json
import traceback
import random
import importlib
import inspect
from collections import OrderedDict, defaultdict
#from threading import Thread, Lock
from queue import Empty
from threading import Thread
from multiprocessing import Process, Lock, JoinableQueue as Queue #pylint: disable=no-name-in-module
from glob import glob
import argparse
import psutil
import yaml
from pynlpl.formats import folia, fql #pylint: disable=import-error,no-name-in-module
from ucto import Tokenizer #pylint: disable=import-error,no-name-in-module

import gecco.helpers.evaluation
from gecco.helpers.common import folia2json



UCTOSEARCHDIRS = ('/usr/local/share/ucto','/usr/share/ucto', '/usr/local/etc/ucto','/etc/ucto/','.')
if 'VIRTUAL_ENV' in os.environ:
    UCTOSEARCHDIRS = (os.environ['VIRTUAL_ENV'] + '/share/ucto/', os.environ['VIRTUAL_ENV'] + '/etc/ucto/',) + UCTOSEARCHDIRS

VERSION = '0.2.5'

class DataThread(Process):
    def __init__(self, corrector, foliadoc, module_ids, outputfile,  inputqueue, outputqueue, infoqueue,waitforprocessors,dumpxml, dumpjson,**parameters):
        super().__init__()

        self.corrector = corrector
        self.inputqueue = inputqueue
        self.outputqueue = outputqueue
        self.infoqueue = infoqueue
        self.module_ids = module_ids
        self.outputfile = outputfile
        self.parameters = parameters
        self.dumpxml = dumpxml
        self.dumpjson = dumpjson
        self.waitforprocessors = waitforprocessors
        self.debug =  'debug' in self.parameters and self.parameters['debug']
        self._stop = False

        #Load FoLiA document
        if isinstance(foliadoc, str):
            #We got a filename instead of a FoLiA document, that's okay
            ext = foliadoc.split('.')[-1].lower()
            if not ext in ('xml','folia','gz','bz2'):
                #Preprocessing - Tokenize input text (plaintext) and produce FoLiA output
                self.corrector.log("Starting Tokeniser")

                inputtextfile = foliadoc

                if ext == 'txt':
                    outputtextfile = '.'.join(inputtextfile.split('.')[:-1]) + '.folia.xml'
                else:
                    outputtextfile = inputtextfile + '.folia.xml'

                tokenizer = Tokenizer(self.corrector.settings['ucto'],xmloutput=True)
                tokenizer.tokenize(inputtextfile, outputtextfile)

                foliadoc = outputtextfile

                self.corrector.log("Tokeniser finished")

            #good, load
            self.corrector.log("Reading FoLiA document")
            self.foliadoc = folia.Document(file=foliadoc)
        else:
            self.foliadoc = foliadoc

        if 'metadata' in parameters:
            for k, v in parameters['metadata'].items():
                self.foliadoc.metadata[k] = v

        begintime = time.time()
        self.corrector.log("Initialising modules on document") #not parallel, acts on same document anyway, should be very quick
        for module in self.corrector:
            if not module_ids or module.id in module_ids:
                self.corrector.log("\tInitialising module " + module.id)
                module.init(self.foliadoc)

        #data in inputqueue takes the form (module, data), where data is an instance of module.UNIT (a folia document or element)
        if folia.Document in self.corrector.units:
            self.corrector.log("\tPreparing input of full documents")

            for module in self.corrector:
                if not module_ids or module.id in module_ids:
                    if module.UNIT is folia.Document:
                        self.corrector.log("\t\tQueuing full-document module " + module.id)
                        inputdata = module.prepareinput(self.foliadoc,**parameters)
                        if inputdata is not None:
                            self.inputqueue.put( (module.id, self.foliadoc.id, inputdata) )

        for unit in self.corrector.units:
            if unit is not folia.Document:
                self.corrector.log("\tPreparing input of " + str(unit.__name__))
                for element in self.foliadoc.select(unit):
                    for module in self.corrector:
                        if not module_ids or module.id in module_ids:
                            if module.UNIT is unit:
                                inputdata = module.prepareinput(element,**parameters)
                                if inputdata is not None:
                                    self.inputqueue.put( (module.id, element.id, inputdata ) )

        for _ in range(self.corrector.settings['threads']):
            self.inputqueue.put( (None,None,None) ) #signals the end of the queue, once for each thread

        duration = time.time() - begintime
        self.corrector.log("Input ready (" + str(duration) + "s)")

    def run(self):
        self.corrector.log("Waiting for processors to be ready...") #not parallel, acts on same document anyway, should be fairly quick depending on module
        self.waitforprocessors.acquire(True,self.corrector.settings['timeout'])
        self.corrector.log("Processing output...") #not parallel, acts on same document anyway, should be fairly quick depending on module
        while not self._stop:
            module_id, unit_id, outputdata, inputdata = self.outputqueue.get(True,self.corrector.settings['timeout'])
            self.outputqueue.task_done()
            if module_id is None and unit_id is None and outputdata is None and inputdata is None: #signals the end of the queue
                self._stop = True
            elif outputdata:
                module = self.corrector.modules[module_id]
                try:
                    queries = module.processoutput(outputdata, inputdata, unit_id,**self.parameters)
                except Exception as e: #pylint: disable=broad-except
                    self.corrector.log("***ERROR*** Exception processing output of " + module_id + ": " + str(e)) #not parallel, acts on same document anyway, should be fairly quick depending on module
                    exc_type, exc_value, exc_traceback = sys.exc_info() #pylint: disable=unused-variable
                    traceback.print_tb(exc_traceback, limit=50, file=sys.stderr)
                    queries = None
                if queries is not None:
                    if isinstance(queries, str):
                        queries = (queries,)
                    for query in queries:
                        try:
                            if self.debug:
                                self.corrector.log("Processing FQL query " + query)
                            q = fql.Query(query)
                            q(self.foliadoc)
                            self.infoqueue.put( module.id)
                        except fql.SyntaxError as e:
                            self.corrector.log("***ERROR*** FQL Syntax error in " + module_id + ":" + str(e)) #not parallel, acts on same document anyway, should be fairly quick depending on module
                            self.corrector.log(" query: " + query)
                            exc_type, exc_value, exc_traceback = sys.exc_info()
                            traceback.print_tb(exc_traceback, limit=50, file=sys.stderr)
                        except fql.QueryError as e:
                            self.corrector.log("***ERROR*** FQL Query error in " + module_id + ":" + str(e)) #not parallel, acts on same document anyway, should be fairly quick depending on module
                            self.corrector.log(" query: " + query)
                            exc_type, exc_value, exc_traceback = sys.exc_info()
                            traceback.print_tb(exc_traceback, limit=50, file=sys.stderr)
                        except Exception as e: #pylint: disable=broad-except
                            self.corrector.log("***ERROR*** Error processing query for " + module_id + ": " + e.__class__.__name__ + " -- " +  str(e)) #not parallel, acts on same document anyway, should be fairly quick depending on module
                            self.corrector.log(" query: " + query)
                            exc_type, exc_value, exc_traceback = sys.exc_info() #pylint: disable=unused-variable
                            traceback.print_tb(exc_traceback, limit=50, file=sys.stderr)

        self.infoqueue.put(None) #signals end

        self.corrector.log("Finalising modules on document") #not parallel, acts on same document anyway, should be fairly quick depending on module
        for module in self.corrector:
            if not self.module_ids or module.id in self.module_ids:
                module.finish(self.foliadoc)



        #Store FoLiA document
        if self.outputfile:
            self.corrector.log("Saving document " + self.outputfile + "....")
            self.foliadoc.save(self.outputfile)
        elif not self.dumpxml and not self.dumpjson:
            self.corrector.log("Saving document " + self.foliadoc.filename + "....")
            self.foliadoc.save()

        if self.dumpxml:
            self.corrector.log("Dumping XML")
            print(self.foliadoc)
        if self.dumpjson:
            self.corrector.log("Dumping JSON")
            print(json.dumps(folia2json(self.foliadoc)))


    def stop(self):
        self._stop = True


class ProcessorThread(Process):
    def __init__(self, corrector,inputqueue, outputqueue, timequeue, **parameters):
        self.corrector = corrector
        self.inputqueue = inputqueue
        self.outputqueue = outputqueue
        self.timequeue = timequeue
        self._stop = False
        self.parameters = parameters
        self.debug  = 'debug' in parameters and parameters['debug']
        self.clients = {} #each thread keeps a bunch of clients open to the servers of the various modules so we don't have to reconnect constantly (= faster)
        self.seqnr = {}
        self.random = random.Random()
        super().__init__()


    def run(self):
        self.corrector.log("[" + str(self.pid) + "] Start of thread")
        while not self._stop:
            try:
                module_id, unit_id, inputdata = self.inputqueue.get(True,self.corrector.settings['timeout'])
            except Empty:
                if self.debug: self.corrector.log(" (inputqueue timed out)")
                self._stop = True
                break
            self.inputqueue.task_done()
            if module_id is None: #signals the last item (there will be one for each thread)
                if self.debug: self.corrector.log(" (end of input queue)")
                self._stop = True
                break
            else:
                module =  self.corrector.modules[module_id]
                if not module.UNITFILTER or module.UNITFILTER(inputdata):
                    if not module.submodule: #modules marked a submodule won't be called by the main process, but are invoked by other modules instead
                        begintime = time.time()
                        module.prepare() #will block until all dependencies are done
                        if module.local:
                            if self.debug:
                                module.log("[" + str(self.pid) + "] (Running " + module.id + " on " + repr(inputdata) + " [local])")
                            outputdata = module.runlocal(inputdata, unit_id, **self.parameters)
                            if outputdata is not None:
                                self.outputqueue.put( (module.id, unit_id, outputdata,inputdata) )
                            if self.debug:
                                duration = round(time.time() - begintime,4)
                                module.log("[" + str(self.pid) + "] (...took " + str(duration) + "s)")
                        else:
                            connected = False
                            if self.debug:
                                module.log("[" + str(self.pid) + "]  (Running " + module.id + " on " + repr(inputdata) + " [remote]")
                            if module.id not in self.seqnr:
                                self.seqnr[module.id] = self.random.randint(0,len(module.servers)) #start with a random sequence nr
                            try:
                                startseqnr = self.seqnr[module.id]
                                while not connected:
                                    #get the server for this sequence nr, sequence numbers ensure rotation between servers
                                    server,port,load = module.getserver(self.seqnr[module.id])   #pylint: disable=unused-variable
                                    self.seqnr[module.id] += 1 #increase sequence number for this module
                                    if self.seqnr[module.id] >= startseqnr + (10 * len(module.servers)):
                                        break #max 10 retries over all servers
                                    try:
                                        if (server,port) not in self.clients:
                                            self.clients[(server,port)] = module.CLIENT(server,port)
                                        client = self.clients[(server,port)]
                                        if self.debug:
                                            module.log("[" + str(self.pid) + "] BEGIN (server=" + server + ", port=" + str(port) + ", client=" + str(client) + ", corrector=" + str(self.corrector) + ", module=" + str(module) + ", unit=" + unit_id + ")")
                                        outputdata = module.runclient(client, unit_id, inputdata,  **self.parameters)
                                        if self.debug:
                                            module.log("[" + str(self.pid) + "] END (server=" + server + ", port=" + str(port) + ", client=" + str(client) + ", corrector=" + str(self.corrector) + ", module=" + str(module) + ", unit=" + unit_id + ")")
                                        if outputdata is not None:
                                            self.outputqueue.put( (module.id, unit_id, outputdata,inputdata) )
                                        #will only be executed when connection succeeded:
                                        connected = True
                                    except ConnectionRefusedError:
                                        module.log("[" + str(self.pid) + "] Server " + server+":" + str(port) + ", module " + module.id + " refused connection, moving on...")
                                        del self.clients[(server,port)]
                                    except Exception: #pylint: disable=broad-except
                                        module.log("[" + str(self.pid) + "] Server communication failed for server " + server +":" + str(port) + ", module " + module.id + ", passed unit " + unit_id + " (traceback follows in debug), moving on...")
                                        exc_type, exc_value, exc_traceback = sys.exc_info() #pylint: disable=unused-variable
                                        traceback.print_tb(exc_traceback, limit=50, file=sys.stderr)
                                        del self.clients[(server,port)]
                            except IndexError:
                                module.log("**ERROR** No servers started for " + module.id)
                            if not connected:
                                module.log("**ERROR** Unable to connect client to server! All servers for module " + module.id + " are down, skipping!")
                            duration = time.time() - begintime
                            self.timequeue.put((module.id, duration))
                            if self.debug:
                                module.log("[" + str(self.pid) + "] (...took " + str(round(duration,4)) + "s)")

        self.corrector.log("[" + str(self.pid) + "] End of thread")


    def stop(self):
        self._stop = True




class Corrector:
    def __init__(self, **settings):
        self.settings = settings
        self.modules = OrderedDict()
        self.verifysettings()


        #Gather servers
        #self.servers = set( [m.settings['servers'] for m in self if not m.local ] )

        self.units = set( [m.UNIT for m in self] )
        self.loaded = False



    def load(self):
        if not self.loaded:
            begintime =time.time()
            self.log("Loading remote modules")
            servers = self.findservers()
            for module, host, port, load in servers:
                self.log("  found " + module + "@" + host + ":" + str(port) + ", load " + str(load))
                self.modules[module].clientload()

            self.log("Loading local modules")
            for module in self:
                if module.local:
                    self.log("Loading " + module.id + " [local]")
                    module.load()

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

        self.root = None
        if 'root' in self.settings:
            for d in self.settings['root'].split(':'):
                if os.path.isdir(os.path.abspath(d)):
                    self.root = os.path.abspath(d)
                    break
            if self.root is None:
                raise Exception("Root directory not found: " + self.settings['root'])
        else:
            self.root = self.settings['root'] = os.path.abspath('.')

        if self.root[-1] != '/': self.root += '/'


        if 'ucto' not in self.settings:
            if 'language' in self.settings:
                for d in UCTOSEARCHDIRS:
                    if os.path.exists(d + "/tokconfig-" + self.settings['language']):
                        self.settings['ucto'] = d + '/tokconfig-' + self.settings['language']
            if 'ucto' not in self.settings:
                for d in UCTOSEARCHDIRS:
                    if os.path.exists(d + "/tokconfig-generic"):
                        self.settings['ucto'] = d + '/tokconfig-generic'
                if 'ucto' not in self.settings:
                    raise Exception("Ucto configuration file not specified and no default found (use setting ucto=)")
        elif not os.path.exists(self.settings['ucto']):
            raise Exception("Specified ucto configuration file not found")


        if 'logfunction' not in self.settings:
            self.settings['logfunction'] = lambda x: print(datetime.datetime.now().strftime("%H:%M:%S.%f") + " " + x,file=sys.stderr)
        self.log = self.settings['logfunction']


        if 'timeout' in self.settings:
            self.settings['timeout'] = int(self.settings['timeout'])
        else:
            self.settings['timeout'] = 120

        if 'threads' not in self.settings:
            self.settings['threads'] = 1

        if 'minpollinterval' not in self.settings:
            self.settings['minpollinterval'] = 60 #60 sec


    def parseconfig(self,configfile):
        self.configfile = configfile #pylint: disable=attribute-defined-outside-init
        config = yaml.load(open(configfile,'r',encoding='utf-8').read())

        if 'inherit' in config:
            baseconfig = yaml.load(open(config['inherit'],'r',encoding='utf-8').read())
            baseconfig.update(config)
            config = baseconfig

        if 'modules' not in config:
            raise Exception("No Modules specified")

        modulespecs = config['modules']
        del config['modules']
        self.settings = config
        self.verifysettings()

        for modulespec in modulespecs:
            if 'enabled' in modulespec and not modulespec['enabled'] or 'disabled' in modulespec and modulespec['disabled']:
                continue
            if not 'id' in modulespec:
                raise Exception("Mising ID in module specification")

            #import modules:
            pymodule = '.'.join(modulespec['module'].split('.')[:-1])
            moduleclass = modulespec['module'].split('.')[-1]
            exec("from " + pymodule + " import " + moduleclass) #pylint: disable=exec-used
            ModuleClass = locals()[moduleclass]
            if 'servers' in modulespec:
                modulespec['servers'] =  tuple( ( (x['host'],x['port']) for x in modulespec['servers']) )
            try:
                module = ModuleClass(self, **modulespec)
            except TypeError:
                raise Exception("Error instantiating " + ModuleClass.__name__)

            self.append(module)


    def run(self,filename,modules,outputfile,dumpxml,dumpjson,**parameters):
        self.load()
        inputqueue = Queue()
        outputqueue = Queue()
        timequeue = Queue()
        infoqueue = Queue()
        waitforprocessors = Lock()
        waitforprocessors.acquire(False)
        datathread = DataThread(self,filename,modules, outputfile, inputqueue, outputqueue, infoqueue,waitforprocessors,dumpxml,dumpjson,**parameters) #fills inputqueue
        datathread.start() #processes outputqueue

        begintime = time.time()
        self.log("Processing modules")

        threads = []
        for _ in range(self.settings['threads']):
            thread = ProcessorThread(self, inputqueue, outputqueue, timequeue,**parameters)
            threads.append(thread)
        self.log(str(len(threads)) + " threads ready.")

        for thread in threads:
            thread.start()

        self.log(str(len(threads)) + " threads started.")
        sys.stderr.flush()

        waitforprocessors.release()
        inputqueue.join()

        inputduration = time.time() - begintime
        self.log("Input queue processed (" + str(inputduration) + "s)")
        outputqueue.put( (None,None,None,None) ) #signals the end of the queue
        datathread.join()
        infopermod = defaultdict(int)
        while True:
            module_id = infoqueue.get(True, self.settings['timeout'])
            if module_id is None:
                break
            infopermod[module_id] += 1
        duration = time.time() - begintime
        timequeue.put((None,None))
        virtualdurationpermod = defaultdict(float)
        callspermod = defaultdict(int)

        virtualduration = 0.0
        while True:
            modid, x = timequeue.get(True, self.settings['timeout'])
            if modid is None:
                break
            else:
                virtualdurationpermod[modid] += x
                callspermod[modid] += 1
                virtualduration += x
        for modid, d in sorted(virtualdurationpermod.items(),key=lambda x: x[1] * -1):
            print("\t"+modid + "\t" + str(round(d,4)) + "s\t" + str(callspermod[modid]) + " calls\t" + str(infopermod[modid]) + " corrections",file=sys.stderr)


        self.log("Cleanup...")
        for thread in threads:
            thread.stop() #custom
        self.log("Processing done (real total " + str(round(duration,2)) + "s , virtual output " + str(virtualduration) + "s, real input " + str(inputduration) + "s)")

        if 'exit' in parameters and parameters['exit']:
            os._exit(0) #very rough exit, hacky... (solves issue #8)


    def __len__(self):
        return len(self.modules)

    def _getitem__(self, modid):
        return self.modules[modid]

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
        if args.parameters:
            parameters = dict(( tuple(p.split('=')) for p in args.parameters))
        else:
            parameters = {}
        if args.modules:
            modules = args.modules.split(',')
        else:
            modules = []

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
        if args.inputfilename != '-':
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
        else:
            if os.path.isdir(args.outputfilename):
                for root, _, files in os.walk(args.outputfilename):
                    for name in files:
                        outputfiles.append(os.path.join(root,name))
            elif os.path.isfile(args.outputfilename):
                outputfiles = [args.outputfilename]




        evaldata = gecco.helpers.evaluation.Evaldata()
        if inputfiles:
            for inputfilename, outputfilename in zip(inputfiles, outputfiles):
                self.run(inputfilename,modules,outputfilename, False,False,**parameters)
                if refdir:
                    referencefilename = os.path.join(refdir, os.path.basename(outputfilename))
                else:
                    referencefilename = args.referencefilename
                gecco.helpers.evaluation.processfile(outputfilename, referencefilename, evaldata)
        else:
            if not outputfiles:
                raise Exception("No output files found and no input files specified")
            for outputfilename in outputfiles:
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




    def startservers(self, module_ids=[]): #pylint: disable=dangerous-default-value
        """Starts all servers on the current host"""

        processes = []

        MYHOSTS = set( [socket.getfqdn() , socket.gethostname(), socket.gethostbyname(socket.gethostname()), '127.0.0.1'] )
        self.log("Starting servers for "  + "/".join(MYHOSTS) )

        if not os.path.exists(self.root + "/run"):
            os.mkdir(self.root + "/run")


        host = socket.getfqdn()

        for module in self:
            if not module.local:
                if not module_ids or module.id in module_ids:
                    portfound = False #port is tasty, let's find port!
                    while not portfound:
                        port = random.randint(10000,65000) #get a random port
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        result = sock.connect_ex(('127.0.0.1',port))
                        if result != 0:
                            portfound = True
                    #Start this server *in a separate subprocess*
                    if self.configfile:
                        cmd = "gecco " + self.configfile + " "
                    else:
                        cmd = sys.argv[0] + " "
                    cmd += "startserver " + module.id + " " + host + " " + str(port)
                    self.log("Starting server " + module.id + "@" + host + ":" + str(port)  + " ...")
                    process = subprocess.Popen(cmd.split(' '),close_fds=True)
                    with open(self.root + "/run/" + module.id + "." + host + "." + str(port) + ".pid",'w') as f:
                        f.write(str(process.pid))
                    processes.append(process)
            else:
                print("Module " + module.id + " is local",file=sys.stderr)

        self.log(str(len(processes)) + " server(s) started.")
        #if processes:
        #    os.wait() #blocking
        #self.log("All servers ended.")

    def stopservers(self, module_ids=[]): #pylint: disable=dangerous-default-value
        MYHOSTS = set( [socket.getfqdn() , socket.gethostname(), socket.gethostbyname(socket.gethostname()), '127.0.0.1'] )
        self.log("Stopping servers for "  + "/".join(MYHOSTS) )

        runpath = self.root + "/run/"
        if not os.path.exists(runpath):
            os.mkdir(runpath)

        self.findservers()

        for module in self.modules.values():
            for host,port,load in module.servers: #pylint: disable=unused-variable
                if not module.local and (not module_ids or module.id in module_ids) and host in MYHOSTS:
                    self.log("Stopping server " + module.id + "@" + host + ":" + str(port) + " ...")
                    with open(runpath + module.id + "." + host + "." + str(port) + ".pid",'r') as f:
                        pid = int(f.read().strip())
                    try:
                        os.kill(pid, 15)
                    except ProcessLookupError:
                        self.log("(process already dead)")
                    os.unlink(runpath + module.id + "." + host + "." + str(port) + ".pid")




    def findservers(self):
        """find all running servers and get the load, will be called by Corrector.load() once before a run"""

        #reset servers for modules
        for module in self.modules.values():
            module.servers = []

        servers = []

        runpath = self.root + "/run/"
        if os.path.exists(runpath):
            for filename in glob(runpath + "/*.pid"):
                filename = os.path.basename(filename)
                fields = filename.split('.')[:-1]
                try:
                    module = self.modules[fields[0]]
                except KeyError:
                    #PID for non-existant module, skip
                    continue
                host = ".".join(fields[1:-1])
                port = int(fields[-1])
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.25) #module servers have to respond very quickly or we ignore them
                try:
                    sock.connect( (host,port) )
                    sock.sendall(b"%GETLOAD%\n")
                    load = float(sock.recv(1024))
                    module.servers.append( (host,port,load) )
                    if hasattr(module,'forcelocal') and  module.forcelocal:
                        module.local = True
                    servers.append( (module.id, host,port,load) )
                except socket.timeout:
                    self.log("Connection to " + module.id + "@" +host+":" + str(port) + " timed out")
                    continue
                except ConnectionRefusedError:
                    self.log("Connection to " + module.id + "@" +host+":" + str(port) + " refused")
                    continue
                except ValueError:
                    self.log("Connection to " + module.id + "@" +host+":" + str(port) + " failed")
                    continue

        return servers


    def startserver(self, module_id, host, port):
        """Start one particular module's server. This method will be launched by server() in different processes"""
        module = self.modules[module_id]
        self.log("Loading module")
        module.load()
        self.log("Running server " + module_id+"@"+host+":"+str(port) + " ...")
        try:
            module.runserver(host,port) #blocking
        except OSError:
            self.log("Server " + module_id+"@"+host+":"+str(port) + " failed, address already in use.")
        self.log("Server " + module_id+"@"+host+":"+str(port) + " ended.")

    def main(self):
        """Parse command line options and run the desired part of the system"""
        parser = argparse.ArgumentParser(description="Gecco is a generic, scalable and modular spelling correction framework", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        subparsers = parser.add_subparsers(dest='command',title='Commands')
        parser_run = subparsers.add_parser('run', help="Run the spelling corrector on the specified input file")
        parser_run.add_argument('-o',dest="outputfile", help="Output filename (if not specified, the input file will be edited in-place",required=False,default="")
        parser_run.add_argument('-O',dest="dumpxml", help="Print result document to stdout as FoLiA XML", required=False)
        parser_run.add_argument('--json',dest="dumpjson", help="Print result document to stdout as JSON", action='store_true',default=False, required=False)
        parser_run.add_argument('filename', help="The file to correct, can be either a FoLiA XML file or a plain-text file which will be automatically tokenised and converted on-the-fly. The XML file will also be the output file. The XML file is edited in place, it will also be the output file unless -o is specified")
        parser_run.add_argument('modules', help="Only run the modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_run.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_run.add_argument('-m',dest='metadata', help="Set extra metadata to be included in the resulting FoLiA document, specify as -m key=value. This options can be issued multiple times ", required=False, action="append")
        parser_run.add_argument('-s',dest='settings', help="Setting overrides, specify as -s setting=value. This option can be issues multiple times.", required=False, action="append")
        parser_run.add_argument('--local', help="Run all modules locally, ignore remote servers", required=False, action='store_true',default=False)
        parser_startservers = subparsers.add_parser('startservers', help="Starts all the module servers, or the modules explicitly specified, on the current host. Issue once for each host.")
        parser_startservers.add_argument('modules', help="Only start server for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_stopservers = subparsers.add_parser('stopservers', help="Stops all the module servers, or the modules explicitly specified,  on the current host. Issue once for each host.")
        parser_stopservers.add_argument('modules', help="Only stop server for modules with the specified IDs (comma-separated list) (if omitted, all modules are run)", nargs='?',default="")
        parser_listservers = subparsers.add_parser('listservers', help="Lists all the module servers on all hosts.")
        parser_startserver = subparsers.add_parser('startserver', help="Start one module's server on the specified port, use 'startservers' instead")
        parser_startserver.add_argument('module', help="Module ID")
        parser_startserver.add_argument('host', help="Host/IP to bind to")
        parser_startserver.add_argument('port', type=int, help="Port")
        parser_train = subparsers.add_parser('train', help="Train modules")
        parser_train.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are trained)", nargs='?',default="")
        parser_train.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_eval = subparsers.add_parser('evaluate', help="Runs the spelling corrector on input data and compares it to reference data, produces an evaluation report")
        parser_eval.add_argument('--local', help="Run all modules locally, ignore remote servers", required=False, action='store_true',default=False)
        parser_eval.add_argument('-s',dest='settings', help="Setting overrides, specify as -s setting=value. This option can be issues multiple times.", required=False, action="append")
        parser_eval.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_eval.add_argument('inputfilename', help="File or directory containing the input (plain text or FoLiA XML). Set to - if the output is already produced and you merely want to evaluate.")
        parser_eval.add_argument('outputfilename', help="File or directory to store the output (FoLiA XML)")
        parser_eval.add_argument('referencefilename', help="File or directory that holds the reference data (FoLiA XML)")
        parser_eval.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are tested)", nargs='?',default="")
        #parser_test = subparsers.add_parser('test', help="Test modules")
        #parser_test.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are tested)", nargs='?',default="")
        #parser_test.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        #parser_tune = subparsers.add_parser('tune', help="Tune modules")
        #parser_tune.add_argument('modules', help="Only train for modules with the specified IDs (comma-separated list) (if omitted, all modules are tuned)", nargs='?',default="")
        #parser_tune.add_argument('-p',dest='parameters', help="Custom parameters passed to the modules, specify as -p parameter=value. This option can be issued multiple times", required=False, action="append")
        parser_reset  = subparsers.add_parser('reset', help="Reset modules, deletes all trained models that have sources. Issue prior to train if you want to start anew.")
        parser_reset.add_argument('modules', help="Only reset for modules with the specified IDs (comma-separated list) (if omitted, all modules are reset)", nargs='?',default="")
        parser_wipe = subparsers.add_parser('wipe', help="Forcibly deletes all knowledge of running servers, use only when you are sure no module servers are running (stop them with stopservers), or they will be orphaned. Used to clean up after a crash.")



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
        self.log("GECCO v" + VERSION + " using " + self.settings['id'])
        if args.command == 'run':
            for module in self.modules.values():
                module.forcelocal = args.local
            if args.parameters: parameters = dict(( tuple(p.split('=')) for p in args.parameters))
            if args.metadata: parameters['metadata'] = dict(( tuple(p.split('=')) for p in args.metadata))
            parameters['exit'] = True #force exit from run(), prevent stale processes
            if args.modules: modules = args.modules.split(',')
            self.run(args.filename,modules,args.outputfile,args.dumpxml, args.dumpjson,**parameters)
        elif args.command == 'startservers':
            if args.modules: modules = args.modules.split(',')
            self.startservers(modules)
        elif args.command == 'stopservers':
            if args.modules: modules = args.modules.split(',')
            self.stopservers(modules)
        elif args.command == 'startserver':
            self.startserver(args.module, args.host, args.port)
        elif args.command == 'listservers' or args.command == 'ls':
            servers = self.findservers()
            if not servers:
                print("No servers are running", file=sys.stderr)
            else:
                for module, host, port, load in servers:
                    print(module + "@" + host + ":" + str(port) + " (load " + str(load) + ")")
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
        elif args.command == 'wipe':
            count = 0
            runpath = self.root + "/run/"
            for filename in glob(runpath + "/*.pid"):
                count += 1
                os.unlink(filename)
            print("Wiped " + str(count) + " servers from memory. If any were still running, they are now orphans!",file=sys.stderr)
        elif not args.command:
            parser.print_help()
        else:
            print("No such command: " + args.command,file=sys.stderr)
            sys.exit(2)
        sys.exit(0)


class LineByLineClient:
    """Simple communication protocol between client and server, newline-delimited"""

    def __init__(self, host, port,timeout=120):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connected = False

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #pylind: disable=attribute-defined-outside-init
        self.socket.settimeout(self.timeout)
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
    The generic RequestHandler class for our server. Instantiated once per connection to the server, invokes the module's run()
    """

    def handle(self):
        while True: #We have to loop so the connection is not closed after one request
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
            if msg == "%GETLOAD%":
                response = str(self.server.module.server_load())
            else:
                response = json.dumps(self.server.module.run(json.loads(msg)))
            #print("Input: [" + msg + "], Response: [" + response + "]",file=sys.stderr)
            if isinstance(response,str):
                response = response.encode('utf-8')
            if response[-1] != 10: response += b"\n"
            self.request.sendall(response)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):

    def handle_error(self,request,client_address):
        print("An error occurred in the server for module " + self.module.id, file=sys.stderr)
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(exc_type, exc_value,file=sys.stderr)
        traceback.print_tb(exc_traceback, limit=50, file=sys.stderr)


class Module:
    UNIT = folia.Document #Specifies on type of input tbe module gets. An entire FoLiA document is the default, any smaller structure element can be assigned, such as folia.Sentence or folia.Word . More fine-grained levels usually increase efficiency.
    UNITFILTER = None #Can be a function that takes a unit and return True if it has to be processed
    CLIENT = LineByLineClient
    SERVER = LineByLineServerHandler

    def __init__(self, parent,**settings):
        self.parent = parent
        self.settings = settings
        self.submodclients = {} #each module keeps a bunch of clients open to the servers of the various submodules so we don't have to reconnect constantly (= faster)
        self.servers = [] #only for the master process, will be populated by it later
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
        for c in self.id:
            if c in ('.',' ','/'):
                raise ValueError("Invalid character in module ID (no spaces, period and slashes allowed): " + self.id)


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

        if 'logfunction' not in self.settings:
            self.settings['logfunction'] = lambda x: print(datetime.datetime.now().strftime("%H:%M:%S.%f") + " [" + self.id + "] " + x,file=sys.stderr) #will be rather messy when multithreaded
        self.log = self.settings['logfunction']

        #Some defaults for FoLiA processing
        if 'set' not in self.settings:
            self.settings['set'] = "https://raw.githubusercontent.com/proycon/folia/master/setdefinitions/spellingcorrection.foliaset.xml"
        if 'class' not in self.settings:
            self.settings['class'] = "nonworderror"
        if 'annotator' not in self.settings:
            self.settings['annotator'] = self.id

        if 'depends' not in self.settings:
            self.settings['depends'] = []

        if 'submodules' not in self.settings:
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


        if 'submodule' not in self.settings:
            self.submodule = False
        else:
            self.submodule = bool(self.settings['submodule'])


        if 'local' not in self.settings:
            self.local = False
        else:
            self.local = bool(self.settings['local'])

        if self.submodule and self.local:
            raise Exception("Module " + self.id + " is a submodule, but no servers are defined, submodules can not be local only")


    def getserver(self, index):
        if not self.servers:
            raise IndexError("No servers")
        index = index % len(self.servers)
        return self.servers[index]

    def getsubmoduleclient(self, submodule):
        #submodule.prepare() #will block until all submod dependencies are done
        #for server,port in submodule.findserver(self.parent.loadbalancemaster):
        #    if (server,port) not in self.submodclients:
        #        self.submodclients[(server,port)] = submodule.CLIENT(server,port)
        #    return self.submodclients[(server,port)]
        #raise Exception("Could not find server for submodule " + submodule.id)
        raise NotImplementedError #may be obsolete

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


    ##### Default callbacks, almost never need to be overloaded:

    def init(self, foliadoc):
        """Initialises the module on the document. This method should set all the necessary declarations if they are not already present. It will be called sequentially and only once on the entire document."""
        if 'set' in self.settings and self.settings['set']:
            if not foliadoc.declared(folia.Correction, self.settings['set']):
                foliadoc.declare(folia.Correction, self.settings['set'])
        return True

    def runserver(self, host, port):
        """Runs the server. Invoked by the Corrector on start. """
        server = ThreadedTCPServer((host, port), self.SERVER)
        server.allow_reuse_address = True #pylint: disable=attribute-defined-outside-init
        server.module = self #pylint: disable=attribute-defined-outside-init
        # Start a thread with the server -- that thread will then fork for each request
        server_thread = Thread(target=server.serve_forever)
        # Exit the server thread when the main thread terminates
        server_thread.setDaemon(True)
        server_thread.start()

        server_thread.join() #block until done

        server.shutdown()

    def server_load(self):
        """Returns a float indicating the load of this server. 0 = idle, 1 = max load, >1 overloaded. Returns normalised system load by default, buy may be overriden for module-specific behaviour."""
        return os.getloadavg()[0] / psutil.cpu_count()


    def runlocal(self, unit_id, inputdata, **parameters):
        """This method gets invoked by the Corrector when the module is run locally."""
        return self.run(inputdata)


    def runclient(self, client, unit_id, inputdata, **parameters):
        """This method gets invoked by the Corrector when it should connect to a remote server, the client instance is passed and already available (will connect on first communication). """
        return json.loads(client.communicate(json.dumps(inputdata)))

    ##### Optional callbacks invoked by the Corrector (defaults may suffice)



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


    ##### Main callbacks invoked by the Corrector that MUST ALWAYS be implemented:

    def prepareinput(self,unit,**parameters):
        """Converts a FoLiA unit to whatever lower-level input-representation the module needs. The representation must be passable over network in JSON. Will be executed serially. May return None to indicate the unit is not to be processed by the module."""
        raise NotImplementedError

    def run(self, inputdata):
        """This methods gets called to turn inputdata into outputdata. It is the part that can be distributed over network and will be executed concurrently. Return value will be automatically serialised as JSON for remote modules. May return None if no output is produced."""
        raise NotImplementedError

    def processoutput(self,outputdata,inputdata,unit_id,**parameters):
        """Processes low-level output data and returns a an FQL query (string) or list/tuple of FQL queries to perform on the data. Executed concurrently. May return None if no query is needed."""
        raise NotImplementedError


    #### Callback invoked by the module itself, MUST be implemented if any loading is done:

    def load(self):
        """Load the requested modules from self.models, module-specific so doesn't do anything by default"""
        pass

    def clientload(self):
        """Load the requested modules from self.models, module-specific so doesn't do anything by default. This is a subset that may be loaded for clients, it should load as little as possible (preferably nothing at all!)"""
        pass

    ######################### FOLIA EDITING ##############################
    #
    # These methods are *NOT* available to module.run(), only to
    # module.processoutput()

    def addsuggestions(self, element_id, suggestions, **kwargs):
        self.log("Adding correction for " + element_id)

        if 'cls' in kwargs:
            cls = kwargs['cls']
        else:
            cls = self.settings['class']

        if isinstance(suggestions,str):
            suggestions = [suggestions]

        q = "EDIT t (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + cls + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        for suggestion in suggestions:
            if isinstance(suggestion, tuple) or isinstance(suggestion, list):
                suggestion, confidence = suggestion
            else:
                confidence = None
            q += " SUGGESTION text \"" + suggestion.replace('"','\\"') + "\""
            if confidence is not None:
                q += " WITH confidence " + str(confidence)

        q += ") FOR ID \"" + element_id + "\" RETURN nothing"
        return q


    def adderrordetection(self, element_id):
        self.log("Adding correction for " + element_id )

        #add the correction
        return "ADD errordetection OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now FOR ID \"" + element_id + "\" RETURN nothing"

    def splitcorrection(self, word_id, suggestions):
        #split one word into multiple

        #suggestions is a list of  ([word], confidence) tuples
        q = "SUBSTITUTE (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        for suggestion, confidence in suggestions:
            q += " SUGGESTION ("
            for i, newword in enumerate(suggestion):
                if i > 0: q += " "
                q += "SUBSTITUTE w WITH text \"" + newword.replace('"','\\"') + "\""
            q += ") WITH confidence " + str(confidence)
        q += ") FOR SPAN ID \"" + word_id + "\""
        q += " RETURN nothing"
        return q

    def mergecorrection(self, newword, originalwords):
        #merge multiple words into one

        q = "SUBSTITUTE (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        q += " SUGGESTION"
        q += " (SUBSTITUTE w WITH text \"" + newword.replace('"','\\"') + "\")"
        #q += " WITH confidence " + str(confidence)
        q += ") FOR SPAN"
        for i, ow in enumerate(originalwords):
            if i > 0: q += " &"
            q += " ID \"" + ow + "\""
        q += " RETURN nothing"
        return q

    def suggestdeletion(self, word_id,merge=False, **kwargs):
        if 'cls' in kwargs:
            cls = kwargs['cls']
        else:
            cls = self.settings['class']
        q = "SUBSTITUTE (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + cls + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        if merge:
            q += " SUGGESTION MERGE DELETION "
        else:
            q += " SUGGESTION DELETION "
        q += ") FOR SPAN ID \"" + word_id + "\""
        q += " RETURN nothing"
        return q

        #----------- OLD (TODO: REMOVE) -----------
        #parent = word.parent
        #index = parent.getindex(word,False)
        #if 'cls' in kwargs:
        #    cls = kwargs['cls']
        #else:
        #    cls = self.settings['class']
        #if index != -1:
        #    self.log(" Suggesting deletion of " + str(word.id))
        #    sugkwargs = {}
        #    if merge:
        #        sugkwargs['merge'] = word.ancestor(folia.StructureElement).id
        #    parent.data[index] = folia.Correction(word.doc, folia.Suggestion(word.doc, **sugkwargs), folia.Current(word.doc, word), set=self.settings['set'],cls=cls, annotator=self.settings['annotator'],annotatortype=folia.AnnotatorType.AUTO, datetime=datetime.datetime.now())
        #else:
        #   self.log(" ERROR: Unable to suggest deletion of " + str(word.id) + ", item index not found")

    def suggestinsertion(self,pivotword_id, text,split=False,mode='PREPEND'):
        q = mode + " (AS CORRECTION OF " + self.settings['set'] + " WITH class \"" + self.settings['class'] + "\" annotator \"" + self.settings['annotator'] + "\" annotatortype \"auto\" datetime now"
        if split:
            q += " SUGGESTION SPLIT (ADD w WITH text \"" + text.replace('"','\\"') + "\") "
        else:
            q += " SUGGESTION (ADD w WITH text \"" + text.replace('"','\\"') + "\") "
        q += ") FOR ID \"" + pivotword_id + "\""
        q += " RETURN nothing"
        return q

        #----------- OLD (TODO: REMOVE) -----------
        #index = pivotword.parent.getindex(pivotword)
        #if index != -1:
        #    self.log(" Suggesting insertion before " + str(pivotword.id))
        #    sugkwargs = {}
        #    if split:
        #        sugkwargs['split'] = pivotword.ancestor(folia.StructureElement).id
        #    doc = pivotword.doc
        #    pivotword.parent.insert(index,folia.Correction(doc, folia.Suggestion(doc, folia.Word(doc,text,generate_id_in=pivotword.parent)), folia.Current(doc), set=self.settings['set'],cls=self.settings['class'], annotator=self.settings['annotator'],annotatortype=folia.AnnotatorType.AUTO, datetime=datetime.datetime.now(), generate_id_in=pivotword.parent))
        #else:
        #    self.log(" ERROR: Unable to suggest insertion before " + str(pivotword.id) + ", item index not found")

def helpmodules():
    #Bit hacky, but it works
    print("Gecco Modules and Settings")
    print("=================================")
    print()
    import gecco.modules #pylint: disable=redefined-outer-name
    for modulefile in sorted(glob(gecco.modules.__path__[0] + "/*.py")):
        modulename = os.path.basename(modulefile).replace('.py','')
        importlib.import_module('gecco.modules.' + modulename)
        for C in dir(getattr(gecco.modules,modulename)):
            C = getattr(getattr(gecco.modules,modulename), C)
            if inspect.isclass(C) and issubclass(C, Module) and hasattr(C,'__doc__') and C.__doc__:
                print("gecco.modules." + modulename + "." + C.__name__)
                print("----------------------------------------------------------------------")
                try:
                    print(C.__doc__)
                except: #pylint: disable=bare-except
                    pass
                print()
    from gecco.helpers.hapaxing import Hapaxer
    print("Hapaxing")
    print("=================================")
    print("The following settings can be added to any module that supports hapaxing:")
    print(Hapaxer.__doc__)



def main():
    try:
        configfile = sys.argv[1]
        if configfile in ("-h","--help"):
            raise IndexError
        elif configfile == "--helpmodules":
            helpmodules()
            sys.exit(0)
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    except IndexError:
        print("Syntax: gecco [configfile.yml] (First specify a config file, for help then add -h)" ,file=sys.stderr)
        print("To see all available modules and parameters: gecco --helpmodules" ,file=sys.stderr)
        sys.exit(2)
    corrector = Corrector(config=configfile)
    corrector.main()


if __name__ == '__main__':
    main()
