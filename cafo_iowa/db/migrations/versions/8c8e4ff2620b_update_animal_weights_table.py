"""update animal weights table

Revision ID: 8c8e4ff2620b
Revises: 120e86f88189
Create Date: 2025-04-19 11:00:35.666793

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c8e4ff2620b"
down_revision: Union[str, None] = "120e86f88189"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
