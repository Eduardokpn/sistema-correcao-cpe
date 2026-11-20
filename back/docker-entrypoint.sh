#!/bin/sh
# Prepares the database, then hands over to the container's command.
set -e
python -m db.migrate
exec "$@"
