"""animal weights

Revision ID: 3ee77e402fe5
Revises: ec9c9496a6b9
Create Date: 2025-04-19 11:14:39.506519

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ee77e402fe5"
down_revision: Union[str, None] = "ec9c9496a6b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
