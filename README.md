========================================================================
GECCO - Generic Environment for Context-Aware Correction of Orthography
=======================================================================

A generic modular framework for spelling correction

Features:
 - Generic built-in modules:
    - Confusible Module
        - Timbl-based (IGTree)
        - allows multiple independent confusibles to be combined in one model (increases performance, allow single socket)
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
        - Multithreaded, modules can be run in parallel
 - Input and output is FoLiA XML
     - Automatic input conversion from plain text using ucto
   
Dependencies:
 - Python 3:
  - pynlpl (for FoLiA)
  - python-timbl
  - python-ucto
 - Python 2:
  - CLAM (No python 3 support yet unfortunately)
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

A simple Python script forms the configuration of a system, it can be invoked over the command-line and offers a number of subcommands exposing all functionality:

	corrector = Corrector("fowlt", "/path/to/fowlt/")
	corrector.append( IGTreeConfusibleModule("thenthan", source="train.txt",test_crossvalidate=True,test=0.1,tune=0.1,model="confusibles.model", confusible=('then','than')))
	corrector.append( IGTreeConfusibleModule("its", source="train.txt",test_crossvalidate=True,test=0.1,tune=0.1,model="confusibles.model", confusible=('its',"it's")))
	corrector.append( ErrorListModule("errorlist", source="errorlist.txt",model="errorlist.model", servers=[("blah",1234),("blah2",1234)]  )
	corrector.append( LexiconModule("lexicon", source=["lexicon.txt","lexicon2.txt"],model=["lexicon.model","lexicon2.model"], servers=[("blah",1235)]  )

	corrector.main()

The configuration can also be in an external YAML file and read on the fly:

 corrector = Corrector(config="blah.yml")
 corrector.main()


YAML configuration:

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
          confusible: [then,than]

---------------------
Command line usage
---------------------

Invoke all gecco functionality through a single command line tool

 $ gecco myconfig.yml [subcommand] 

or 

 $ myspellingcorrector.py [subcommand]


Subcommands:

 * reset [$id] -- delete models for all modules or specified module
 * train [$id] -- train all modules or specified module
 * test [$id] -- test all modules or specified module
 * tune [$id] -- tune all modules or specified module

 * start [$id] -- Start module servers (all or specified) that match the
    current host, this will have to be run for each host 

 * run [filename] [$id] [$parameters] -- Run (all or specified module) on specified FoLiA document
 
 * build -- Builds CLAM configuration and wrapper and django webinterface
 * runserver -- Starts CLAM webservice (using development server, not
   recommended for production use) and Django interface (using development
   server, not for producion use)

---------------
Architecture
---------------

    class Corrector:
        init(id, root, **settings)

        settings:
            traintxt: plaintext corpus for training
            tunetxt: plaintext corpus for development
            testtxt: plaintext corpus for testing

        modules #list

        start(id=None) 

        train(id=None) 

        test(id=None)

        tune(id=None)

        append(module) #adds a module

        __getitem__(id) #gets a module by ID

        run(foliadoc, id=None,**parameters)

        build()

        runserver()

        main()


    class Module
        init(id,**settings)
        train()
        tune()
        test()
        start()

        save(filename)
        load(filename)

        run(foliadoc, **parameters)



    class IGTreeConfusibleModule(Module):
        #**settings expects:
        #	confusibles: list of words (2 at least)
        
    class ColibriConfusibleModule(Module):
        #**settings expects:
        #	confusibles: list of words (2 at least)


    class LoadBalancer:
        init(host,port)
        getload()
        

	



