#!/bin/bash

echo "Reset system">&2
gecco test.yml reset
if [ $? -ne 0 ]; then
    echo "Reset failed!!!" >&2
    exit 2
fi

echo "Training system">&2
gecco test.yml train
if [ $? -ne 0 ]; then
    echo "Training failed!!!" >&2
    exit 2
fi

echo "Running system on test document">&2
gecco test.yml run -s threads=1 -p debug=1 --local test/test.txt
if [ $? -ne 0 ]; then
    echo "Run failed!!!" >&2
    exit 2
fi

echo "Running unit tests after local run">&2
python ./test.py test/
if [ $? -ne 0 ]; then
    echo "Unit tests failed!" >&2
    exit 2
fi

echo "Running and evaluating test document">&2
if [ $? -ne 0 ]; then
    gecco test.yml evaluate -s threads=1 -p debug=1 --local test/test.txt test/test.folia.xml example/testreference.folia.xml
    echo "Evaluate failed!!!" >&2
    exit 2
fi

#TODO: client/server run
