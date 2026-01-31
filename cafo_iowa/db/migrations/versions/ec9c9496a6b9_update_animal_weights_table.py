"""update animal weights table

Revision ID: ec9c9496a6b9
Revises: 8c8e4ff2620b
Create Date: 2025-04-19 11:09:48.559506

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ec9c9496a6b9"
down_revision: Union[str, None] = "8c8e4ff2620b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
