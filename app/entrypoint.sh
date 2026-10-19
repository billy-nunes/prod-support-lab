#!/bin/sh
set -e
# Prometheus multiprocess metrics need a clean scratch dir on every start.
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
exec gunicorn -c gunicorn.conf.py app:app
