"""staff check of Apple parts & service history

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('staff_parts', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.drop_column('staff_parts')
