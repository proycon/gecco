========================================================================
GECCO - Generic Environment for Context-Aware Correction of Orthography
=======================================================================

    by Maarten van Gompel
    Centre for Language and Speech Technology, Radboud University Nijmegen
    Sponsored by Revisely (http://revise.ly)
    Licensed under the GNU Public License v3

Gecco is a generic modular and distributed framework for spelling correction. Aimed to
build complete context-aware spelling correction system given your own data
set.  Most modules will be language-independent and trainable from a source
corpus. Training is explicitly included in the framework. The framework aims to
easily extendible, modules can be written in Python 3.  Moreover, the framework
is scalable and distributable over multiple servers. 

Given an input text, Gecco will add various suggestions for correction. 

The system can be invoked from the command-line, as a Python binding, as a
RESTful webservice, or through the web application (two interfaces).

**Modules**:
 - Generic built-in modules:
    - **Confusible Module**
        - A confusible module is able to discern which version of often
          confused word is correct given the context. For example, the words
          "then" and "than" are commonly confused in English.
        - Your configuration should specify between which confusibles the module disambiguates.
        - The module is implemented using the IGTree classifier (a k-Nearest Neighbour
          approximation) in Timbl.
    - **Suffix Confusible Module**
        - A variant of the confusible module that checks commonly confused morphological
          suffixes, rather than words.
        - Your configuration should specify between which suffixes the module disambiguates
        - The module is implemented using the IGTree classifier (a k-Nearest Neighbour
          approximation) in Timbl.
    - **Language Model Module**
        - A language model predicts what words are likely to follow others,
          similar to predictive typing applications commonly found on
          smartphones.
        - The module is implemented using the IGTree classifier (a k-Nearest Neighbour
          approximation) in Timbl.
    - **Aspell Module**
        - Aspell is open-source lexicon-based software for spelling correction.
          This module enables aspell to be used from gecco. This is not a
          context-sensitive method.
    - **Lexicon Module**
        - The lexicon module enables you to automatically generate a lexicon
          from corpus data and use it. This is not a context-sensitive method.
        - Typed words are matched against the lexicon and the module will come
          with suggestions within a certain Levenshtein distance. 
    - **Errorlist Module**
        - The errorlist module is a very simple module that checks whether a
          word is in a known error list, and if so, provides the suggestions
          from that list. This is not a context-sensitive method.
    - **Split Module**
        - The split module detects words that are split but should be written
          together.
        - Implemented using Colibri Core
    - **Runon Module**
        - The runon module detects words that are written as one but should be
          split.
        - Implemented using Colibri Core
    - **Punctuation & Recase Module**
        - The punctuation & recase module attempts to detect missing
          punctuation, superfluous punctuation, and missing capitals.
        - The module is implemented using the IGTree classifier (a k-Nearest Neighbour
          approximation) in Timbl.
 - Modules suggested but not implemented yet:
    - *Language Detection Module*
        - (Not written yet, option for later)
    - *Sound-alike Module*
        - (Not written yet, option for later)

**Features**
 - Easily extendible by adding modules using the gecco module API
 - Language independent
 - Built-in training pipeline (given corpus input): Create models from sources
 - Built-in testing pipeline (given an error-annotated test corpus), returns report of evaluation metrics per module
 - **Distributed**, **Multithreaded** & **Scalable**:
    - Load balancing: backend servers can run on multiple hosts, master process chooses host
        with least load
    - Master process always on a single host (reduces network load and increases performance)
        - Multithreaded, modules can be invoked in parallel
    - Module servers themselves may be multithreaded
 - Input and output is **FoLiA XML** (http://proycon.github.io/folia)
     - Automatic input conversion from plain text using ucto

Gecco is the successor of Valkuil.net and Fowlt.net.
 
-----------------------
Installation
-----------------------

Gecco relies on a large number of dependencies, including but not limited to:

Dependencies:
 - *Generic*:
  - python 3.3 or higher
  - pynlpl (https://github.com/proycon/pynlpl), needed for FoLiA support
    (https://proycon.github.io/folia)
  - python-ucto & ucto (in turn depending on libfolia, ticcutils)
 - *Module-specific*:
  - Timbl (http://ilk.uvt.nl/timbl)
  - Colibri Core (https://github.com/proycon/colibri-core/)
  - Aspell (http://aspell.net)
  - aspell-python-py3
  - python-timbl
 - *Webservice*:
  - CLAM (port to Python 3) (https://proycon.github.io/clam)

To install Gecco, we *strongly* recommend you to use our LaMachine distribution:
https://github.com/proycon/lamachine .

LaMachine includes Gecco and can be run in multiple ways: as a virtual machine,
as a docker app, or as a compilation script setting up a Python virtual
environment.

Gecco uses memory-based technologies, and depending on the models you train,
make take up considerable memory. For we recommend *at least* 16MB RAM. For
various modules, model size may be reduced by increasing frequency thresholds,
but this will come at the cost of reduced accuracy.

Gecco will only run on POSIX-complaint operating systems (i.e. Linux, BSD, Mac OS X), not on Windows.

----------------
Configuration
----------------

To build an actual spelling correction system, you need to have corpus sources
and create a gecco configuration that enable the modules you desire with the
parameters you want. 

A Gecco system consists of a configuration, either in the form of a simple Python
script or an external YAML configuration file.

Example YAML configuration:

    name: fowlt
    path: /path/to/fowlt
    language: en
    modules:
        - module: gecco.modules.confusibles.TIMBLWordConfusibleModule
          id: confusibles
          source: 
            - train.txt
          model: 
            - confusible.model
          servers:
              - host: blah
                port: 12345
              - host: blah2
                port: 12345
          confusible: [then,than]

Alternatively, the configuration can be done in Python directly, in which case
the script will be the tool that exposes all functionality:

    from gecco import Corrector
    from gecco.modules.confusibles import TIMBLWordConfusibleModule

	corrector = Corrector(id="fowlt", root="/path/to/fowlt/")
	corrector.append( TIMBLWordConfusibleModule("thenthan", source="train.txt",test_crossvalidate=True,test=0.1,tune=0.1,model="confusibles.model", confusible=('then','than')))
	corrector.append( TIMBLWordConfusibleModule("its", source="train.txt",test_crossvalidate=True,test=0.1,tune=0.1,model="confusibles.model", confusible=('its',"it's")))
	corrector.append( TIMBLWordConfusibleModule("errorlist", source="errorlist.txt",model="errorlist.model", servers=[("blah",1234),("blah2",1234)]  )
	corrector.append( TIMBLWordConfusibleModule("lexicon", source=["lexicon.txt","lexicon2.txt"],model=["lexicon.model","lexicon2.model"], servers=[("blah",1235)]  )
	corrector.main()

---------------------
Command line usage
---------------------

Invoke all gecco functionality through a single command line tool

    $ gecco myconfig.yml [subcommand] 

or 

    $ myspellingcorrector.py [subcommand]


Syntax:

    usage: gecco [-h]
                {run,startservers,stopservers,startserver,train,evaluate,reset}
                ...

    Gecco is a generic, scalable and modular spelling correction framework

    Commands:
    {run,startservers,stopservers,startserver,train,evaluate,reset}
        run                 Run the spelling corrector on the specified input file
        startservers        Starts all the module servers that are configured to
                            run on the current host. Issue once for each host.
        stopservers         Stops all the module servers that are configured to
                            run on the current host. Issue once for each host.
        startserver         Start one module's server on the specified port, use
                            'startservers' instead
        train               Train modules
        evaluate            Runs the spelling corrector on input data and compares
                            it to reference data, produces an evaluation report
        reset               Reset modules, deletes all trained models that have
                            sources. Issue prior to train if you want to start
                            anew.
 

----------------
Server setup
---------------

On each host that serves one or more modules, a `gecco myconfig.yml
startservers` has to be issued. Modules not set up to run as a server will
simply be started and invoked locally on request, which is something you want
to prevent as this usually takes up too much time.

`gecco run <input.folia.xml>` is executed to process a given FoLiA document or
plaintext document, it starts a master process that will invoke all the
modules, which may be distributed over multiple servers. If multiple server
instances of the same module are available, the load will be distributed over
them. Output will be delivered in the FoLiA XML format and will contain
suggestions for correction.  

----------------------------------------
Gecco as a webservice
----------------------------------------

RESTUL webservice access will be available through CLAM. This, however, is currently not implemented yet.

------------------------------
Gecco as a web-application
------------------------------

A web-application will eventually be available, modelled after Valkuil.net/Fowlt.net.


	



