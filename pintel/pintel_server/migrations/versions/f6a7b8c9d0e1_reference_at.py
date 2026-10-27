"""эталоны из потока: отметка о выгрузке аппарата

Revision ID: f6a7b8c9d0e1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('evaluations') as b:
        b.add_column(sa.Column('reference_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('evaluations') as b:
        b.drop_column('reference_at')
