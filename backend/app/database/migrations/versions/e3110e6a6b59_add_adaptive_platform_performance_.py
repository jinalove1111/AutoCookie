"""add adaptive platform performance tracking columns and snapshot table

Revision ID: e3110e6a6b59
Revises: 393afdf7fe67
Create Date: 2026-07-15 20:57:24.720821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3110e6a6b59'
down_revision: Union[str, Sequence[str], None] = '393afdf7fe67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # All 6 nullable, no server_default needed -- existing rows simply get
    # NULL, matching their true prior state (this data was never captured
    # before this migration). See ENGINEERING_DECISIONS.md #44.
    op.add_column('trades', sa.Column('market_regime', sa.JSON(), nullable=True))
    op.add_column('trades', sa.Column('strategy_name', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_trades_strategy_name'), 'trades', ['strategy_name'], unique=False)
    op.add_column('trades', sa.Column('holding_time_seconds', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('max_adverse_excursion', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('max_favorable_excursion', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('latency_ms', sa.Float(), nullable=True))

    op.create_table(
        'strategy_performance_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('strategy_name', sa.String(length=32), nullable=False),
        sa.Column('market_regime', sa.String(length=32), nullable=True),
        sa.Column('window_trades', sa.Integer(), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('win_rate', sa.Float(), nullable=False),
        sa.Column('profit_factor', sa.Float(), nullable=False),
        sa.Column('expectancy', sa.Float(), nullable=False),
        sa.Column('max_drawdown', sa.Float(), nullable=False),
        sa.Column('sharpe', sa.Float(), nullable=False),
        sa.Column('sortino', sa.Float(), nullable=False),
        sa.Column('recovery_factor', sa.Float(), nullable=False),
        sa.Column('is_disabled', sa.Boolean(), nullable=False),
        sa.Column('disabled_reason', sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_strategy_performance_snapshots_strategy_name'),
        'strategy_performance_snapshots', ['strategy_name'], unique=False,
    )
    op.create_index(
        op.f('ix_strategy_performance_snapshots_market_regime'),
        'strategy_performance_snapshots', ['market_regime'], unique=False,
    )
    op.create_index(
        op.f('ix_strategy_performance_snapshots_computed_at'),
        'strategy_performance_snapshots', ['computed_at'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_strategy_performance_snapshots_computed_at'), table_name='strategy_performance_snapshots')
    op.drop_index(op.f('ix_strategy_performance_snapshots_market_regime'), table_name='strategy_performance_snapshots')
    op.drop_index(op.f('ix_strategy_performance_snapshots_strategy_name'), table_name='strategy_performance_snapshots')
    op.drop_table('strategy_performance_snapshots')

    op.drop_column('trades', 'latency_ms')
    op.drop_column('trades', 'max_favorable_excursion')
    op.drop_column('trades', 'max_adverse_excursion')
    op.drop_column('trades', 'holding_time_seconds')
    op.drop_index(op.f('ix_trades_strategy_name'), table_name='trades')
    op.drop_column('trades', 'strategy_name')
    op.drop_column('trades', 'market_regime')
