"""тест на телефоне клиента по временной ссылке

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'phone_tests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token', sa.String(length=32), nullable=False),
        sa.Column('kiosk_id', sa.Integer(), sa.ForeignKey('kiosks.id'), nullable=True),
        sa.Column('eval_id', sa.Integer(), sa.ForeignKey('evaluations.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('device', sa.String(length=200), nullable=True),
    )
    op.create_index('ix_phone_tests_token', 'phone_tests', ['token'], unique=True)
    op.create_index('ix_phone_tests_eval_id', 'phone_tests', ['eval_id'])
    op.create_index('ix_phone_tests_created_at', 'phone_tests', ['created_at'])


def downgrade():
    op.drop_index('ix_phone_tests_created_at', table_name='phone_tests')
    op.drop_index('ix_phone_tests_eval_id', table_name='phone_tests')
    op.drop_index('ix_phone_tests_token', table_name='phone_tests')
    op.drop_table('phone_tests')
