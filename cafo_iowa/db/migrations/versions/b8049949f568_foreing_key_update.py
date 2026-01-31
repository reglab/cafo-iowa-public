"""foreing key update

Revision ID: b8049949f568
Revises: fa769572a3a0
Create Date: 2025-04-21 12:54:40.940340

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8049949f568"
down_revision: Union[str, None] = "fa769572a3a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
