"""add animal weightstable and urban

Revision ID: dd74f72f72ec
Revises: 519cb1eb9855
Create Date: 2025-04-19 11:33:01.523345

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd74f72f72ec"
down_revision: Union[str, None] = "519cb1eb9855"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
