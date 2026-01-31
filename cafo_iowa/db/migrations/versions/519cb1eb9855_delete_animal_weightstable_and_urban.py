"""delete animal weightstable and urban

Revision ID: 519cb1eb9855
Revises: a12299dea699
Create Date: 2025-04-19 11:32:01.163566

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "519cb1eb9855"
down_revision: Union[str, None] = "a12299dea699"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
