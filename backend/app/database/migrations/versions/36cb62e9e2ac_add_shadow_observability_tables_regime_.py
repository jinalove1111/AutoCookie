"""add shadow observability tables (regime_snapshots, shadow_signals)

Adaptive platform Milestone 11 (2026-07-16, docs/ADAPTIVE_ARCHITECTURE.md
sections 2.4/6). Purely additive -- two brand-new tables, no changes to
any existing table. Schema-only: milestone 11b wires paper trading to
write to these tables (behind a default-off flag); this migration just
gives it somewhere to write.

Revision ID: 36cb62e9e2ac
Revises: e3110e6a6b59
Create Date: 2026-07-16 03:36:36.192345

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36cb62e9e2ac'
down_revision: Union[str, Sequence[str], None] = 'e3110e6a6b59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'regime_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('timeframe', sa.String(length=16), nullable=False),
        sa.Column('trend', sa.String(length=32), nullable=False),
        sa.Column('volatility', sa.String(length=32), nullable=False),
        sa.Column('breakout', sa.Boolean(), nullable=False),
        sa.Column('mean_reversion', sa.Boolean(), nullable=False),
        sa.Column('liquidity_sweep_environment', sa.Boolean(), nullable=False),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_regime_snapshots_captured_at'),
        'regime_snapshots', ['captured_at'], unique=False,
    )
    op.create_index(
        op.f('ix_regime_snapshots_symbol'),
        'regime_snapshots', ['symbol'], unique=False,
    )

    op.create_table(
        'shadow_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('strategy_name', sa.String(length=32), nullable=False),
        sa.Column('strategy_version', sa.String(length=32), nullable=True),
        sa.Column('direction', sa.String(length=8), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('stop_loss', sa.Float(), nullable=False),
        sa.Column('take_profit', sa.Float(), nullable=False),
        sa.Column('rr', sa.Float(), nullable=False),
        sa.Column('market_regime', sa.JSON(), nullable=True),
        sa.Column('signal_payload', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_shadow_signals_captured_at'),
        'shadow_signals', ['captured_at'], unique=False,
    )
    op.create_index(
        op.f('ix_shadow_signals_strategy_name'),
        'shadow_signals', ['strategy_name'], unique=False,
    )
    op.create_index(
        op.f('ix_shadow_signals_symbol'),
        'shadow_signals', ['symbol'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shadow_signals_symbol'), table_name='shadow_signals')
    op.drop_index(op.f('ix_shadow_signals_strategy_name'), table_name='shadow_signals')
    op.drop_index(op.f('ix_shadow_signals_captured_at'), table_name='shadow_signals')
    op.drop_table('shadow_signals')

    op.drop_index(op.f('ix_regime_snapshots_symbol'), table_name='regime_snapshots')
    op.drop_index(op.f('ix_regime_snapshots_captured_at'), table_name='regime_snapshots')
    op.drop_table('regime_snapshots')
