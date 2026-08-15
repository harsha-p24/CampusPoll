"""performance indexes

Revision ID: 002_performance_indexes
Revises: 001_initial
Create Date: 2024-04-29
"""
from alembic import op

revision      = '002_performance_indexes'
down_revision = '001_initial'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_index('ix_votes_voter_election',    'votes',            ['voter_id', 'election_id'])
    op.create_index('ix_analytics_user_time',     'analytics_events', ['user_id', 'timestamp'])
    op.create_index('ix_login_attempts_ip_time',  'login_attempts',   ['ip_address', 'attempted_at'])

    # Fraud logs table
    op.create_table('fraud_logs',
        __import__('sqlalchemy').Column('id',          __import__('sqlalchemy').Integer(),     primary_key=True),
        __import__('sqlalchemy').Column('voter_id',    __import__('sqlalchemy').Integer(),     nullable=True),
        __import__('sqlalchemy').Column('election_id', __import__('sqlalchemy').Integer(),     nullable=True),
        __import__('sqlalchemy').Column('risk_score',  __import__('sqlalchemy').Float(),       nullable=False),
        __import__('sqlalchemy').Column('flags',       __import__('sqlalchemy').String(500),   nullable=True),
        __import__('sqlalchemy').Column('action',      __import__('sqlalchemy').String(20),    nullable=True),
        __import__('sqlalchemy').Column('created_at',  __import__('sqlalchemy').DateTime(),    nullable=True),
    )
    op.create_index('ix_fraud_logs_voter',    'fraud_logs', ['voter_id'])
    op.create_index('ix_fraud_logs_election', 'fraud_logs', ['election_id'])


def downgrade():
    op.drop_table('fraud_logs')
    op.drop_index('ix_votes_voter_election',   'votes')
    op.drop_index('ix_analytics_user_time',    'analytics_events')
    op.drop_index('ix_login_attempts_ip_time', 'login_attempts')
