"""прайс на сервере кассы убран: цену сделки считает бот Оценки, таблица была пустой

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('price_grids', schema=None) as b:
        b.drop_index(b.f('ix_price_grids_is_current'))
    op.drop_table('price_grids')


def downgrade():
    op.create_table(
        'price_grids',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('models_count', sa.Integer(), nullable=False),
        sa.Column('positions_count', sa.Integer(), nullable=False),
        sa.Column('grid', sa.JSON(), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('fetched_by', sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('price_grids', schema=None) as b:
        b.create_index(b.f('ix_price_grids_is_current'), ['is_current'], unique=False)
