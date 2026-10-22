# SQLAlchemy 2 engine + sessions. the engine is built on first use, not at import,
# so the app and tests can start without a database

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    # pool_pre_ping so a dropped connection (Render free tier sleeps) gets replaced
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session():
    # FastAPI dependency: one session per request, always closed afterwards
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
