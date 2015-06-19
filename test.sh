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

echo "Running system">&2
gecco example.yml run -s threads=1 -p debug=1 --local example/test.txt
if [ $? -ne 0 ]; then
    echo "Run failed!!!" >&2
fi

