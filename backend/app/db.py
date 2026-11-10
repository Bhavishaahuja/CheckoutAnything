# SQLAlchemy 2 engine + sessions. the engine is built on first use, not at import,
# so tests can point it somewhere else first

from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url):
    if url.startswith("sqlite"):
        options = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            # one shared connection, or every session would get its own empty database
            options["poolclass"] = StaticPool
        return create_engine(url, **options)
    # pool_pre_ping so a dropped connection gets replaced instead of failing a request
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_engine():
    return make_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session():
    # for background work (the connect run), which has no request to hang a session on
    return get_sessionmaker()()


def get_session():
    # FastAPI dependency: one session per request, always closed afterwards
    session = new_session()
    try:
        yield session
    finally:
        session.close()


# columns added to orders after the first deploy. create_all only makes missing tables, so a
# database from before these existed gets them added here. all nullable, nothing to backfill
CHECK_COLUMNS = {
    "check_order_id": "INTEGER",
    "check_mandate_id": "INTEGER",
    "review_state": "VARCHAR(20)",
    "check_verdict": "VARCHAR(20)",
    "check_reason": "TEXT",
    "decision_ms": "INTEGER",
}


def add_missing_order_columns(engine):
    existing = set()
    for column in inspect(engine).get_columns("orders"):
        existing.add(column["name"])
    with engine.begin() as connection:
        for name, sql_type in CHECK_COLUMNS.items():
            if name not in existing:
                # names and types come from the dict above, never from a request
                connection.execute(text("ALTER TABLE orders ADD COLUMN " + name + " " + sql_type))


def create_tables():
    # four small tables and no migrations yet, so the API makes them on startup
    from backend.app import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(engine)
    add_missing_order_columns(engine)
