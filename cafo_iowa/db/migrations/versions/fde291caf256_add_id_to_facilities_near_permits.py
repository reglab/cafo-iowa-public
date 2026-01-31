"""add id to facilities near permits

Revision ID: fde291caf256
Revises: 18c4ffbd3ae1
Create Date: 2024-03-19 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fde291caf256"
down_revision: Union[str, None] = "18c4ffbd3ae1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add id column as nullable first
    op.add_column(
        "facilities_near_permits",
        sa.Column("id", sa.Integer(), nullable=True),
        schema="processed",
    )

    # Create a sequence for the id column
    op.execute("CREATE SEQUENCE processed.facilities_near_permits_id_seq")

    # Update existing rows with sequential ids
    op.execute(
        """
        UPDATE processed.facilities_near_permits
        SET id = nextval('processed.facilities_near_permits_id_seq')
        WHERE id IS NULL
    """
    )

    # Make the id column not null and set it as the primary key
    op.alter_column(
        "facilities_near_permits",
        "id",
        existing_type=sa.Integer(),
        nullable=False,
        autoincrement=True,
        server_default=sa.text("nextval('processed.facilities_near_permits_id_seq')"),
        schema="processed",
    )

    # Set the sequence to be owned by the id column
    op.execute(
        "ALTER SEQUENCE processed.facilities_near_permits_id_seq OWNED BY processed.facilities_near_permits.id"
    )

    # Add primary key constraint
    op.create_primary_key(
        "facilities_near_permits_pkey",
        "facilities_near_permits",
        ["id"],
        schema="processed",
    )


def downgrade() -> None:
    # Remove primary key constraint
    op.drop_constraint(
        "facilities_near_permits_pkey", "facilities_near_permits", schema="processed"
    )

    # Drop the sequence
    op.execute("DROP SEQUENCE processed.facilities_near_permits_id_seq")

    # Drop the id column
    op.drop_column("facilities_near_permits", "id", schema="processed")
