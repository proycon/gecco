English spelling corrector for Gecco - News Crawl Corpus
==========================================================

Make sure you are in the ''gecco/example/newscorpus-en'' directory and follow the
instructions:

1) Call the downloadsourcedata.sh script from within this directory to download the
necessary corpus. The system uses an excerpt of the News Crawl 2012 corpus, obtained from: 
http://www.statmt.org/wmt13/translation-task.html#download

    $ ./downloadsourcedata.sh

2) Train the system (this may take a long time):

    $ gecco newscorpus-en.yml train

3) Start the servers on the current host:

    $ gecco newscorpus-en.yml startservers

4) Run it on some input document

    $ gecco newscorpus-en.yml run input.txt
 
