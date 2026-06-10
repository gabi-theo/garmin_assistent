"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-06-06 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enable TimescaleDB extension
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

    # 2. Create 'users' table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('garmin_username', sa.String(), nullable=True),
        sa.Column('garmin_password_encrypted', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    
    # 3. Create 'metrics' table (time-series hypertable)
    op.create_table(
        'metrics',
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric', sa.String(), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('time', 'user_id', 'metric')
    )

    # Convert 'metrics' table to hypertable in TimescaleDB
    op.execute("SELECT create_hypertable('metrics', 'time', if_not_exists => TRUE);")

    # Create index on (user_id, metric, time DESC) for fast telemetry queries
    op.create_index(
        'idx_metrics_user_metric_time',
        'metrics',
        ['user_id', 'metric', sa.text('time DESC')],
        unique=False
    )

    # 4. Create 'insights' log table
    op.create_table(
        'insights',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric', sa.String(), nullable=False),
        sa.Column('insight', sa.String(), nullable=False),
        sa.Column('anomaly_detected', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deviation_pct', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. Create 'profile_snapshots' table (time-series hypertable)
    op.create_table(
        'profile_snapshots',
        sa.Column('time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('fatigue_score', sa.Float(), nullable=True),
        sa.Column('recovery_score', sa.Float(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('time', 'user_id')
    )

    # Convert 'profile_snapshots' table to hypertable in TimescaleDB
    op.execute("SELECT create_hypertable('profile_snapshots', 'time', if_not_exists => TRUE);")


def downgrade() -> None:
    op.drop_table('profile_snapshots')
    op.drop_table('insights')
    op.drop_index('idx_metrics_user_metric_time', table_name='metrics')
    op.drop_table('metrics')
    op.drop_table('users')
