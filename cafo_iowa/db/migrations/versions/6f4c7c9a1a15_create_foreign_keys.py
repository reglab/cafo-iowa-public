"""create foreign keys

Revision ID: 6f4c7c9a1a15
Revises: fde291caf256
Create Date: 2025-04-10 13:38:08.560775

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f4c7c9a1a15"
down_revision: Union[str, None] = "fde291caf256"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
