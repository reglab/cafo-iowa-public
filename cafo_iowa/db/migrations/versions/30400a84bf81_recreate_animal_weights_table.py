"""recreate animal weights table

Revision ID: 30400a84bf81
Revises: 2b29b7daf396
Create Date: 2025-04-19 11:29:45.205103

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "30400a84bf81"
down_revision: Union[str, None] = "2b29b7daf396"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
