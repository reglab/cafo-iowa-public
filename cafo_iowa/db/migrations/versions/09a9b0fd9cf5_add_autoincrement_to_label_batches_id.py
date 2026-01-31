"""add_autoincrement_to_label_batches_id

Revision ID: 09a9b0fd9cf5
Revises: aaa2814f404b
Create Date: 2024-04-16 00:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "09a9b0fd9cf5"
down_revision: Union[str, None] = "aaa2814f404b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create a new sequence for the id column
    op.execute("CREATE SEQUENCE IF NOT EXISTS label_batches_id_seq")

    # Set the default value of the id column to use the sequence
    op.execute(
        "ALTER TABLE processed.label_batches ALTER COLUMN id SET DEFAULT nextval('label_batches_id_seq')"
    )

    # Set the sequence's current value to the maximum id value
    op.execute(
        "SELECT setval('label_batches_id_seq', COALESCE((SELECT MAX(id) FROM processed.label_batches), 0) + 1, false)"
    )


def downgrade() -> None:
    # Remove the default value from the id column
    op.execute("ALTER TABLE processed.label_batches ALTER COLUMN id DROP DEFAULT")

    # Drop the sequence
    op.execute("DROP SEQUENCE IF EXISTS label_batches_id_seq")
