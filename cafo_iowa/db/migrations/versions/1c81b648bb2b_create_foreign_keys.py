"""create foreign keys

Revision ID: 1c81b648bb2b
Revises: 54c272fe8004
Create Date: 2025-04-10 16:43:26.655115

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c81b648bb2b"
down_revision: Union[str, None] = "54c272fe8004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
