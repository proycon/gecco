#!/bin/bash

echo "Reset system">&2
gecco example.yml reset
if [ $? -ne 0 ]; then
    echo "Reset failed!!!" >&2
fi

echo "Training system">&2
gecco example.yml train
if [ $? -ne 0 ]; then
    echo "Training failed!!!" >&2
fi

echo "Running system on test document">&2
gecco example.yml run -s threads=1 -p debug=1 --local example/test.txt
if [ $? -ne 0 ]; then
    echo "Run failed!!!" >&2
fi

echo "Running and evaluating test document">&2
if [ $? -ne 0 ]; then
    gecco example.yml evaluate -s threads=1 -p debug=1 --local example/test.txt /tmp/test.folia.xml example/testreference.folia.xml
    echo "Evaluate failed!!!" >&2
fi
