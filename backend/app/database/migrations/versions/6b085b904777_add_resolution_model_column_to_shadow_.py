"""add resolution_model column to shadow_signals

Adaptive platform Milestone 18c (2026-07-16, docs/RESEARCH_ROUND_1.md
recommendation #3). Milestone 14b's resolver (`app.portfolio.
shadow_resolver`) settled `ShadowSignal` outcomes against an OPTIMISTIC
model: instant, fee-free fills at the recorded signal price. That
optimism was proven decision-relevant by docs/ROBUSTNESS_REPORT.md (the
zero-fee/zero-delay assumptions materially changed a promotion verdict),
so this milestone replaces the resolution model with a realistic one --
1-candle entry delay, adverse slippage, and both-leg fees folded into
`resolved_r` (see `shadow_resolver.py`'s new docstring for the exact
formulas) -- WITHOUT touching any row already resolved under the old
model.

This migration adds exactly one purely-additive, nullable column:

  - resolution_model: which resolution model settled this row.
    NULL = a legacy row resolved before this migration existed, under
    the old (Milestone 14b) optimistic instant-fill model -- that NULL
    is its permanent, honest label; it is never backfilled, because
    doing so would misrepresent a genuinely different measurement
    regime as the new one. Non-NULL rows carry the resolver's
    `RESOLUTION_MODEL` constant (currently `"v2_realistic_fills"`) at
    the moment they were resolved, so future resolver revisions can add
    a `"v3_..."` value the same additive way without ever mixing
    regimes silently.

Evidence-honesty rationale (this migration's whole point): a
`resolved_r` computed under the old model and one computed under the
new model are NOT the same measurement -- one is an upper bound, the
other is fee/slippage/delay-adjusted. Mixing them into one evidence pool
(`app.portfolio.rolling_regime_performance.collect_regime_evidence`)
would silently blend two different instruments, exactly the failure
mode that module's own docstring already warns against for shadow-vs-
live pooling. `resolution_model` is what lets that module (and any
future consumer) distinguish the two regimes instead of guessing.

No table drops/alters beyond ADD COLUMN; downgrade removes exactly what
upgrade added.

Revision ID: 6b085b904777
Revises: 65aba13281ad
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b085b904777'
down_revision: Union[str, Sequence[str], None] = '65aba13281ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'shadow_signals',
        sa.Column('resolution_model', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('shadow_signals', 'resolution_model')
