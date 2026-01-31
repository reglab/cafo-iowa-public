"""update foreign keys

Revision ID: 4799c36cae02
Revises: 09a9b0fd9cf5
Create Date: 2025-04-16 17:21:32.747850

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4799c36cae02"
down_revision: Union[str, None] = "09a9b0fd9cf5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
