#!/bin/bash


echo "Updating global dependencies">&2
echo "  The following packages are required: $PKGS">&2
echo "  This will require root privileges, if you do not have these and packages are not available, ask your system administrator to install them and run this script again afterwards.">&2
PKGS="pkg-config git-core make gcc g++ autoconf-archive autotools-dev libicu-dev libxml2-dev libbz2-dev zlib1g-dev libtar-dev libboost-dev python3 python3-pip python-virtualenv"
sudo apt-get update
sudo apt-get install $PKGS 

echo "Creating virtualenv">&2
virtualenv env

echo "Activating virtualenv">&2
. env/bin/activate

export LD_LIBRARY_PATH=$VIRTUAL_ENV/lib:$LD_LIBRARY_PATH

mkdir src
cd src

echo "Installing ticcutils">&2
git clone https://github.com/proycon/ticcutils
cd ticcutils
bash bootstrap.sh
./configure --prefix=$VIRTUAL_ENV
make
make install
cd ..

echo "Installing libfolia">&2
git clone https://github.com/proycon/libfolia
cd libfolia
bash bootstrap.sh
./configure --prefix=$VIRTUAL_ENV
make
make install
cd ..

echo "Installing ucto">&2
git clone https://github.com/proycon/ucto
cd ucto
bash bootstrap.sh
./configure --prefix=$VIRTUAL_ENV
make
make install
cd ..

echo "Installing timbl">&2
git clone https://github.com/proycon/timbl
cd timbl
bash bootstrap.sh
./configure --prefix=$VIRTUAL_ENV
make
make install
cd ..

cd ..

echo "Installing Python dependencies">&2
pip install -r requirements.txt

echo "Installing Gecco">&2
python setup.py install
