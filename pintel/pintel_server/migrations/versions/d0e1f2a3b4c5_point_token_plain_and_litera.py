"""токен точки текстом и литера магазина: точками управляют в базе, не в кассе

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('points') as b:
        b.add_column(sa.Column('token', sa.String(length=64), nullable=True))
        b.add_column(sa.Column('litera', sa.String(length=8), nullable=True))
        b.create_unique_constraint('uq_points_token', ['token'])
        b.drop_constraint('uq_points_token_hash', type_='unique')
        b.drop_column('token_hash')


def downgrade():
    with op.batch_alter_table('points') as b:
        b.add_column(sa.Column('token_hash', sa.String(length=64), nullable=True))
        b.create_unique_constraint('uq_points_token_hash', ['token_hash'])
        b.drop_constraint('uq_points_token', type_='unique')
        b.drop_column('litera')
        b.drop_column('token')
