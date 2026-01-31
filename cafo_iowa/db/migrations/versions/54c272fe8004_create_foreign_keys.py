"""create foreign keys

Revision ID: 54c272fe8004
Revises: 6f4c7c9a1a15
Create Date: 2025-04-10 16:17:23.188271

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "54c272fe8004"
down_revision: Union[str, None] = "6f4c7c9a1a15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
