# -*- coding: utf-8 -*-
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from pintel_server.config import settings
from pintel_server.db import Base, TZDateTime
from pintel_server import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Наш TZDateTime в миграциях записываем как обычный DateTime(timezone=True)."""
    if type_ == "type" and isinstance(obj, TZDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_item=render_item, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_item=render_item,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
