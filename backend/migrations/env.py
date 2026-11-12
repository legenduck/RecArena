from alembic import context
from recarena_platform.db import Base, engine_from_env
from recarena_platform.db import catalog as models  # register metadata for Alembic comparisons
from recarena_platform.db import runtime as runtime_models

engine = engine_from_env()
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
