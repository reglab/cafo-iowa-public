"""add primary key to animal weights table

Revision ID: fa769572a3a0
Revises: bbfff30040f6
Create Date: 2025-04-19 11:38:05.094388

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa769572a3a0"
down_revision: Union[str, None] = "bbfff30040f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
