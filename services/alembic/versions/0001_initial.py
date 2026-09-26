"""initial schema (ведомо: таблицы = ORM models_db; create_all как миграция 0001)

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ведомо: стартовая схема создаётся приложением (app.database.init_db);
    # миграция выполняет ту же операцию для чистых окружений.
    from app.database import Base
    import app.models_db  # noqa: F401
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.database import Base
    import app.models_db  # noqa: F401
    Base.metadata.drop_all(bind=op.get_bind())