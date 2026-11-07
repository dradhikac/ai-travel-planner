"""0001_baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-21 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline empty migration."""
    pass


def downgrade() -> None:
    """Baseline empty downgrade."""
    pass
