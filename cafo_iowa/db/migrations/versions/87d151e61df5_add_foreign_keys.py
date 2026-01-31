"""add foreign keys

Revision ID: 87d151e61df5
Revises: 0cabe5956fbc
Create Date: 2025-04-14 18:04:59.676729

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "87d151e61df5"
down_revision: Union[str, None] = "0cabe5956fbc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
