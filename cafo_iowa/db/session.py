import enum
from urllib.parse import quote_plus

import sqlalchemy
import sqlalchemy.orm

import cafo_iowa.utils.io as io
from cafo_iowa.db.models import Base


def get_engine() -> sqlalchemy.engine.Engine:
    """Get a SQLAlchemy engine for the Oracle database."""
    user, password, host, port, db = (
        io.getenv("PGUSER"),
        io.getenv("PGPASSWORD"),
        io.getenv("PGHOST"),
        io.getenv("PGPORT"),
        io.getenv("PGDATABASE"),
    )
    if not user:
        raise ValueError("Missing PGUSER environment variable.")
    if not password:
        raise ValueError("Missing PGPASSWORD environment variable.")
    if not host:
        raise ValueError("Missing PGHOST environment variable.")
    if not port:
        raise ValueError("Missing PGPORT environment variable.")
    if not db:
        raise ValueError("Missing PGDATABASE environment variable.")
    assert all((user, password, host, port, db)), (
        "Missing environment variable(s) for PostgreSQL connection."
        "Check PGUSER, PGPASSWORD, PGHOST, PGPORT, PGDATABASE."
    )

    return sqlalchemy.create_engine(
        f"postgresql+psycopg2://{io.getenv('PGUSER')}:"
        f"{quote_plus(io.getenv('PGPASSWORD'))}@"
        f"{io.getenv('PGHOST')}:"
        f"{io.getenv('PGPORT')}/"
        f"{io.getenv('PGDATABASE')}",
        echo=io.getenv("SQL_ECHO", "false").lower() == "true",
    )


def get_session() -> sqlalchemy.orm.Session:
    """Get a SQLAlchemy session for the database."""
    engine = get_engine()

    sess = sqlalchemy.orm.sessionmaker(bind=engine)()
    return sess


def execute_with_session(func, *args, **kwargs):
    with get_session() as session:
        return func(session=session, *args, **kwargs)
