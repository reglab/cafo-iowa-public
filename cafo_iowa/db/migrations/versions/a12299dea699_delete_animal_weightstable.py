"""delete animal weightstable

Revision ID: a12299dea699
Revises: 30400a84bf81
Create Date: 2025-04-19 11:30:38.715479

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a12299dea699"
down_revision: Union[str, None] = "30400a84bf81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
