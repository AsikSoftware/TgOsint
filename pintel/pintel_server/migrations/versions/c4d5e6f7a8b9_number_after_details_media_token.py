"""number issued after client details; separate media token

Revision ID: c4d5e6f7a8b9
Revises: b7f2c1a9d3e4
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b7f2c1a9d3e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.alter_column('number', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('media_token', sa.String(length=32), nullable=True))
        batch_op.create_unique_constraint('uq_eval_media_token', ['media_token'])


def downgrade():
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_eval_media_token', type_='unique')
        batch_op.drop_column('media_token')
        batch_op.alter_column('number', existing_type=sa.Integer(), nullable=False)
