"""add_episodes_table

Revision ID: 3f1c2a9d4e5b
Revises: 80a2108a685a
Create Date: 2026-07-04

Episodic memory (DCL-054): one timestamped record per agent task, queryable
by date and tag, linked to tasks (and through task_id to audit events).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3f1c2a9d4e5b'
down_revision: Union[str, Sequence[str], None] = '80a2108a685a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'episodes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_id', sa.String(length=36), nullable=True),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('outcome', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('episodes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_episodes_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_episodes_started_at'), ['started_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('episodes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_episodes_started_at'))
        batch_op.drop_index(batch_op.f('ix_episodes_task_id'))
    op.drop_table('episodes')
