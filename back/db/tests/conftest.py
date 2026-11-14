"""Shared fixtures for the data-package tests.

Every test runs against a throwaway in-memory SQLite database so nothing touches
the developer's real cpe_omr.db and tests stay isolated from one another.
"""
import pytest
from sqlalchemy.orm import Session, sessionmaker

from db.database import get_engine, init_db


@pytest.fixture
def engine():
    # A fresh in-memory database per test
    engine = get_engine(url="sqlite:///:memory:")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
