import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SCHEMA_REVISION = '0019'


class Base(DeclarativeBase):
    pass


def engine_from_env():
    url = os.environ['RECARENA_DATABASE_URL']
    if not url.startswith('postgresql+psycopg://'):
        raise ValueError('RecArena requires PostgreSQL with the psycopg driver')
    def integer_setting(name, default, minimum):
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError:
            raise ValueError(f'{name} must be an integer >= {minimum}') from None
        if value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
        return value
    # Each worker owns its pool; budget the sum across workers and shops.
    return create_engine(url, pool_pre_ping=True,
        pool_size=integer_setting('RECARENA_DB_POOL_SIZE', 5, 1),
        max_overflow=integer_setting('RECARENA_DB_MAX_OVERFLOW', 10, 0))


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
