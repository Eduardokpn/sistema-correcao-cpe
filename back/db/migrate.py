"""Bring the database to the current schema: `python -m db.migrate`.

What the API container runs before starting (see docker-entrypoint.sh), so a
fresh deploy gets its tables and an updated one gets the new migrations without
anyone having to remember `alembic upgrade head`.

One special case: a database created by an old version of the app, back when it
built the tables itself on startup, has the tables but no Alembic revision.
Upgrading it would fail on "table already exists", so it is first stamped as
current - the same one-off fix the README documents.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from db.database import database_url, get_engine

BACK_DIR = Path(__file__).resolve().parent.parent
VERSION_TABLE = "alembic_version"


def _needs_stamp(engine) -> bool:
    tables = set(inspect(engine).get_table_names())
    app_tables = tables - {VERSION_TABLE}
    if not app_tables:
        return False
    if VERSION_TABLE not in tables:
        return True
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT COUNT(*) FROM {VERSION_TABLE}")).scalar() == 0


def migrate() -> None:
    config = Config(str(BACK_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACK_DIR / "db" / "migrations"))

    engine = get_engine(url=database_url())
    try:
        stamp_first = _needs_stamp(engine)
    finally:
        engine.dispose()

    if stamp_first:
        print(
            "[migrate] Tables exist but no Alembic revision is recorded "
            "(database created by an old version). Stamping it as current."
        )
        command.stamp(config, "head")
    command.upgrade(config, "head")
    print("[migrate] Database is at the latest schema.")


if __name__ == "__main__":
    migrate()
