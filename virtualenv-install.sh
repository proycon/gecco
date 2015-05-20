#!/bin/bash

error () {
    echo "An error occured during installation!" >&2
    echo $1 >&2
    exit 2
}

echo "Updating global dependencies">&2
echo "  The following packages are required: $PKGS">&2
echo "  This will require root privileges, if you do not have these and packages are not available, ask your system administrator to install them and run this script again afterwards.">&2
PKGS="pkg-config git-core make gcc g++ autoconf-archive autotools-dev libicu-dev libxml2-dev libbz2-dev zlib1g-dev libtar-dev libboost-dev python3 python3-pip python-virtualenv"
sudo apt-get update
sudo apt-get install $PKGS 



echo "Creating virtualenv">&2
virtualenv --no-site-packages --python=python3 env

echo "Activating virtualenv">&2
. env/bin/activate

echo "Virtual Environment is $VIRTUAL_ENV">&2
export LD_LIBRARY_PATH=$VIRTUAL_ENV/lib:$LD_LIBRARY_PATH

if [ -d src ]; then
    rm -Rf src
fi
mkdir src
cd src

echo "Installing ticcutils">&2
git clone https://github.com/proycon/ticcutils
cd ticcutils
echo $PWD >&2
. bootstrap.sh || error "ticcutils bootstrap failed"
./configure --prefix=$VIRTUAL_ENV || error "ticcutils configure failed"
make || error "ticcutils make failed"
make install || error "ticcutils make install failed"
cd ..

echo "Installing libfolia">&2
git clone https://github.com/proycon/libfolia
cd libfolia
. bootstrap.sh || error "libfolia bootstrap failed"
./configure --prefix=$VIRTUAL_ENV || error "libfolia configure failed"
make || error "libfolia make failed"
make install || error "libfolia make install failed"
cd ..

echo "Installing ucto">&2
git clone https://github.com/proycon/ucto
cd ucto
. bootstrap.sh || error "ucto bootstrap failed"
./configure --prefix=$VIRTUAL_ENV || error "ucto configure failed"
make || error "ucto make failed"
make install || error "ucto make install failed"
cd ..

echo "Installing timbl">&2
git clone https://github.com/proycon/timbl
cd timbl
. bootstrap.sh || error "timbl bootstrap failed"
./configure --prefix=$VIRTUAL_ENV || error "timbl configure failed"
make || error "timbl make failed"
make install || error "timbl make install failed"
cd ..

cd ..

echo "Installing Python dependencies">&2
pip install Cython #first we do cython, otherwise python-ucto will fail
pip install -r requirements.txt || error "Unable to install all python dependencies"

echo "Installing Gecco">&2
python setup.py install || error "Unable to install gecco"
