"""Database fixtures.

Every other test in this suite is pure-unit: parsers, hashing, and the router are
all functions over plain values. `aggregate_facts()` is not — it is SQL, and the
SQL is the part worth testing, so faking the database would test nothing. These
fixtures give it a real Postgres.

The tests run against a **separate database** (`<name>_test`), created on demand
and never the one holding real statements. Each test runs inside a transaction
that is rolled back afterwards, so tests cannot see each other's rows and the
schema is only built once.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Base


def _urls() -> tuple[str, str, str]:
    """(admin url, test url, test database name).

    The admin connection points at the `postgres` maintenance database, because
    CREATE DATABASE cannot be run while connected to the database being created.
    """
    url = make_url(get_settings().database_url)
    test_name = f"{url.database}_test"
    return (
        url.set(database="postgres").render_as_string(hide_password=False),
        url.set(database=test_name).render_as_string(hide_password=False),
        test_name,
    )


@pytest.fixture(scope="session")
def engine():
    admin_url, test_url, test_name = _urls()

    # CREATE DATABASE cannot run inside a transaction block, hence AUTOCOMMIT.
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{test_name}"'))
    admin.dispose()

    eng = create_engine(test_url)
    with eng.connect() as conn:
        # The embedding columns are of type vector, so the extension has to exist
        # before create_all can build the tables.
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # create_all rather than running the migrations: this fixture is for testing
    # queries, and CI already proves the migrations build the schema from empty.
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Session:
    """A session whose writes are rolled back when the test ends.

    Binding the session to an open connection with an outer transaction — rather
    than letting it manage its own — means the code under test can call
    `commit()` normally and still leave nothing behind.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
