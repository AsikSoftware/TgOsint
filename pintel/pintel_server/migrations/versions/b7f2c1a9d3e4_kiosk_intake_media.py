"""kiosk intake: client details, media, ocenka import

Revision ID: b7f2c1a9d3e4
Revises: e35844762b95
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7f2c1a9d3e4'
down_revision = 'e35844762b95'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('client_phone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('has_box', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('has_cord', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('panic_full', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('upload_token', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('ocenka_device_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('ocenka_imported_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f('ix_evaluations_ocenka_device_id'), ['ocenka_device_id'], unique=False)
        batch_op.create_unique_constraint('uq_eval_upload_token', ['upload_token'])

    op.create_table(
        'evaluation_media',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('eval_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('filename', sa.String(length=160), nullable=False),
        sa.Column('content_type', sa.String(length=80), nullable=True),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('tg_file_id', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['eval_id'], ['evaluations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('evaluation_media', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evaluation_media_eval_id'), ['eval_id'], unique=False)


def downgrade():
    with op.batch_alter_table('evaluation_media', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evaluation_media_eval_id'))
    op.drop_table('evaluation_media')
    with op.batch_alter_table('evaluations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_eval_upload_token', type_='unique')
        batch_op.drop_index(batch_op.f('ix_evaluations_ocenka_device_id'))
        batch_op.drop_column('ocenka_imported_at')
        batch_op.drop_column('ocenka_device_id')
        batch_op.drop_column('upload_token')
        batch_op.drop_column('panic_full')
        batch_op.drop_column('has_cord')
        batch_op.drop_column('has_box')
        batch_op.drop_column('client_phone')
        batch_op.drop_column('client_name')
