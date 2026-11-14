"""add verdict check constraint

Adds a database-level CHECK constraint restricting answers.verdict to the three
canonical states (correct / incorrect / unmarked). Portable across engines:

- PostgreSQL: emitted as a native ALTER TABLE ... ADD CONSTRAINT.
- SQLite: applied through batch mode (table copy), since SQLite can't ALTER a
  table to add a constraint in place.

Note: this assumes existing rows already satisfy the constraint. The only writer
is the grading ingest layer, which always maps verdicts to these three values,
so no data backfill is needed. If a database somehow holds other values, clean
them up before upgrading.

Revision ID: 54aeeb1858ea
Revises: 99dff7064e9a
Create Date: 2026-10-10 10:27:31.537467

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "54aeeb1858ea"
down_revision: Union[str, None] = "99dff7064e9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_answer_verdict_valid"
TABLE_NAME = "answers"
CHECK_SQL = "verdict IN ('correct', 'incorrect', 'unmarked')"


def upgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.create_check_constraint(CONSTRAINT_NAME, CHECK_SQL)


def downgrade() -> None:
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
