"""updated relationships

Revision ID: fee5b7795652
Revises: 69f0436cbdaa
Create Date: 2024-08-12 15:22:39.290476

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fee5b7795652"
down_revision: Union[str, None] = "69f0436cbdaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alter the column type to match the foreign key target column
    op.alter_column(
        "label_batches",
        "naip_qt_id",
        existing_type=sa.ARRAY(
            sa.String()
        ),  # Assuming it's currently an array of strings
        type_=sa.String(),  # Convert it to a single string (VARCHAR)
        schema="processed",
        existing_nullable=True,
    )

    # Create the foreign key after altering the column
    op.create_foreign_key(
        None,
        "label_batches",
        "naip21_qt",
        ["naip_qt_id"],
        ["id"],
        source_schema="processed",
        referent_schema="processed",
    )


def downgrade() -> None:
    # Drop the foreign key first
    op.drop_constraint(None, "label_batches", schema="processed", type_="foreignkey")

    # Revert the column type change
    op.alter_column(
        "label_batches",
        "naip_qt_id",
        existing_type=sa.String(),
        type_=sa.ARRAY(sa.String()),  # Revert back to an array of strings
        schema="processed",
        existing_nullable=True,
    )
