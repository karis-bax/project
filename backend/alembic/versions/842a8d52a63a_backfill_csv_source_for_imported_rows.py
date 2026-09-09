"""backfill csv source for imported rows

Revision ID: 842a8d52a63a
Revises: a7fb93e3d818
Create Date: 2026-09-09 02:56:55.385905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '842a8d52a63a'
down_revision: Union[str, Sequence[str], None] = 'a7fb93e3d818'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill provenance: rows with an import_hash were CSV imports.

    Pre-fix, CSV-imported rows were written with source='manual' (the default).
    They are identifiable by a non-null import_hash (sync rows use external_id
    and leave import_hash null).
    """
    op.execute(
        "UPDATE transactions SET source = 'csv' "
        "WHERE import_hash IS NOT NULL AND source = 'manual'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE transactions SET source = 'manual' "
        "WHERE import_hash IS NOT NULL AND source = 'csv'"
    )
