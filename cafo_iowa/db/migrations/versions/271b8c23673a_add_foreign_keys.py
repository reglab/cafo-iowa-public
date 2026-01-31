"""add foreign keys

Revision ID: 271b8c23673a
Revises: 87d151e61df5
Create Date: 2025-04-15 15:59:39.478963

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "271b8c23673a"
down_revision: Union[str, None] = "87d151e61df5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
