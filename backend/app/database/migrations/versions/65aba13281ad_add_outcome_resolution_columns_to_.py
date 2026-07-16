"""add outcome resolution columns to shadow_signals

Adaptive platform Milestone 14a (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md
section 4.3). shadow_signals (Milestone 11) rows record what a non-active
strategy WOULD have done -- entry/stop/tp/rr -- but nothing records how
that would have played out. This migration adds three purely-additive,
nullable columns so a future resolver (Milestone 14b, separate task) can
walk subsequent candles and settle each shadow signal:

  - outcome: "tp" / "sl" / "expired" (NULL = unresolved/open)
  - resolved_at: UTC timestamp of when the resolver settled the signal
  - resolved_r: realized R multiple (+rr for "tp", -1.0 for "sl", NULL
    for "expired") -- the resolver enforces this, not the DB

No table drops/alters beyond ADD COLUMN; downgrade removes exactly what
upgrade added.

Revision ID: 65aba13281ad
Revises: 36cb62e9e2ac
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65aba13281ad'
down_revision: Union[str, Sequence[str], None] = '36cb62e9e2ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('shadow_signals', sa.Column('outcome', sa.String(length=16), nullable=True))
    op.add_column('shadow_signals', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shadow_signals', sa.Column('resolved_r', sa.Float(), nullable=True))
    op.create_index(
        op.f('ix_shadow_signals_outcome'),
        'shadow_signals', ['outcome'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shadow_signals_outcome'), table_name='shadow_signals')
    op.drop_column('shadow_signals', 'resolved_r')
    op.drop_column('shadow_signals', 'resolved_at')
    op.drop_column('shadow_signals', 'outcome')
