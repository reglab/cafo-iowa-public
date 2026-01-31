"""animal weights

Revision ID: 2b29b7daf396
Revises: 0812e74f9178
Create Date: 2025-04-19 11:28:32.810803

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b29b7daf396"
down_revision: Union[str, None] = "0812e74f9178"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
