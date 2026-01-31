"""animal weights

Revision ID: e83c3f4400ee
Revises: 3ee77e402fe5
Create Date: 2025-04-19 11:20:13.636259

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e83c3f4400ee"
down_revision: Union[str, None] = "3ee77e402fe5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
