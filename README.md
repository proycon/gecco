========================================================================
GECCO - Generic Enviroment for Context-Aware Correction of Orthography
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
 - Easily extendible by adding modules using the gecco module API
 - Language independent
 - Built-in training pipeline (given corpus input)
 - Built-in testing pipeline (given test corpus), returns simple report of
   evaluation metrics per module
 - Built-in tuning pipeline (given development corpus), tunes and stores parameter
   weights
 - Distributable & Scalable:
    - Load balancing: backend servers can run on multiple host, master process chooses host
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
 - Reimplement all modules within new framework
 - CLAM integration
 - Generic client (separate from main command line tool)


----------------
 Configuration
----------------

A simple Python script forms the configuration of a system, it can be invoked over the command-line and offers a number of subcommands exposing all functionality:

	corrector = Corrector("fowlt", "/path/to/fowlt/", traintxt="train.txt", testtxt="test.txt")
	corrector.append( IGTreeConfusibleModule("confusibles", confusibles=[("then","than"), ("it's","its") ]) )
	corrector.append( ErrorListModule("errorlist", file="errorlist.txt", servers=[("blah",1234),("blah2",1234)]  )
	corrector.append( LexiconModule("lexicon", file="lexicon.txt", servers=[("blah",1235)]  )
	corrector.main()


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
        

	



