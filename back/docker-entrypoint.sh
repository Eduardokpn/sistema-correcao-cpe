#!/bin/sh
# Prepares the database, then hands over to the container's command.
set -e
python -m data.migrate
exec "$@"
