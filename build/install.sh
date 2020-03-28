#!/bin/bash -e

VIRTUALENV_NAME="memsight"
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# update apt
echo "Updating apt..."
sudo apt-get update >/dev/null || true

# dependencies
echo "Installing dependencies..."
sudo apt-get install -y sudo nano python3-pip time git python3-dev python3-setuptools build-essential
sudo -H python3 -m pip install -U pip

# virtualenv
echo "Creating virtualenv"
sudo -H python3 -m pip install virtualenv virtualenvwrapper
python3 -m pip install virtualenvwrapper

source build/local-pip-install.sh

exit 0
