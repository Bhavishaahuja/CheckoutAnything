# SQLAlchemy 2 engine + sessions. the engine is built on first use, not at import,
# so tests can point it somewhere else first

from functools import lru_cache

from sqlalchemy import create_engine
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


def create_tables():
    # six small tables and no migrations yet, so the API makes them on startup
    from backend.app import models  # noqa: F401

    Base.metadata.create_all(get_engine())
