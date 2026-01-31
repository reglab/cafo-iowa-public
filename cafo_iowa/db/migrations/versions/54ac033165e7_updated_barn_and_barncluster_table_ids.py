"""updated barn and barncluster table ids

Revision ID: 54ac033165e7
Revises: b8049949f568
Create Date: 2025-04-22 12:45:08.248194

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "54ac033165e7"
down_revision: Union[str, None] = "b8049949f568"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
