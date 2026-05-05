#!/bin/sh
PLAYDOG_VERSION="0.6.0"
PLAYSCRIBE_VERSION="0.3.0"
INSTALL_TARGET=$arg[1]

if [ -z INSTALL_TARGET ] ; then
  echo "Usage: $arg[0] system|user"
  echo "Install the script system wide or for user only."
  exit 1
fi

if [ INSTALL_TARGET == "system" ] ; then
  cp PlayDog-${PLAYDOG_VERSION}.py /usr/local/bin/
  if [ -f /usr/local/bin/playdog ] ; then
    echo "Previous Version Found. Making Backup."
    rm -f /usr/local/bin/playdog.bak
    mv /usr/local/bin/playdog /usr/local/bin/playdog.bak
  fi
  ln -s /usr/local/bin/PlayDog-${PLAYDOG_VERSION}.py /usr/local/bin/playdog

  cp PlayScribe-${PLAYSCRIBE_VERSION}.py /usr/local/bin/
  if [ -f /usr/local/bin/playscribe ] ; then
    echo "Previous Version Found. Making Backup."
    rm -f /usr/local/bin/playscribe.bak
    mv /usr/local/bin/playscribe /usr/local/bin/playscribe.bak
  fi
  ln -s /usr/local/bin/PlayScribe-${PLAYSCRIBE_VERSION}.py /usr/local/bin/playscribe

  exit 0
fi

if [ INSTALL_TARGET == "user" ] ; then
  echo "Installing for local user"

  exit 0
fi

echo "ERROR: No target found."
exit 1

