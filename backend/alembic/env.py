"""Alembic environment.

The database URL is taken from the application's own settings rather than from
alembic.ini, so migrations and the app can never disagree about which database
they are talking to. alembic.ini's sqlalchemy.url is left blank deliberately.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings

# Importing models is what populates Base.metadata. Without it autogenerate
# compares against an empty schema and cheerfully proposes dropping every table.
from app.models import Base

config = context.config

# % is the interpolation character in an ini file, so a password containing one
# would break set_main_option. Escaping it costs nothing and fails loudly later
# if skipped.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting — `alembic upgrade head --sql`."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Without compare_type, a column changing from VARCHAR(32) to
            # VARCHAR(64) is silently ignored by autogenerate.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
