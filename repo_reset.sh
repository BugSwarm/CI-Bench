#!/usr/bin/env bash

cp /home/$1/build/failed/$2/$3/model.patch .
cd /home/$1/build/failed/$2/$3/
git clean -fdxq
SHA=$(git log -1 --pretty=format:%h)
git reset --hard $SHA