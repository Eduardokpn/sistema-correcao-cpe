"""Dependencies shared by the routers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.database import get_session_factory


def get_db() -> Session:
    """Request-scoped session dependency."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
