========================================================================
GECCO - Generic Environment for Context-Aware Correction of Orthography
=======================================================================

A generic modular framework for spelling correction. Aimed to quickly build a
complete context-aware spelling correction system given your own data set.
Most components will be language independent and trainable from a source
corpus, training is explicitly included in the framework. The framework aims
to easily extendible, modules can be written in Python 3. Moreover, the framework
is scalable and distributable over multiple servers. 

The system can be invoked from the command-line, as a Python binding, as a RESTful webservice, or
through the web application (two interfaces).


Features:
 - Generic built-in modules (all will have a server mode):
    - Confusible Module
        - Timbl-based (IGTree)
        - alternative: Colibri-Core based
    - Language Model Module
        - WOPR based
        - alternative: SRILM-based, Colibri-Core based
    - Aspell Module
    - Lexicon Module
    - Errorlist Module
    - Split Module
    - Runon Module
    - Garbage Module
    - Punctuation Module (new)
    - Language Detection
 - Easily extendible by adding modules using the gecco module API
 - Language independent
 - Built-in training pipeline (given corpus input)
 - Built-in testing pipeline (given test corpus), returns simple report of
   evaluation metrics per module
 - Built-in tuning pipeline (given development corpus), tunes and stores parameter
   weights
 - Distributable & Scalable:
    - Load balancing: backend servers can run on multiple hosts, master process chooses host
        with least load
    - Master process always on a single host (reduces network load and increases performance)
        - Multithreaded, modules can be invoked in parallel
 - Input and output is FoLiA XML
     - Automatic input conversion from plain text using ucto
   
Dependencies:
 - Python 3:
  - pynlpl (for FoLiA)
  - python-timbl
  - python-ucto
  - CLAM (port to Python 3 still in progress)
 - Module-specific:
  - Timbl
  - WOPR
  - Aspell
  - colibri-core (py3)
 - ucto

Workload:
 - Build framework
 - Abstract Module
   - Client/server functionality
 - Load balancing
 - Reimplement all modules within new framework, in Python. Using python-timbl
 - CLAM integration
 - Generic client (separate from main command line tool)


----------------
 Configuration
----------------

A Gecco system consists of a configuration, either in the form of a simple Python
script or an external. YAML configuration file.

	corrector = Corrector(id="fowlt", root="/path/to/fowlt/")
	corrector.append( IGTreeConfusibleModule("thenthan", source="train.txt",test_crossvalidate=True,test=0.1,tune=0.1,model="confusibles.model", confusible=('then','than')))
	corrector.append( IGTreeConfusibleModule("its", source="train.txt",test_crossvalidate=True,test=0.1,tune=0.1,model="confusibles.model", confusible=('its',"it's")))
	corrector.append( ErrorListModule("errorlist", source="errorlist.txt",model="errorlist.model", servers=[("blah",1234),("blah2",1234)]  )
	corrector.append( LexiconModule("lexicon", source=["lexicon.txt","lexicon2.txt"],model=["lexicon.model","lexicon2.model"], servers=[("blah",1235)]  )

	corrector.main()

If the Python script is used, the script is the command line tool that exposes
all funcionality of the system.

Example YAML configuration:

    name: fowlt
    path: /path/to/fowlt
    language: en
    modules:
        - module: IGTreeConfusibleModule
          id: confusibles
          source: train.txt
          test: test.txt                        [or a floating point value to automatically reserve a portion of the train set]
          tune: tune.txt                        [or a floating point value to automatically reserve a portion of the train set]
          model: confusible.model
          servers:
              - host: blah
                port: 12345
              - host: blah2
                port: 12345
          confusible: [then,than]

---------------------
Command line usage
---------------------

Invoke all gecco functionality through a single command line tool

    $ gecco myconfig.yml [subcommand] 

or 

    $ myspellingcorrector.py [subcommand]


Subcommands:

 * `reset [$id]` -- delete models for all modules or specified module
 * `train [$id]` -- train all modules or specified module
 * `test [$id]` -- test all modules or specified module
 * `tune [$id]` -- tune all modules or specified module

 * `start [$id]` -- Start module servers (all or specified) that match the
    current host, this will have to be run for each host 

 * `run [filename] [$id] [$parameters]` -- Run (all or specified module) on specified FoLiA document
 
 * `build` -- Builds CLAM configuration and wrapper and django webinterface
 * `runserver` -- Starts CLAM webservice (using development server, not
   recommended for production use) and Django interface (using development
   server, not for producion use)

----------------
Server setup
---------------

On each server that runs one or more modules a `gecco myconfig.yml start` has
to be issued to start the modules. Modules not set up to run as a server will
simply be started and invoked locally on request.

`gecco run <input.folia.xml>` is executed on the master server to process a
given FoLiA document or plaintext document, it will invoke all the modules
which may be distributed over multiple servers, if multiple server instances of
the same module are running, the one with the lowest load is selected. Output will
be delivered in FoLiA XML.

RESTUL webservice access is available through CLAM, the CLAM service can be
automatically generated. Web-application access is available either through the
generic interface in CLAM, as well as the more user-friendly interface of
Valkuil/Fowlt.


	



