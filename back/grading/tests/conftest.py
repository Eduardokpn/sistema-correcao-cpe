"""Reuse the data package's in-memory DB fixtures for grading tests."""
import pytest
from sqlalchemy.orm import Session, sessionmaker

from db.database import get_engine, init_db


@pytest.fixture
def session(request) -> Session:
    engine = get_engine(url="sqlite:///:memory:")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
