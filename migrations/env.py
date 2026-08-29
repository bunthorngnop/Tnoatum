from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from tnoat_tum_cafe.config import load_settings
from tnoat_tum_cafe.db import Base
from tnoat_tum_cafe import models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
database_url = load_settings().database_url
if database_url.startswith("sqlite:///"):
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if not database_path.is_absolute():
        database_path.parent.mkdir(parents=True, exist_ok=True)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
