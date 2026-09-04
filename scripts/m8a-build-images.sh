#!/bin/sh
set -eu

docker build --build-arg SERVICE=benchmark --tag vkr-rca-m8a-benchmark:latest .
docker build --build-arg SERVICE=rca --tag vkr-rca-m8a-rca:latest .
