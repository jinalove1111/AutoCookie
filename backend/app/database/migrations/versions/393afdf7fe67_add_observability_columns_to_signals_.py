"""add observability columns to signals and trades

Revision ID: 393afdf7fe67
Revises: 4b8a822a475b
Create Date: 2026-07-12 23:17:48.611584

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '393afdf7fe67'
down_revision: Union[str, Sequence[str], None] = '4b8a822a475b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # All 4 nullable, no server_default needed -- existing rows simply get
    # NULL, exactly matching their true prior state (this data was never
    # captured before this migration). See ENGINEERING_DECISIONS.md #40.
    op.add_column('signals', sa.Column('rejection_reason', sa.String(length=1024), nullable=True))
    op.add_column('trades', sa.Column('exit_reason', sa.String(length=32), nullable=True))
    op.add_column('trades', sa.Column('r_multiple', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('strategy_config', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('trades', 'strategy_config')
    op.drop_column('trades', 'r_multiple')
    op.drop_column('trades', 'exit_reason')
    op.drop_column('signals', 'rejection_reason')
