# Alembic runs this for every migration command. run from the repo root:
#   alembic upgrade head
#   alembic revision --autogenerate -m "add something"

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.app import models  # noqa: F401  (registers the tables on Base.metadata)
from backend.app.config import get_settings
from backend.app.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url():
    # tests set sqlalchemy.url directly, everything else reads DATABASE_URL
    url_from_config = config.get_main_option("sqlalchemy.url")
    if url_from_config:
        return url_from_config
    return get_settings().database_url


def run_migrations_offline():
    # "alembic upgrade head --sql" prints the SQL instead of running it
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
