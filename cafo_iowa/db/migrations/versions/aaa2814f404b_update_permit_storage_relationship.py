"""update permit storage relationship

Revision ID: aaa2814f404b
Revises: 271b8c23673a
Create Date: 2025-04-15 17:05:16.397596

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aaa2814f404b"
down_revision: Union[str, None] = "271b8c23673a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
