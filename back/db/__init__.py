"""Data-access package for the CPE OMR system.

Holds the SQLAlchemy models, the engine/session factory and the repository layer
that both the FastAPI service and CLI scripts import. Kept free of any OMR or web
concern so it stays a plain, reusable persistence library.
"""
from db.database import (
    get_engine,
    get_session,
    session_scope,
    init_db,
    DATABASE_URL_ENV,
    DEFAULT_SQLITE_PATH,
)
from db.models import (
    Base,
    Class,
    Student,
    Exam,
    Subject,
    Subtopic,
    Question,
    Sheet,
    Answer,
    VERDICT_CORRECT,
    VERDICT_INCORRECT,
    VERDICT_UNMARKED,
)

__all__ = [
    "get_engine",
    "get_session",
    "session_scope",
    "init_db",
    "DATABASE_URL_ENV",
    "DEFAULT_SQLITE_PATH",
    "Base",
    "Class",
    "Student",
    "Exam",
    "Subject",
    "Subtopic",
    "Question",
    "Sheet",
    "Answer",
    "VERDICT_CORRECT",
    "VERDICT_INCORRECT",
    "VERDICT_UNMARKED",
]
