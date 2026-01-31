"""add buffer column to faciliies_near_permits table

Revision ID: 0cabe5956fbc
Revises: 954b1d294615
Create Date: 2025-04-10 21:26:21.880554

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0cabe5956fbc"
down_revision: Union[str, None] = "954b1d294615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
