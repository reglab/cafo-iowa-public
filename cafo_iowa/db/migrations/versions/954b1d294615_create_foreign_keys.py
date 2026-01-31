"""create foreign keys

Revision ID: 954b1d294615
Revises: 1c81b648bb2b
Create Date: 2025-04-10 17:11:22.023035

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "954b1d294615"
down_revision: Union[str, None] = "1c81b648bb2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
