"""API test harness: a TestClient wired to an isolated in-memory database.

Overrides the app's get_db dependency so every test gets a fresh schema and the
grading data package's real repositories run against SQLite in memory.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import create_app, get_db
from db.database import get_engine, init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Grading files (raw csv, marked sheets) go to a throwaway folder
    monkeypatch.setenv("CPE_ARTIFACTS_DIR", str(tmp_path / "gradings"))
    # A single shared in-memory engine for the life of one test
    engine = get_engine(url="sqlite:///:memory:")
    init_db(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    app = create_app(initialize_schema=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        test_client.engine = engine  # exposed for direct seeding if needed
        test_client.session_factory = TestingSession
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()
