"""animal weights

Revision ID: 0812e74f9178
Revises: e83c3f4400ee
Create Date: 2025-04-19 11:25:58.791769

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0812e74f9178"
down_revision: Union[str, None] = "e83c3f4400ee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
