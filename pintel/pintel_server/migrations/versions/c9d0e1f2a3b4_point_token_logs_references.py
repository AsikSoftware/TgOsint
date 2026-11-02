"""токен у точки, журнал программы и эталоны на сервере

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('points') as b:
        b.add_column(sa.Column('token_hash', sa.String(length=64), nullable=True))
        b.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        b.add_column(sa.Column('staff_name', sa.String(length=80), nullable=True))
        b.add_column(sa.Column('settings', sa.JSON(), nullable=True))
        b.create_unique_constraint('uq_points_token_hash', ['token_hash'])

    op.create_table(
        'kiosk_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('point_id', sa.Integer(), sa.ForeignKey('points.id'), nullable=True),
        sa.Column('kiosk_id', sa.Integer(), sa.ForeignKey('kiosks.id'), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('line', sa.Text(), nullable=False),
    )
    op.create_index('ix_kiosk_logs_at', 'kiosk_logs', ['at'])
    op.create_index('ix_kiosk_logs_point_id', 'kiosk_logs', ['point_id'])
    op.create_index('ix_kiosk_logs_kiosk_id', 'kiosk_logs', ['kiosk_id'])

    op.create_table(
        'reference_bundles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('point_id', sa.Integer(), sa.ForeignKey('points.id'), nullable=True),
        sa.Column('kiosk_id', sa.Integer(), sa.ForeignKey('kiosks.id'), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('model_name', sa.String(length=64), nullable=True),
        sa.Column('ios', sa.String(length=16), nullable=True),
        sa.Column('verdict', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_reference_bundles_name', 'reference_bundles', ['name'], unique=True)
    op.create_index('ix_reference_bundles_point_id', 'reference_bundles', ['point_id'])
    op.create_index('ix_reference_bundles_created_at', 'reference_bundles', ['created_at'])


def downgrade():
    op.drop_table('reference_bundles')
    op.drop_table('kiosk_logs')
    with op.batch_alter_table('points') as b:
        b.drop_constraint('uq_points_token_hash', type_='unique')
        b.drop_column('settings')
        b.drop_column('staff_name')
        b.drop_column('is_active')
        b.drop_column('token_hash')
