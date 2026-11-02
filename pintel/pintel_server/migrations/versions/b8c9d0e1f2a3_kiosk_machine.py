"""киоск узнаёт себя сам: имя машины вместо раздачи токенов руками

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('kiosks') as b:
        b.add_column(sa.Column('machine', sa.String(length=80), nullable=True))
    op.create_index('ix_kiosks_machine', 'kiosks', ['machine'])


def downgrade():
    op.drop_index('ix_kiosks_machine', table_name='kiosks')
    with op.batch_alter_table('kiosks') as b:
        b.drop_column('machine')
