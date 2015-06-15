#!/bin/bash

echo "Training system">&2
gecco example.yml train
if [ $? -ne 0 ]; then
    echo "Training failed!!!" >&2
fi



