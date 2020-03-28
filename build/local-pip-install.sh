#!/bin/bash -e

VIRTUALENV_NAME="memsight"
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

python3 -m pip install virtualenvwrapper virtualenv

# virtualenv
echo "Creating virtualenv"

export WORKON_HOME=$HOME/.virtualenvs

source /usr/share/virtualenvwrapper/virtualenvwrapper.sh || echo
source /usr/local/bin/virtualenvwrapper.sh || echo

rmvirtualenv $VIRTUALENV_NAME || true
mkvirtualenv --python=$(which python3) $VIRTUALENV_NAME || true

# angr stuff
echo "Installing angr..."
python3 -m pip install --no-deps -r $DIR/../requirements.txt
#pip install angr==7.8.8.1
#pip install -I --no-use-wheel capstone==3.0.4 # fix error import
#pip install --force-reinstall angr claripy

# patches
echo "Applying patches"
cd ~/.virtualenvs/$VIRTUALENV_NAME/lib/python3.7/site-packages/

# track angr changes
cd angr; git init; git add . >/dev/null; git commit -a -m "initial import" >/dev/null; cd ..
cd claripy; git init; git add . >/dev/null; git commit -a -m "initial import" >/dev/null; cd ..

for p in $DIR/0*.patch; do
    patch -p1 < $p
done

echo
echo "Created virtualenv $VIRTUALENV_NAME. Work on it using: workon $VIRTUALENV_NAME"
echo

exit 0
