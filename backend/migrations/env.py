from alembic import context

from app.config import load_settings
from app.db import Base, database

if context.is_offline_mode():
    context.configure(url="sqlite://", target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = database(load_settings().db_path)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
