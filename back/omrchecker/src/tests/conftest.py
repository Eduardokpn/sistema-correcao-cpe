"""Pin the timezone for the OMR engine tests.

The pipeline names its output files after the local hour (Results_05AM.csv) and
the snapshots were recorded with the clock frozen at 1970-01-01 in India
Standard Time. Without this the file names - and so every snapshot - depend on
the timezone of whoever runs the tests.
"""
import os
import time

import pytest


@pytest.fixture(autouse=True, scope="session")
def _snapshot_timezone():
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Kolkata"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()
