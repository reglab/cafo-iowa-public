"""update foreign keys

Revision ID: 120e86f88189
Revises: 4799c36cae02
Create Date: 2025-04-16 18:40:24.796578

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "120e86f88189"
down_revision: Union[str, None] = "4799c36cae02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
